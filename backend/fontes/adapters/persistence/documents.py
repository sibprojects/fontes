import builtins
from uuid import UUID

from sqlalchemy import ColumnElement, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fontes.adapters.persistence.models import DocumentRow
from fontes.application.ports.documents import DuplicateDocumentError
from fontes.domain.documents import Document, DocumentStatus, SourceType

_UNIQUE_VIOLATION = "23505"


def _to_row(doc: Document) -> DocumentRow:
    return DocumentRow(
        id=doc.id,
        title=doc.title,
        source_type=doc.source_type.value,
        status=doc.status.value,
        storage_key=doc.storage_key,
        content_hash=doc.content_hash,
        url=doc.url,
        error=doc.error,
        attempts=doc.attempts,
        created_at=doc.created_at,
    )


def _to_domain(row: DocumentRow) -> Document:
    return Document(
        id=row.id,
        title=row.title,
        source_type=SourceType(row.source_type),
        status=DocumentStatus(row.status),
        created_at=row.created_at,
        storage_key=row.storage_key,
        content_hash=row.content_hash,
        url=row.url,
        error=row.error,
        attempts=row.attempts,
    )


class SqlDocumentRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def add(self, doc: Document) -> None:
        try:
            async with self._sessions.begin() as session:
                session.add(_to_row(doc))
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == _UNIQUE_VIOLATION:
                raise DuplicateDocumentError(doc.content_hash or doc.url or str(doc.id)) from exc
            raise

    async def get(self, id: UUID) -> Document | None:
        async with self._sessions() as session:
            row = await session.get(DocumentRow, id)
            return _to_domain(row) if row else None

    async def find_by_hash(self, content_hash: str) -> Document | None:
        return await self._first(DocumentRow.content_hash == content_hash)

    async def find_by_url(self, url: str) -> Document | None:
        return await self._first(DocumentRow.url == url)

    async def list(self) -> list[Document]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(DocumentRow).order_by(DocumentRow.created_at.desc(), DocumentRow.id)
            )
            return [_to_domain(r) for r in rows]

    async def delete(self, id: UUID) -> bool:
        async with self._sessions.begin() as session:
            result = await session.execute(
                delete(DocumentRow).where(DocumentRow.id == id).returning(DocumentRow.id)
            )
            return result.first() is not None

    async def start_processing(self, id: UUID) -> Document | None:
        async with self._sessions.begin() as session:
            row = await session.scalar(
                update(DocumentRow)
                .where(DocumentRow.id == id, DocumentRow.status != DocumentStatus.READY.value)
                .values(
                    status=DocumentStatus.PROCESSING.value,
                    attempts=DocumentRow.attempts + 1,
                    error=None,
                )
                .returning(DocumentRow)
            )
            return _to_domain(row) if row else None

    async def set_status(self, id: UUID, status: DocumentStatus, error: str | None = None) -> bool:
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(DocumentRow)
                .where(DocumentRow.id == id)
                .values(status=status.value, error=error)
                .returning(DocumentRow.id)
            )
            return result.first() is not None

    async def list_by_status(self, status: DocumentStatus) -> builtins.list[Document]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(DocumentRow)
                .where(DocumentRow.status == status.value)
                .order_by(DocumentRow.created_at, DocumentRow.id)
            )
            return [_to_domain(r) for r in rows]

    async def _first(self, condition: ColumnElement[bool]) -> Document | None:
        async with self._sessions() as session:
            row = await session.scalar(select(DocumentRow).where(condition).limit(1))
            return _to_domain(row) if row else None
