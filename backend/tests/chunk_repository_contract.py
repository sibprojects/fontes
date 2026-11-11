"""Cases every ChunkRepository must pass.

Imported by tests/test_fakes.py (in-memory fake) and by the integration tests (Postgres);
each module provides its own `chunks` and `docs` fixtures.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from fontes.application.ports.chunks import ChunkRepository
from fontes.application.ports.documents import DocumentRepository
from fontes.domain.chunks import Chunk
from fontes.domain.documents import Document, DocumentStatus

T0 = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


async def _document(docs: DocumentRepository) -> UUID:
    doc = Document.from_upload("a.pdf", f"hash-{uuid4()}", now=T0)
    await docs.add(doc)
    return doc.id


def _vectors(n: int) -> list[list[float]]:
    return [[float(i)] * 1024 for i in range(n)]


async def test_replace_then_list_in_order(
    chunks: ChunkRepository, docs: DocumentRepository
) -> None:
    doc_id = await _document(docs)
    written = [
        Chunk(0, "first", 1, 1),
        Chunk(1, "second", 1, 2, "Intro"),
        Chunk(2, "third"),
    ]
    assert await chunks.replace(doc_id, written, _vectors(3)) is True
    got = await chunks.list_for_document(doc_id)
    assert got == written
    assert [c.ordinal for c in got] == [0, 1, 2]


async def test_replace_twice_leaves_only_second(
    chunks: ChunkRepository, docs: DocumentRepository
) -> None:
    doc_id = await _document(docs)
    await chunks.replace(doc_id, [Chunk(i, f"old {i}") for i in range(3)], _vectors(3))
    second = [Chunk(0, "new 0"), Chunk(1, "new 1")]
    assert await chunks.replace(doc_id, second, _vectors(2)) is True
    assert await chunks.list_for_document(doc_id) == second


async def test_replace_for_missing_document_writes_nothing(chunks: ChunkRepository) -> None:
    missing = uuid4()
    assert await chunks.replace(missing, [Chunk(0, "orphan")], _vectors(1)) is False
    assert await chunks.list_for_document(missing) == []


async def test_replace_with_mismatched_embeddings_raises(
    chunks: ChunkRepository, docs: DocumentRepository
) -> None:
    doc_id = await _document(docs)
    with pytest.raises(ValueError):
        await chunks.replace(doc_id, [Chunk(0, "a"), Chunk(1, "b")], _vectors(1))


async def test_text_with_unusual_characters_round_trips(
    chunks: ChunkRepository, docs: DocumentRepository
) -> None:
    doc_id = await _document(docs)
    text = "Глава 1 — «цитата» ✓ \t tab"
    await chunks.replace(doc_id, [Chunk(0, text, section="Раздел")], _vectors(1))
    assert await chunks.list_for_document(doc_id) == [Chunk(0, text, section="Раздел")]


def _axis(*weights: tuple[int, float]) -> list[float]:
    vector = [0.0] * 1024
    for index, weight in weights:
        vector[index] = weight
    return vector


async def _ready(docs: DocumentRepository, doc: Document | None = None) -> Document:
    doc = doc or Document.from_upload("a.pdf", f"hash-{uuid4()}", now=T0)
    await docs.add(doc)
    await docs.set_status(doc.id, DocumentStatus.READY)
    return doc


async def test_search_orders_by_similarity(
    chunks: ChunkRepository, docs: DocumentRepository
) -> None:
    doc = await _ready(docs)
    await chunks.replace(
        doc.id,
        [Chunk(0, "axis0"), Chunk(1, "axis1"), Chunk(2, "mixed")],
        [_axis((0, 1.0)), _axis((1, 1.0)), _axis((0, 0.7), (1, 0.7))],
    )
    hits = await chunks.search(_axis((0, 1.0)), limit=2)
    assert [h.chunk.text for h in hits] == ["axis0", "mixed"]
    assert [h.score for h in hits] == pytest.approx([1.0, 0.7071], abs=1e-3)


async def test_search_skips_documents_not_ready(
    chunks: ChunkRepository, docs: DocumentRepository
) -> None:
    doc = await _document(docs)  # stays queued
    await chunks.replace(doc, [Chunk(0, "match")], [_axis((0, 1.0))])
    assert await chunks.search(_axis((0, 1.0)), limit=5) == []


async def test_search_respects_limit(chunks: ChunkRepository, docs: DocumentRepository) -> None:
    doc = await _ready(docs)
    await chunks.replace(
        doc.id,
        [Chunk(i, f"c{i}") for i in range(5)],
        [_axis((i, 1.0), (10, 0.5)) for i in range(5)],
    )
    assert len(await chunks.search(_axis((10, 1.0)), limit=3)) == 3


async def test_search_hit_carries_citation_fields(
    chunks: ChunkRepository, docs: DocumentRepository
) -> None:
    doc = await _ready(docs, Document.from_url(f"https://x.test/{uuid4()}", now=T0))
    stored = [Chunk(0, "a", section="Intro"), Chunk(1, "b"), Chunk(2, "c")]
    await chunks.replace(doc.id, stored, [_axis((0, 1.0)), _axis((1, 1.0)), _axis((2, 1.0))])
    (hit,) = await chunks.search(_axis((0, 1.0)), limit=1)
    assert hit.document_id == doc.id
    assert hit.document_title == doc.title
    assert hit.document_url == doc.url
    assert hit.total_chunks == 3
    assert hit.chunk == stored[0]


async def test_search_across_documents(chunks: ChunkRepository, docs: DocumentRepository) -> None:
    first, second = await _ready(docs), await _ready(docs)
    await chunks.replace(first.id, [Chunk(0, "first")], [_axis((0, 0.6), (1, 0.8))])
    await chunks.replace(second.id, [Chunk(0, "second")], [_axis((0, 1.0))])
    hits = await chunks.search(_axis((0, 1.0)), limit=5)
    assert [(h.document_id, h.chunk.text) for h in hits] == [
        (second.id, "second"),
        (first.id, "first"),
    ]
