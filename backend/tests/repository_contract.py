"""Status-transition cases every DocumentRepository must pass.

Imported by tests/test_fakes.py (in-memory fake) and by the integration tests (Postgres);
each module provides its own `repo` fixture.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fontes.application.ports.documents import DocumentRepository
from fontes.domain.documents import Document, DocumentStatus

T0 = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


async def _queued(repo: DocumentRepository, name: str = "a.pdf", at: datetime = T0) -> Document:
    doc = Document.from_upload(name, f"hash-{name}", now=at)
    await repo.add(doc)
    return doc


async def test_start_processing_increments_attempts(repo: DocumentRepository) -> None:
    d = await _queued(repo)
    await repo.set_status(d.id, DocumentStatus.QUEUED, "previous error")
    got = await repo.start_processing(d.id)
    assert got is not None
    assert (got.status, got.attempts, got.error) == (DocumentStatus.PROCESSING, 1, None)
    again = await repo.start_processing(d.id)
    assert again is not None and again.attempts == 2
    assert await repo.get(d.id) == again


async def test_start_processing_skips_ready(repo: DocumentRepository) -> None:
    d = await _queued(repo)
    assert await repo.set_status(d.id, DocumentStatus.READY) is True
    assert await repo.start_processing(d.id) is None
    got = await repo.get(d.id)
    assert got is not None and (got.status, got.attempts) == (DocumentStatus.READY, 0)


async def test_start_processing_missing_returns_none(repo: DocumentRepository) -> None:
    assert await repo.start_processing(uuid4()) is None


async def test_set_status_with_error(repo: DocumentRepository) -> None:
    d = await _queued(repo)
    assert await repo.set_status(d.id, DocumentStatus.FAILED, "boom") is True
    got = await repo.get(d.id)
    assert got is not None and (got.status, got.error) == (DocumentStatus.FAILED, "boom")


async def test_set_status_clears_error(repo: DocumentRepository) -> None:
    d = await _queued(repo)
    await repo.set_status(d.id, DocumentStatus.QUEUED, "boom")
    await repo.set_status(d.id, DocumentStatus.READY)
    got = await repo.get(d.id)
    assert got is not None and got.error is None


async def test_set_status_missing_returns_false(repo: DocumentRepository) -> None:
    assert await repo.set_status(uuid4(), DocumentStatus.READY) is False
    assert await repo.list() == []


async def test_list_by_status_oldest_first(repo: DocumentRepository) -> None:
    newer = await _queued(repo, "b.pdf", T0 + timedelta(minutes=1))
    older = await _queued(repo, "a.pdf", T0)
    ready = await _queued(repo, "c.pdf", T0 - timedelta(minutes=1))
    await repo.set_status(ready.id, DocumentStatus.READY)
    queued = await repo.list_by_status(DocumentStatus.QUEUED)
    assert [d.id for d in queued] == [older.id, newer.id]
    assert [d.id for d in await repo.list_by_status(DocumentStatus.READY)] == [ready.id]


async def test_start_processing_skips_failed(repo: DocumentRepository) -> None:
    # A stale duplicate message must not bring a dead-lettered document back to life.
    d = await _queued(repo)
    await repo.set_status(d.id, DocumentStatus.FAILED, "corrupt PDF")
    assert await repo.start_processing(d.id) is None
    got = await repo.get(d.id)
    assert got is not None and (got.status, got.error) == (DocumentStatus.FAILED, "corrupt PDF")
