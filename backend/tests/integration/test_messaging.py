import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID, uuid4

import aio_pika
import pytest

from fontes.adapters.messaging.connection import AmqpConnection
from fontes.adapters.messaging.consumer import IngestConsumer
from fontes.adapters.messaging.health import RabbitMQHealthCheck
from fontes.adapters.messaging.publisher import AmqpPublisher
from fontes.adapters.messaging.topology import Topology
from fontes.application.ingestion import IngestOutcome, IngestResult
from fontes.config import Settings

pytestmark = pytest.mark.integration

ACK = IngestResult(IngestOutcome.ACK)
RETRY = IngestResult(IngestOutcome.RETRY, "ConnectionError: down")
WAIT_SECONDS = 5.0


class ScriptedHandler:
    """Plays its script one step per call; the last step repeats."""

    def __init__(self, *script: IngestResult | Exception, block: asyncio.Event | None = None):
        self.script = list(script)
        self.block = block
        self.calls: list[tuple[UUID, float]] = []

    async def __call__(self, document_id: UUID) -> IngestResult:
        self.calls.append((document_id, time.monotonic()))
        if self.block is not None:
            await self.block.wait()
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        return step


async def eventually(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


@pytest.fixture
async def amqp() -> AsyncIterator[tuple[AmqpConnection, Topology]]:
    connection = AmqpConnection(Settings().rabbitmq_url, connect_timeout=3.0)
    topology = Topology(f"test-{uuid4().hex[:8]}", retry_delay_ms=200)
    yield connection, topology
    channel = await (await connection.get()).channel()
    for name in (topology.main, topology.retry, topology.dlq):
        await channel.queue_delete(name)
    await connection.close()


async def _get(connection: AmqpConnection, queue: str) -> Any:
    """The next message waiting in `queue` (acked); AssertionError if none arrives in time."""
    channel = await (await connection.get()).channel()
    q = await channel.declare_queue(queue, passive=True)
    deadline = time.monotonic() + WAIT_SECONDS
    while (message := await q.get(no_ack=True, fail=False)) is None:
        if time.monotonic() > deadline:
            raise AssertionError(f"no message in {queue}")
        await asyncio.sleep(0.02)
    await channel.close()
    return message


async def _count(connection: AmqpConnection, queue: str) -> int:
    channel = await (await connection.get()).channel()
    declared = await channel.declare_queue(queue, passive=True)
    await channel.close()
    count = declared.declaration_result.message_count
    assert count is not None
    return count


def _consumer(
    connection: AmqpConnection, topology: Topology, handler: ScriptedHandler, max_crashes: int = 3
) -> IngestConsumer:
    return IngestConsumer(connection, topology, handler, max_crashes=max_crashes, prefetch=1)


async def test_declare_is_idempotent(amqp: tuple[AmqpConnection, Topology]) -> None:
    connection, topology = amqp
    channel = await (await connection.get()).channel()
    await topology.declare(channel)
    await topology.declare(channel)
    # The retry queue's TTL and dead-letter arguments route an expired message to main.
    await channel.default_exchange.publish(aio_pika.Message(b"x"), routing_key=topology.retry)
    started = time.monotonic()
    message = await _get(connection, topology.main)
    assert message.body == b"x"
    assert time.monotonic() - started >= 0.15
    assert await _count(connection, topology.dlq) == 0


async def test_published_message_is_consumed_and_acked(
    amqp: tuple[AmqpConnection, Topology],
) -> None:
    connection, topology = amqp
    handler = ScriptedHandler(ACK)
    consumer = _consumer(connection, topology, handler)
    await consumer.start()
    try:
        document_id = uuid4()
        await AmqpPublisher(connection, topology).publish_ingest(document_id)
        await eventually(lambda: len(handler.calls) == 1)
        assert handler.calls[0][0] == document_id
    finally:
        await consumer.stop()
    assert await _count(connection, topology.main) == 0


async def test_retry_comes_back_after_ttl(amqp: tuple[AmqpConnection, Topology]) -> None:
    connection, topology = amqp
    handler = ScriptedHandler(RETRY, ACK)
    consumer = _consumer(connection, topology, handler)
    await consumer.start()
    try:
        document_id = uuid4()
        await AmqpPublisher(connection, topology).publish_ingest(document_id)
        await eventually(lambda: len(handler.calls) == 2)
    finally:
        await consumer.stop()
    (first_id, first_at), (second_id, second_at) = handler.calls
    assert first_id == second_id == document_id
    # TTL is 0.2 s; leave slack for clock granularity (~15 ms on Windows).
    assert second_at - first_at >= 0.15
    assert await _count(connection, topology.dlq) == 0


async def test_dead_letter_lands_in_dlq_with_error(amqp: tuple[AmqpConnection, Topology]) -> None:
    connection, topology = amqp
    consumer = _consumer(
        connection, topology, ScriptedHandler(IngestResult(IngestOutcome.DEAD_LETTER, "corrupt"))
    )
    await consumer.start()
    try:
        document_id = uuid4()
        await AmqpPublisher(connection, topology).publish_ingest(document_id)
        message = await _get(connection, topology.dlq)
    finally:
        await consumer.stop()
    assert json.loads(message.body) == {"document_id": str(document_id)}
    assert message.headers["x-fontes-error"] == "corrupt"
    assert await _count(connection, topology.dlq) == 0


async def test_poison_message_goes_to_dlq(amqp: tuple[AmqpConnection, Topology]) -> None:
    connection, topology = amqp
    handler = ScriptedHandler(ACK)
    consumer = _consumer(connection, topology, handler)
    await consumer.start()
    try:
        channel = await (await connection.get()).channel()
        await channel.default_exchange.publish(
            aio_pika.Message(b"not json"), routing_key=topology.main
        )
        message = await _get(connection, topology.dlq)
    finally:
        await consumer.stop()
    assert message.body == b"not json"
    assert "x-fontes-error" in message.headers
    assert handler.calls == []


async def test_deeply_nested_body_goes_to_dlq(amqp: tuple[AmqpConnection, Topology]) -> None:
    connection, topology = amqp
    handler = ScriptedHandler(ACK)
    consumer = _consumer(connection, topology, handler)
    await consumer.start()
    try:
        channel = await (await connection.get()).channel()
        await channel.default_exchange.publish(
            aio_pika.Message(b"[" * 100_000), routing_key=topology.main
        )
        message = await _get(connection, topology.dlq)
        # The worker is not stalled: the next valid message is still consumed.
        document_id = uuid4()
        await AmqpPublisher(connection, topology).publish_ingest(document_id)
        await eventually(lambda: len(handler.calls) == 1)
    finally:
        await consumer.stop()
    assert message.body == b"[" * 100_000
    assert "RecursionError" in message.headers["x-fontes-error"]
    assert handler.calls[0][0] == document_id


async def test_handler_crash_is_retried_then_dead_lettered(
    amqp: tuple[AmqpConnection, Topology],
) -> None:
    connection, topology = amqp
    handler = ScriptedHandler(RuntimeError("db down"))
    consumer = _consumer(connection, topology, handler, max_crashes=2)
    await consumer.start()
    try:
        await AmqpPublisher(connection, topology).publish_ingest(uuid4())
        message = await _get(connection, topology.dlq)
    finally:
        await consumer.stop()
    assert len(handler.calls) == 3
    assert message.headers["x-fontes-error"] == "RuntimeError: db down"


async def test_unacked_message_is_redelivered_after_consumer_dies(
    amqp: tuple[AmqpConnection, Topology],
) -> None:
    connection, topology = amqp
    release = asyncio.Event()
    stuck = ScriptedHandler(ACK, block=release)
    first = _consumer(connection, topology, stuck)
    await first.start()
    document_id = uuid4()
    await AmqpPublisher(connection, topology).publish_ingest(document_id)
    await eventually(lambda: len(stuck.calls) == 1)
    await first.stop()  # dies holding the unacked message

    healthy = ScriptedHandler(ACK)
    second = _consumer(connection, topology, healthy)
    await second.start()
    try:
        await eventually(lambda: len(healthy.calls) == 1)
    finally:
        await second.stop()
        release.set()
    assert healthy.calls[0][0] == document_id


async def test_health_uses_shared_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[object] = []
    real_connect = aio_pika.connect_robust

    async def counting_connect(*args: Any, **kwargs: Any) -> Any:
        connection = await real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(aio_pika, "connect_robust", counting_connect)
    connection = AmqpConnection(Settings().rabbitmq_url, connect_timeout=3.0)
    check = RabbitMQHealthCheck(connection)
    try:
        await check.check()
        await check.check()
    finally:
        await connection.close()
    assert len(opened) == 1
