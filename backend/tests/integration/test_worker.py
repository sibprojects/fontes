import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from fontes.adapters.messaging.connection import AmqpConnection
from fontes.adapters.persistence.documents import SqlDocumentRepository
from fontes.application.ports.ingestion import DocumentProcessor
from fontes.config import Settings
from fontes.container import build_app, build_worker
from fontes.domain.documents import Document, DocumentStatus

pytestmark = pytest.mark.integration

WAIT_SECONDS = 10.0


@asynccontextmanager
async def running_worker(
    settings: Settings, processor: DocumentProcessor | None = None
) -> AsyncIterator[None]:
    stop = asyncio.Event()
    task = asyncio.create_task(build_worker(settings, processor).run(stop))
    try:
        yield
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=WAIT_SECONDS)


async def until(
    repo: SqlDocumentRepository, doc: Document, done: Callable[[Document], bool]
) -> Document:
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        current = await repo.get(doc.id)
        assert current is not None
        if done(current):
            return current
        if time.monotonic() > deadline:
            raise AssertionError(f"document stuck in {current.status}")
        await asyncio.sleep(0.05)


class AlwaysDown:
    async def process(self, doc: Document) -> None:
        raise ConnectionError("embedding service down")


async def test_upload_goes_queued_to_ready_through_rabbitmq(
    repo: SqlDocumentRepository, settings: Settings
) -> None:
    settings = settings.model_copy(update={"stub_processing_seconds": 0})
    app = build_app(settings)
    async with (
        running_worker(settings),
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        r = await c.post("/documents", files={"file": ("a.md", b"# a")})
        assert r.status_code == 201
        deadline = time.monotonic() + WAIT_SECONDS
        while (doc := (await c.get("/documents")).json()[0])["status"] != "ready":
            assert time.monotonic() < deadline, f"document stuck in {doc['status']}"
            await asyncio.sleep(0.05)
    assert doc["attempts"] == 1


async def test_worker_sweep_publishes_queued_documents(
    repo: SqlDocumentRepository, settings: Settings
) -> None:
    settings = settings.model_copy(update={"stub_processing_seconds": 0})
    doc = Document.from_upload("lost.pdf", "hash-lost", now=datetime.now(UTC))
    await repo.add(doc)  # queued, but its message never reached the broker
    async with running_worker(settings):
        ready = await until(repo, doc, lambda d: d.status == DocumentStatus.READY)
    assert ready.attempts == 1


async def test_failing_processor_ends_failed_in_dlq(
    repo: SqlDocumentRepository, settings: Settings
) -> None:
    settings = settings.model_copy(update={"ingest_retry_delay_ms": 100})
    doc = Document.from_upload("a.pdf", "hash-a", now=datetime.now(UTC))
    await repo.add(doc)
    async with running_worker(settings, AlwaysDown()):
        failed = await until(repo, doc, lambda d: d.status == DocumentStatus.FAILED)
    assert failed.attempts == 3
    assert failed.error == "ConnectionError: embedding service down"

    connection = AmqpConnection(settings.rabbitmq_url, connect_timeout=3.0)
    try:
        channel = await (await connection.get()).channel()
        dlq = await channel.declare_queue(f"{settings.amqp_prefix}.ingest.dlq", passive=True)
        assert dlq.declaration_result.message_count == 1
    finally:
        await connection.close()
