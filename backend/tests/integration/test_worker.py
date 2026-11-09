import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from fontes.adapters.messaging.connection import AmqpConnection
from fontes.adapters.persistence.documents import SqlDocumentRepository
from fontes.adapters.storage.local import LocalFileStorage
from fontes.application.ports.ingestion import DocumentProcessor
from fontes.config import Settings
from fontes.container import build_app, build_worker
from fontes.domain.documents import Document, DocumentStatus
from tests.fakes import FakeEmbedder
from tests.pdf_factory import make_pdf

pytestmark = pytest.mark.integration

WAIT_SECONDS = 10.0


@asynccontextmanager
async def running_worker(
    settings: Settings, processor: DocumentProcessor | None = None
) -> AsyncIterator[None]:
    stop = asyncio.Event()
    worker = build_worker(settings, processor, embedder=FakeEmbedder())
    task = asyncio.create_task(worker.run(stop))
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


@asynccontextmanager
async def api_and_worker(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = build_app(settings)
    async with (
        running_worker(settings),
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


async def upload_until_done(c: AsyncClient, name: str, data: bytes) -> dict[str, Any]:
    """Uploads a file and waits until the worker has finished with it (ready or failed)."""
    r = await c.post("/documents", files={"file": (name, data)})
    assert r.status_code == 201
    doc_id = r.json()["id"]
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        doc: dict[str, Any] = next(
            d for d in (await c.get("/documents")).json() if d["id"] == doc_id
        )
        if doc["status"] in ("ready", "failed"):
            return doc
        assert time.monotonic() < deadline, f"document stuck in {doc['status']}"
        await asyncio.sleep(0.05)


async def chunk_locations(c: AsyncClient, doc_id: str) -> list[str]:
    r = await c.get(f"/documents/{doc_id}/chunks")
    assert r.status_code == 200
    return [chunk["location"] for chunk in r.json()]


async def test_upload_goes_queued_to_ready_through_rabbitmq(
    repo: SqlDocumentRepository, settings: Settings
) -> None:
    async with api_and_worker(settings) as c:
        doc = await upload_until_done(c, "a.md", b"# a\n\nSome text.")
    assert (doc["status"], doc["attempts"]) == ("ready", 1)


async def test_markdown_upload_ends_up_as_chunks(
    repo: SqlDocumentRepository, settings: Settings
) -> None:
    body = "# A\n\n" + "alpha words " * 40 + "\n\n# B\n\n" + "beta words " * 40
    async with api_and_worker(settings) as c:
        doc = await upload_until_done(c, "notes.md", body.encode())
        assert doc["status"] == "ready"
        assert await chunk_locations(c, doc["id"]) == ["A", "B"]


async def test_pdf_upload_cites_pages(repo: SqlDocumentRepository, settings: Settings) -> None:
    pdf = make_pdf(["first page " * 40, "second page " * 40])
    async with api_and_worker(settings) as c:
        doc = await upload_until_done(c, "paper.pdf", pdf)
        assert doc["status"] == "ready"
        assert await chunk_locations(c, doc["id"]) == ["p. 1", "p. 2"]


async def test_unreadable_pdf_fails_without_retry(
    repo: SqlDocumentRepository, settings: Settings
) -> None:
    async with api_and_worker(settings) as c:
        doc = await upload_until_done(c, "a.pdf", b"%PDF-1.4 garbage")
    assert (doc["status"], doc["attempts"]) == ("failed", 1)
    assert "Could not read the PDF" in doc["error"]


async def test_delete_removes_chunks(repo: SqlDocumentRepository, settings: Settings) -> None:
    async with api_and_worker(settings) as c:
        doc = await upload_until_done(c, "a.md", b"# a\n\nSome text.")
        assert doc["status"] == "ready"
        assert await chunk_locations(c, doc["id"]) == ["a"]
        assert (await c.delete(f"/documents/{doc['id']}")).status_code == 204
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            count = await conn.scalar(
                text("SELECT count(*) FROM chunks WHERE document_id = :id"), {"id": doc["id"]}
            )
    finally:
        await engine.dispose()
    assert count == 0


async def test_worker_sweep_publishes_queued_documents(
    repo: SqlDocumentRepository, settings: Settings
) -> None:
    doc = Document.from_upload("lost.md", "hash-lost", now=datetime.now(UTC))
    assert doc.storage_key is not None
    await LocalFileStorage(settings.storage_dir).save(doc.storage_key, b"# lost\n\nFound.")
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
