import asyncio
from uuid import UUID

from aio_pika.abc import AbstractRobustChannel

from fontes.adapters.messaging.connection import AmqpConnection
from fontes.adapters.messaging.topology import Topology, encode_document_id, ingest_message


class AmqpPublisher:
    """Publishes ingest messages; returns only after the broker has confirmed them."""

    def __init__(self, connection: AmqpConnection, topology: Topology) -> None:
        self._connection = connection
        self._topology = topology
        self._channel: AbstractRobustChannel | None = None
        self._lock = asyncio.Lock()

    async def publish_ingest(self, document_id: UUID) -> None:
        channel = await self._get_channel()
        await channel.default_exchange.publish(
            ingest_message(encode_document_id(document_id)),
            routing_key=self._topology.main,
            mandatory=True,  # an unroutable message raises instead of vanishing
        )

    async def _get_channel(self) -> AbstractRobustChannel:
        async with self._lock:
            if self._channel is None or self._channel.is_closed:
                connection = await self._connection.get()
                channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
                # Declaring here too means a message published before the worker ever ran
                # still has a queue to land in.
                await self._topology.declare(channel)
                self._channel = channel
            return self._channel
