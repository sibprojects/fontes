import builtins
from collections.abc import Sequence
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import defer

from fontes.adapters.persistence.models import ChunkRow, DocumentRow
from fontes.domain.chunks import Chunk


def _to_domain(row: ChunkRow) -> Chunk:
    return Chunk(
        ordinal=row.ordinal,
        text=row.text,
        page_start=row.page_start,
        page_end=row.page_end,
        section=row.section,
    )


class SqlChunkRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def replace(
        self,
        document_id: UUID,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> bool:
        if len(chunks) != len(embeddings):
            raise ValueError(f"{len(chunks)} chunks but {len(embeddings)} embeddings")
        async with self._sessions.begin() as session:
            # The row lock serializes concurrent runs for one document and blocks a delete
            # until we commit; a document deleted first is simply gone.
            locked = await session.scalar(
                select(DocumentRow.id).where(DocumentRow.id == document_id).with_for_update()
            )
            if locked is None:
                return False
            await session.execute(delete(ChunkRow).where(ChunkRow.document_id == document_id))
            session.add_all(
                ChunkRow(
                    id=uuid4(),
                    document_id=document_id,
                    ordinal=chunk.ordinal,
                    text=chunk.text,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    section=chunk.section,
                    embedding=list(vector),
                )
                for chunk, vector in zip(chunks, embeddings, strict=True)
            )
            return True

    async def list_for_document(self, document_id: UUID) -> builtins.list[Chunk]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(ChunkRow)
                .options(defer(ChunkRow.embedding))
                .where(ChunkRow.document_id == document_id)
                .order_by(ChunkRow.ordinal)
            )
            return [_to_domain(r) for r in rows]
