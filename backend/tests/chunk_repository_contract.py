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
from fontes.domain.documents import Document

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
