import builtins
from dataclasses import replace
from uuid import UUID

from fontes.application.ports.documents import DuplicateDocumentError
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
        if doc is None or doc.status == DocumentStatus.READY:
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


class InMemoryFileStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def save(self, key: str, data: bytes) -> None:
        self.files[key] = data

    async def delete(self, key: str) -> None:
        self.files.pop(key, None)
