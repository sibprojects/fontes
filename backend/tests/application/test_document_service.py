import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from fontes.application.documents import (
    DocumentNotFoundError,
    DocumentService,
    EmptyFileError,
    FileTooLargeError,
)
from fontes.domain.documents import Document, DocumentStatus, UnsupportedSourceError
from tests.fakes import InMemoryDocumentRepository, InMemoryFileStorage

T0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=1)


@pytest.fixture
def repo() -> InMemoryDocumentRepository:
    return InMemoryDocumentRepository()


@pytest.fixture
def storage() -> InMemoryFileStorage:
    return InMemoryFileStorage()


@pytest.fixture
def svc(repo: InMemoryDocumentRepository, storage: InMemoryFileStorage) -> DocumentService:
    return DocumentService(repo, storage, max_upload_bytes=100, clock=lambda: T0)


async def test_upload_stores_file_and_queues_document(
    svc: DocumentService, repo: InMemoryDocumentRepository, storage: InMemoryFileStorage
) -> None:
    r = await svc.upload("a.pdf", b"%PDF-1")
    assert r.created and r.document.status == DocumentStatus.QUEUED
    assert r.document.storage_key is not None
    assert storage.files[r.document.storage_key] == b"%PDF-1"
    assert await repo.get(r.document.id) == r.document
    assert r.document.content_hash == hashlib.sha256(b"%PDF-1").hexdigest()


async def test_upload_duplicate_returns_existing(
    svc: DocumentService, repo: InMemoryDocumentRepository, storage: InMemoryFileStorage
) -> None:
    first = await svc.upload("a.pdf", b"same")
    second = await svc.upload("b.pdf", b"same")
    assert not second.created and second.document.id == first.document.id
    assert len(storage.files) == 1 and len(await repo.list()) == 1


async def test_upload_rejects_empty(svc: DocumentService) -> None:
    with pytest.raises(EmptyFileError):
        await svc.upload("a.pdf", b"")


async def test_upload_rejects_too_large(svc: DocumentService) -> None:
    await svc.upload("a.pdf", b"x" * 100)  # exactly at the limit is fine
    with pytest.raises(FileTooLargeError):
        await svc.upload("b.pdf", b"y" * 101)


async def test_upload_rejects_unsupported_before_storing(
    svc: DocumentService, storage: InMemoryFileStorage
) -> None:
    with pytest.raises(UnsupportedSourceError):
        await svc.upload("a.docx", b"x")
    assert storage.files == {}


async def test_upload_removes_file_when_row_insert_fails(
    repo: InMemoryDocumentRepository, storage: InMemoryFileStorage
) -> None:
    async def broken_add(doc: Document) -> None:
        raise RuntimeError("db down")

    repo.add = broken_add  # type: ignore[method-assign]
    svc = DocumentService(repo, storage, max_upload_bytes=100, clock=lambda: T0)
    with pytest.raises(RuntimeError, match="db down"):
        await svc.upload("a.pdf", b"x")
    assert storage.files == {}


async def test_add_url_and_duplicate(svc: DocumentService) -> None:
    a = await svc.add_url("https://e.com/x")
    b = await svc.add_url(" https://e.com/x ")
    assert a.created and not b.created and a.document.id == b.document.id


async def test_list_newest_first(
    repo: InMemoryDocumentRepository, storage: InMemoryFileStorage
) -> None:
    times = iter([T0, T1])
    svc = DocumentService(repo, storage, max_upload_bytes=100, clock=lambda: next(times))
    first = await svc.upload("a.pdf", b"1")
    second = await svc.add_url("https://e.com/x")
    assert await svc.list() == [second.document, first.document]


async def test_delete_removes_row_and_file(
    svc: DocumentService, repo: InMemoryDocumentRepository, storage: InMemoryFileStorage
) -> None:
    r = await svc.upload("a.pdf", b"x")
    await svc.delete(r.document.id)
    assert await repo.get(r.document.id) is None and storage.files == {}


async def test_delete_tolerates_missing_file(
    svc: DocumentService, repo: InMemoryDocumentRepository, storage: InMemoryFileStorage
) -> None:
    r = await svc.upload("a.pdf", b"x")
    storage.files.clear()
    await svc.delete(r.document.id)
    assert await repo.get(r.document.id) is None


async def test_delete_url_document_has_no_file(
    svc: DocumentService, repo: InMemoryDocumentRepository
) -> None:
    r = await svc.add_url("https://e.com/x")
    await svc.delete(r.document.id)
    assert await repo.get(r.document.id) is None


async def test_delete_unknown_raises(svc: DocumentService) -> None:
    with pytest.raises(DocumentNotFoundError):
        await svc.delete(uuid4())
