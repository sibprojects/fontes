from uuid import UUID

from fontes.domain.documents import Document


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, Document] = {}

    async def add(self, doc: Document) -> None:
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


class InMemoryFileStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def save(self, key: str, data: bytes) -> None:
        self.files[key] = data

    async def delete(self, key: str) -> None:
        self.files.pop(key, None)
