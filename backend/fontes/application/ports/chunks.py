from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from fontes.domain.chunks import Chunk


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
