from datetime import UTC, datetime

import pytest

from fontes.application.chunking import Chunker
from fontes.application.pipeline import IngestionPipeline
from fontes.application.ports.ingestion import PermanentIngestionError
from fontes.domain.chunks import Segment
from fontes.domain.documents import Document, SourceType
from tests.fakes import (
    FakeEmbedder,
    FakeLoader,
    InMemoryChunkRepository,
    InMemoryDocumentRepository,
)

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
TWO_SECTIONS = [Segment("A\n" + "a " * 200, section="A"), Segment("B\n" + "b " * 200, section="B")]


class Setup:
    def __init__(
        self,
        loader: FakeLoader | None = None,
        embedder: FakeEmbedder | None = None,
        with_loader: bool = True,
    ) -> None:
        self.docs = InMemoryDocumentRepository()
        self.chunks = InMemoryChunkRepository(self.docs)
        self.loader = loader or FakeLoader(TWO_SECTIONS)
        self.embedder = embedder or FakeEmbedder(dimension=8)
        loaders = {SourceType.MARKDOWN: self.loader} if with_loader else {}
        self.pipeline = IngestionPipeline(
            loaders, Chunker(1500, 200, 300), self.embedder, self.chunks
        )

    async def document(self) -> Document:
        doc = Document.from_upload("notes.md", "hash", now=NOW)
        await self.docs.add(doc)
        return doc


async def test_document_ends_up_as_embedded_chunks() -> None:
    s = Setup()
    doc = await s.document()
    await s.pipeline.process(doc)
    stored = await s.chunks.list_for_document(doc.id)
    assert [c.section for c in stored] == ["A", "B"]
    assert [len(v) for v in s.chunks.embeddings[doc.id]] == [8, 8]
    assert s.embedder.calls == [[c.text for c in stored]]


async def test_no_text_is_permanent() -> None:
    s = Setup(loader=FakeLoader([]))
    with pytest.raises(PermanentIngestionError, match="No text could be extracted"):
        await s.pipeline.process(await s.document())
    assert s.embedder.calls == []


async def test_blank_text_is_permanent() -> None:
    s = Setup(loader=FakeLoader([Segment("  \n\x00 ", page=1)]))
    with pytest.raises(PermanentIngestionError, match="No text could be extracted"):
        await s.pipeline.process(await s.document())


async def test_rerun_replaces_chunks() -> None:
    s = Setup()
    doc = await s.document()
    await s.pipeline.process(doc)
    await s.pipeline.process(doc)
    assert len(await s.chunks.list_for_document(doc.id)) == 2


async def test_deleted_document_discards_results() -> None:
    s = Setup()
    doc = Document.from_upload("notes.md", "hash", now=NOW)  # never added
    await s.pipeline.process(doc)
    assert s.chunks.rows == {}


async def test_embedder_failure_propagates_and_stores_nothing() -> None:
    s = Setup(embedder=FakeEmbedder(fail=ConnectionError("down")))
    doc = await s.document()
    with pytest.raises(ConnectionError):
        await s.pipeline.process(doc)
    assert await s.chunks.list_for_document(doc.id) == []


async def test_unknown_source_type_is_permanent() -> None:
    s = Setup(with_loader=False)
    with pytest.raises(PermanentIngestionError, match="No loader for markdown"):
        await s.pipeline.process(await s.document())


async def test_loader_permanent_error_passes_through() -> None:
    error = PermanentIngestionError("corrupt")
    s = Setup(loader=FakeLoader(error))
    with pytest.raises(PermanentIngestionError) as info:
        await s.pipeline.process(await s.document())
    assert info.value is error


async def test_no_text_message_mentions_scanned_pdfs_only_for_pdfs() -> None:
    s = Setup(loader=FakeLoader([]))
    with pytest.raises(PermanentIngestionError) as info:
        await s.pipeline.process(await s.document())
    assert "scanned" not in str(info.value)

    pdf = Document.from_upload("scan.pdf", "hash-scan", now=NOW)
    await s.docs.add(pdf)
    pipeline = IngestionPipeline(
        {SourceType.PDF: FakeLoader([])}, Chunker(1500, 200, 300), s.embedder, s.chunks
    )
    with pytest.raises(PermanentIngestionError, match="scanned PDFs are not supported"):
        await pipeline.process(pdf)
