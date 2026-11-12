import builtins
import hashlib
import math
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import replace
from uuid import UUID

from fontes.application.ports.chunks import SearchHit
from fontes.application.ports.documents import DuplicateDocumentError
from fontes.domain.answers import Answer
from fontes.domain.chunks import Chunk, Segment
from fontes.domain.documents import Document, DocumentStatus


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, Document] = {}

    async def add(self, doc: Document) -> None:
        # Mirrors the unique indexes on content_hash and url.
        for d in self.rows.values():
            if (doc.content_hash and d.content_hash == doc.content_hash) or (
                doc.url and d.url == doc.url
            ):
                raise DuplicateDocumentError(doc.content_hash or doc.url or "")
        self.rows[doc.id] = doc

    async def get(self, id: UUID) -> Document | None:
        return self.rows.get(id)

    async def find_by_hash(self, content_hash: str) -> Document | None:
        return next((d for d in self.rows.values() if d.content_hash == content_hash), None)

    async def find_by_url(self, url: str) -> Document | None:
        return next((d for d in self.rows.values() if d.url == url), None)

    async def list(self) -> list[Document]:
        return sorted(self.rows.values(), key=lambda d: d.created_at, reverse=True)

    async def delete(self, id: UUID) -> bool:
        return self.rows.pop(id, None) is not None

    async def start_processing(self, id: UUID) -> Document | None:
        doc = self.rows.get(id)
        if doc is None or doc.status not in (DocumentStatus.QUEUED, DocumentStatus.PROCESSING):
            return None
        doc = replace(doc, status=DocumentStatus.PROCESSING, attempts=doc.attempts + 1, error=None)
        self.rows[id] = doc
        return doc

    async def set_status(self, id: UUID, status: DocumentStatus, error: str | None = None) -> bool:
        doc = self.rows.get(id)
        if doc is None:
            return False
        self.rows[id] = replace(doc, status=status, error=error)
        return True

    async def list_by_status(self, status: DocumentStatus) -> builtins.list[Document]:
        return sorted(
            (d for d in self.rows.values() if d.status == status), key=lambda d: d.created_at
        )


class InMemoryChunkRepository:
    def __init__(self, documents: InMemoryDocumentRepository) -> None:
        self._documents = documents
        self.rows: dict[UUID, list[Chunk]] = {}
        self.embeddings: dict[UUID, list[list[float]]] = {}

    async def replace(
        self,
        document_id: UUID,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> bool:
        if len(chunks) != len(embeddings):
            raise ValueError(f"{len(chunks)} chunks but {len(embeddings)} embeddings")
        if document_id not in self._documents.rows:
            return False
        self.rows[document_id] = list(chunks)
        self.embeddings[document_id] = [list(v) for v in embeddings]
        return True

    async def list_for_document(self, document_id: UUID) -> builtins.list[Chunk]:
        if document_id not in self._documents.rows:  # mirrors the cascade delete
            return []
        return sorted(self.rows.get(document_id, []), key=lambda c: c.ordinal)

    async def search(self, vector: Sequence[float], limit: int) -> builtins.list[SearchHit]:
        hits = [
            SearchHit(doc.id, doc.title, doc.url, chunk, len(chunks), _cosine(vector, embedding))
            for doc_id, chunks in self.rows.items()
            if (doc := self._documents.rows.get(doc_id)) and doc.status == DocumentStatus.READY
            for chunk, embedding in zip(chunks, self.embeddings[doc_id], strict=True)
        ]
        return sorted(hits, key=lambda h: h.score, reverse=True)[:limit]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


class InMemoryQuestionRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, Answer] = {}

    async def add(self, answer: Answer) -> None:
        self.rows[answer.id] = answer

    async def get(self, id: UUID) -> Answer | None:
        return self.rows.get(id)

    async def list(self, limit: int) -> builtins.list[Answer]:
        newest = sorted(self.rows.values(), key=lambda a: a.created_at, reverse=True)
        return newest[:limit]


class InMemoryFileStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def save(self, key: str, data: bytes) -> None:
        self.files[key] = data

    async def read(self, key: str) -> bytes:
        try:
            return self.files[key]
        except KeyError:
            raise FileNotFoundError(key) from None

    async def delete(self, key: str) -> None:
        self.files.pop(key, None)


class FakePublisher:
    def __init__(self, fail: bool = False) -> None:
        self.published: list[UUID] = []
        self.fail = fail

    async def publish_ingest(self, document_id: UUID) -> None:
        if self.fail:
            raise ConnectionError("broker down")
        self.published.append(document_id)


class FakeProcessor:
    """Raises the queued exceptions one per call; succeeds once the queue is empty."""

    def __init__(
        self,
        errors: list[Exception] | None = None,
        on_process: Callable[[Document], Awaitable[None]] | None = None,
    ) -> None:
        self.errors = list(errors or [])
        self.on_process = on_process
        self.calls = 0

    async def process(self, doc: Document) -> None:
        self.calls += 1
        if self.on_process is not None:
            await self.on_process(doc)
        if self.errors:
            raise self.errors.pop(0)


class FakeEmbedder:
    """Deterministic vectors derived from a hash of each text."""

    def __init__(self, dimension: int = 1024, fail: Exception | None = None) -> None:
        self.dimension = dimension
        self.fail = fail
        self.calls: list[list[str]] = []

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.fail is not None:
            raise self.fail
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        return [digest[i % len(digest)] / 255 for i in range(self.dimension)]


class FakeLoader:
    """Returns the given segments, or raises the given exception."""

    def __init__(self, segments: builtins.list[Segment] | Exception) -> None:
        self.segments = segments
        self.calls = 0

    async def load(self, doc: Document) -> builtins.list[Segment]:
        self.calls += 1
        if isinstance(self.segments, Exception):
            raise self.segments
        return list(self.segments)


class FakeLLM:
    """Streams the given pieces; with `fail`, raises it after `fail_after` pieces."""

    provider = "fake"
    model = "fake-1"

    def __init__(
        self,
        chunks: builtins.list[str] | None = None,
        fail: Exception | None = None,
        fail_after: int = 0,
    ) -> None:
        self.chunks = list(chunks or [])
        self.fail = fail
        self.fail_after = fail_after
        self.calls: builtins.list[tuple[str, str]] = []

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        self.calls.append((system, user))
        pieces = self.chunks[: self.fail_after] if self.fail is not None else self.chunks
        for piece in pieces:
            yield piece
        if self.fail is not None:
            raise self.fail
