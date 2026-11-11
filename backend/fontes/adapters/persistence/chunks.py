import builtins
from collections.abc import Sequence
from uuid import UUID, uuid4

from sqlalchemy import delete, exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import defer

from fontes.adapters.persistence.models import ChunkRow, DocumentRow
from fontes.application.ports.chunks import SearchHit
from fontes.domain.chunks import Chunk
from fontes.domain.documents import DocumentStatus


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

    async def search(self, vector: Sequence[float], limit: int) -> builtins.list[SearchHit]:
        distance = ChunkRow.embedding.cosine_distance(list(vector))
        # Order and limit first, so the HNSW index serves the ordering; count only the top rows.
        top = (
            select(
                ChunkRow.document_id,
                ChunkRow.ordinal,
                ChunkRow.text,
                ChunkRow.page_start,
                ChunkRow.page_end,
                ChunkRow.section,
                distance.label("distance"),
            )
            # EXISTS, not a join: a join makes Postgres sort every chunk instead of walking
            # the HNSW index in distance order.
            .where(
                exists().where(
                    DocumentRow.id == ChunkRow.document_id,
                    DocumentRow.status == DocumentStatus.READY.value,
                )
            )
            .order_by(distance)
            .limit(limit)
            .subquery()
        )
        total = (
            select(func.count()).where(ChunkRow.document_id == top.c.document_id).scalar_subquery()
        )
        query = (
            select(top, DocumentRow.title, DocumentRow.url, total.label("total"))
            .join(DocumentRow, DocumentRow.id == top.c.document_id)
            .order_by(top.c.distance)
        )
        async with self._sessions.begin() as session:
            # The index yields candidates before the filter; without an iterative scan,
            # chunks of documents that are not ready could leave fewer than `limit` hits.
            await session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
            rows = (await session.execute(query)).all()
        return [
            SearchHit(
                document_id=row.document_id,
                document_title=row.title,
                document_url=row.url,
                chunk=Chunk(row.ordinal, row.text, row.page_start, row.page_end, row.section),
                total_chunks=row.total,
                score=1.0 - float(row.distance),
            )
            for row in rows
        ]
