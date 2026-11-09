from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from fontes.api.app import create_app
from fontes.api.limits import MULTIPART_OVERHEAD_BYTES
from fontes.application.documents import DocumentService
from fontes.domain.chunks import Chunk
from tests.fakes import (
    FakePublisher,
    InMemoryChunkRepository,
    InMemoryDocumentRepository,
    InMemoryFileStorage,
)

LIMIT = 100


@pytest.fixture
def storage() -> InMemoryFileStorage:
    return InMemoryFileStorage()


@pytest.fixture
def repo() -> InMemoryDocumentRepository:
    return InMemoryDocumentRepository()


@pytest.fixture
def chunks(repo: InMemoryDocumentRepository) -> InMemoryChunkRepository:
    return InMemoryChunkRepository(repo)


@pytest.fixture
async def c(
    repo: InMemoryDocumentRepository,
    storage: InMemoryFileStorage,
    chunks: InMemoryChunkRepository,
) -> AsyncIterator[AsyncClient]:
    service = DocumentService(repo, storage, chunks, FakePublisher(), max_upload_bytes=LIMIT)
    app = create_app([], health_timeout=1.0, documents=service, max_upload_bytes=LIMIT)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def pdf(data: bytes = b"%PDF-1", name: str = "a.pdf") -> dict[str, tuple[str, bytes, str]]:
    return {"file": (name, data, "application/pdf")}


async def test_upload_returns_201_and_lists(c: AsyncClient) -> None:
    r = await c.post("/documents", files=pdf())
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "queued"
    assert (body["title"], body["source_type"], body["attempts"]) == ("a.pdf", "pdf", 0)
    assert set(body) == {
        "id",
        "title",
        "source_type",
        "status",
        "url",
        "error",
        "attempts",
        "created_at",
    }
    listed = await c.get("/documents")
    assert listed.status_code == 200
    assert listed.json() == [body]


async def test_upload_duplicate_returns_200(c: AsyncClient) -> None:
    first = await c.post("/documents", files=pdf())
    second = await c.post("/documents", files=pdf(name="b.pdf"))
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["id"] == first.json()["id"]


async def test_upload_empty_returns_400(c: AsyncClient) -> None:
    r = await c.post("/documents", files=pdf(b""))
    assert r.status_code == 400
    assert isinstance(r.json()["detail"], str)


async def test_upload_too_large_returns_413(c: AsyncClient, storage: InMemoryFileStorage) -> None:
    assert (await c.post("/documents", files=pdf(b"x" * LIMIT))).status_code == 201
    r = await c.post("/documents", files=pdf(b"y" * (LIMIT + 1), name="b.pdf"))
    assert r.status_code == 413
    assert isinstance(r.json()["detail"], str)
    assert len(storage.files) == 1


async def test_upload_unsupported_returns_415(c: AsyncClient) -> None:
    r = await c.post("/documents", files=pdf(name="a.docx"))
    assert r.status_code == 415
    assert ".pdf" in r.json()["detail"]


async def test_upload_without_file_returns_422(c: AsyncClient) -> None:
    r = await c.post("/documents", data={"x": "y"})
    assert r.status_code == 422


async def test_upload_with_path_in_filename_is_stored_safely(
    c: AsyncClient, storage: InMemoryFileStorage
) -> None:
    r = await c.post("/documents", files={"file": ("../../evil.pdf", b"x", "application/pdf")})
    assert r.status_code == 201 and r.json()["title"] == "evil.pdf"
    assert list(storage.files) == [f"{r.json()['id']}.pdf"]


async def test_add_url_201_then_200(c: AsyncClient) -> None:
    first = await c.post("/documents/url", json={"url": "https://e.com/x"})
    second = await c.post("/documents/url", json={"url": " https://e.com/x "})
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert (first.json()["source_type"], first.json()["url"]) == ("url", "https://e.com/x")


async def test_add_url_invalid_returns_422(c: AsyncClient) -> None:
    r = await c.post("/documents/url", json={"url": "ftp://x"})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)


async def test_delete_204_then_404(c: AsyncClient) -> None:
    doc_id = (await c.post("/documents", files=pdf())).json()["id"]
    r = await c.delete(f"/documents/{doc_id}")
    assert r.status_code == 204 and r.content == b""
    again = await c.delete(f"/documents/{doc_id}")
    assert again.status_code == 404
    assert isinstance(again.json()["detail"], str)
    assert (await c.get("/documents")).json() == []


async def test_delete_unknown_returns_404(c: AsyncClient) -> None:
    assert (await c.delete(f"/documents/{uuid4()}")).status_code == 404


async def test_oversized_content_length_is_rejected_before_reading(
    c: AsyncClient, storage: InMemoryFileStorage
) -> None:
    body = b"x" * (LIMIT + MULTIPART_OVERHEAD_BYTES + 1)
    r = await c.post(
        "/documents",
        content=body,
        headers={"content-type": "multipart/form-data; boundary=b"},
    )
    assert r.status_code == 413
    assert isinstance(r.json()["detail"], str)
    assert storage.files == {}


async def test_oversized_chunked_body_is_rejected(
    c: AsyncClient, storage: InMemoryFileStorage
) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        # A well-formed file part whose data never ends within the limit.
        yield (
            b"--b\r\n"
            b'Content-Disposition: form-data; name="file"; filename="a.pdf"\r\n'
            b"Content-Type: application/pdf\r\n\r\n"
        )
        for _ in range(100):
            yield b"x" * 1024 * 1024

    r = await c.post(
        "/documents",
        content=chunks(),
        headers={"content-type": "multipart/form-data; boundary=b"},
    )
    assert r.status_code == 413
    assert storage.files == {}


async def test_list_chunks_returns_locations(
    c: AsyncClient, chunks: InMemoryChunkRepository
) -> None:
    doc_id = (await c.post("/documents", files=pdf(b"# A", name="a.md"))).json()["id"]
    stored = [
        Chunk(0, "alpha", section="A"),
        Chunk(1, "beta", page_start=2, page_end=3),
        Chunk(2, "gamma"),
    ]
    await chunks.replace(UUID(doc_id), stored, [[0.0]] * 3)
    r = await c.get(f"/documents/{doc_id}/chunks")
    assert r.status_code == 200
    assert r.json() == [
        {"ordinal": 0, "location": "A", "text": "alpha"},
        {"ordinal": 1, "location": "pp. 2\u20133", "text": "beta"},
        {"ordinal": 2, "location": "part 3 of 3", "text": "gamma"},
    ]


async def test_list_chunks_of_unprocessed_document_is_empty(c: AsyncClient) -> None:
    doc_id = (await c.post("/documents", files=pdf())).json()["id"]
    r = await c.get(f"/documents/{doc_id}/chunks")
    assert (r.status_code, r.json()) == (200, [])


async def test_list_chunks_unknown_document_404(c: AsyncClient) -> None:
    r = await c.get(f"/documents/{uuid4()}/chunks")
    assert r.status_code == 404
    assert isinstance(r.json()["detail"], str)
