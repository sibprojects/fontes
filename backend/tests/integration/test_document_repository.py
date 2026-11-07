from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from fontes.adapters.persistence.documents import SqlDocumentRepository
from fontes.application.ports.documents import DuplicateDocumentError
from fontes.domain.documents import Document
from tests.repository_contract import (  # noqa: F401
    test_list_by_status_oldest_first,
    test_set_status_clears_error,
    test_set_status_missing_returns_false,
    test_set_status_with_error,
    test_start_processing_increments_attempts,
    test_start_processing_skips_failed,
    test_start_processing_missing_returns_none,
    test_start_processing_skips_ready,
)

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=1)


async def test_add_and_get_roundtrip(repo: SqlDocumentRepository) -> None:
    d = Document.from_upload("a.pdf", "h1", now=T0)
    await repo.add(d)
    assert await repo.get(d.id) == d


async def test_url_document_roundtrip(repo: SqlDocumentRepository) -> None:
    d = Document.from_url("https://e.com/x", now=T0)
    await repo.add(d)
    assert await repo.get(d.id) == d


async def test_get_unknown_returns_none(repo: SqlDocumentRepository) -> None:
    assert await repo.get(uuid4()) is None


async def test_find_by_hash_and_url(repo: SqlDocumentRepository) -> None:
    f = Document.from_upload("a.pdf", "h1", now=T0)
    u = Document.from_url("https://e.com/x", now=T0)
    await repo.add(f)
    await repo.add(u)
    assert await repo.find_by_hash("h1") == f
    assert await repo.find_by_hash("nope") is None
    assert await repo.find_by_url("https://e.com/x") == u
    assert await repo.find_by_url("https://e.com/y") is None


async def test_list_newest_first(repo: SqlDocumentRepository) -> None:
    first = Document.from_upload("a.pdf", "h1", now=T0)
    second = Document.from_upload("b.pdf", "h2", now=T1)
    await repo.add(first)
    await repo.add(second)
    assert await repo.list() == [second, first]


async def test_delete(repo: SqlDocumentRepository) -> None:
    d = Document.from_upload("a.pdf", "h1", now=T0)
    await repo.add(d)
    assert await repo.delete(d.id) is True
    assert await repo.get(d.id) is None


async def test_delete_returns_false_for_unknown(repo: SqlDocumentRepository) -> None:
    assert await repo.delete(uuid4()) is False


async def test_duplicate_hash_violates_unique_index(repo: SqlDocumentRepository) -> None:
    await repo.add(Document.from_upload("a.pdf", "same", now=T0))
    with pytest.raises(DuplicateDocumentError):
        await repo.add(Document.from_upload("b.pdf", "same", now=T0))


async def test_duplicate_url_violates_unique_index(repo: SqlDocumentRepository) -> None:
    await repo.add(Document.from_url("https://e.com/x", now=T0))
    with pytest.raises(DuplicateDocumentError):
        await repo.add(Document.from_url("https://e.com/x", now=T0))


async def test_created_at_is_timezone_aware(repo: SqlDocumentRepository) -> None:
    d = Document.from_upload("a.pdf", "h1", now=T0)
    await repo.add(d)
    got = await repo.get(d.id)
    assert got is not None and got.created_at.tzinfo is not None
