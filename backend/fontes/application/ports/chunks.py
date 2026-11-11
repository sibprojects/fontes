from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fontes.domain.chunks import Chunk


@dataclass(frozen=True)
class SearchHit:
    """A retrieved chunk with what a citation needs from its document."""

    document_id: UUID
    document_title: str
    document_url: str | None
    chunk: Chunk
    total_chunks: int  # for "part 3 of 12"
    score: float  # cosine similarity, 1.0 = same direction


class ChunkRepository(Protocol):
    async def replace(
        self,
        document_id: UUID,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> bool:
        """Atomically swap the document's chunks for these; return False if it is missing.

        Raise ValueError if chunks and embeddings differ in length.
        """
        ...

    async def list_for_document(self, document_id: UUID) -> list[Chunk]:
        """The document's chunks, by ordinal."""
        ...

    async def search(self, vector: Sequence[float], limit: int) -> list[SearchHit]:
        """The `limit` chunks of ready documents closest to `vector`, most similar first."""
        ...
