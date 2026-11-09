import asyncio
from collections.abc import Mapping

from fontes.application.chunking import Chunker
from fontes.application.ports.chunks import ChunkRepository
from fontes.application.ports.embeddings import Embedder
from fontes.application.ports.ingestion import PermanentIngestionError
from fontes.application.ports.loading import DocumentLoader
from fontes.domain.documents import Document, SourceType


class IngestionPipeline:
    """The DocumentProcessor for real documents: load, chunk, embed, store."""

    def __init__(
        self,
        loaders: Mapping[SourceType, DocumentLoader],
        chunker: Chunker,
        embedder: Embedder,
        chunks: ChunkRepository,
    ) -> None:
        self._loaders = loaders
        self._chunker = chunker
        self._embedder = embedder
        self._chunks = chunks

    async def process(self, doc: Document) -> None:
        loader = self._loaders.get(doc.source_type)
        if loader is None:
            raise PermanentIngestionError(f"No loader for {doc.source_type}")
        segments = await loader.load(doc)
        chunks = await asyncio.to_thread(self._chunker.split, segments)
        if not chunks:
            raise PermanentIngestionError(
                "No text could be extracted (scanned PDFs are not supported)"
            )
        embeddings = await self._embedder.embed([c.text for c in chunks])
        # False means the document was deleted while we worked: nothing to keep.
        await self._chunks.replace(doc.id, chunks, embeddings)
