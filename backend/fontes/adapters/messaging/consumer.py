import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from aio_pika.abc import AbstractIncomingMessage, AbstractQueue, AbstractRobustChannel

from fontes.adapters.messaging.connection import AmqpConnection
from fontes.adapters.messaging.topology import (
    CRASHES_HEADER,
    ERROR_HEADER,
    Topology,
    decode_document_id,
    ingest_message,
)
from fontes.application.ingestion import IngestOutcome, IngestResult

log = logging.getLogger(__name__)


class IngestConsumer:
    """Feeds the main queue to `handle` and carries out its decision.

    Retry and dead-letter are republished copies (with the error in a header), acked only
    after the broker confirms the copy. If the copy fails, the original goes back to the queue.
    """

    def __init__(
        self,
        connection: AmqpConnection,
        topology: Topology,
        handle: Callable[[UUID], Awaitable[IngestResult]],
        max_crashes: int,
        prefetch: int,
    ) -> None:
        self._connection = connection
        self._topology = topology
        self._handle = handle
        self._max_crashes = max_crashes
        self._prefetch = prefetch
        self._channel: AbstractRobustChannel | None = None
        self._queue: AbstractQueue | None = None
        self._tag: str | None = None

    async def start(self) -> None:
        connection = await self._connection.get()
        self._channel = await connection.channel(publisher_confirms=True)
        await self._channel.set_qos(prefetch_count=self._prefetch)
        await self._topology.declare(self._channel)
        self._queue = await self._channel.get_queue(self._topology.main)
        self._tag = await self._queue.consume(self._on_message)

    async def stop(self) -> None:
        """Stop taking messages; any still unacked go back to the queue with the channel."""
        if self._queue is not None and self._tag is not None:
            await self._queue.cancel(self._tag)
        if self._channel is not None:
            await self._channel.close()
        self._channel = self._queue = self._tag = None

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        try:
            document_id = decode_document_id(message.body)
        except ValueError as exc:
            log.warning("Poison message sent to %s: %s", self._topology.dlq, exc)
            await self._forward(message, self._topology.dlq, str(exc))
            return

        try:
            result = await self._handle(document_id)
        except Exception as exc:
            crashes = _int_header(message, CRASHES_HEADER) + 1
            log.exception("Handler crashed on %s (crash %d)", document_id, crashes)
            target = self._topology.retry if crashes <= self._max_crashes else self._topology.dlq
            await self._forward(message, target, f"{type(exc).__name__}: {exc}", crashes)
            return

        if result.outcome == IngestOutcome.ACK:
            await message.ack()
        elif result.outcome == IngestOutcome.RETRY:
            await self._forward(message, self._topology.retry, result.error)
        else:
            await self._forward(message, self._topology.dlq, result.error)

    async def _forward(
        self,
        message: AbstractIncomingMessage,
        queue: str,
        error: str | None,
        crashes: int | None = None,
    ) -> None:
        headers = dict(message.headers)
        if error is not None:
            headers[ERROR_HEADER] = error
        if crashes is not None:
            headers[CRASHES_HEADER] = crashes
        try:
            assert self._channel is not None
            await self._channel.default_exchange.publish(
                ingest_message(message.body, headers), routing_key=queue
            )
        except Exception:
            log.exception("Could not forward a message to %s; requeueing it", queue)
            await message.nack(requeue=True)
            return
        await message.ack()


def _int_header(message: AbstractIncomingMessage, name: str) -> int:
    value = message.headers.get(name)
    return value if isinstance(value, int) else 0
