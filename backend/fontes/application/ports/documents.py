from typing import Protocol
from uuid import UUID

from fontes.domain.documents import Document


class DocumentRepository(Protocol):
    async def add(self, doc: Document) -> None: ...

    async def get(self, id: UUID) -> Document | None: ...

    async def find_by_hash(self, content_hash: str) -> Document | None: ...

    async def find_by_url(self, url: str) -> Document | None: ...

    async def list(self) -> list[Document]:
        """All documents, newest first."""
        ...

    async def delete(self, id: UUID) -> bool:
        """Return False if there was no such document."""
        ...


class FileStorage(Protocol):
    async def save(self, key: str, data: bytes) -> None: ...

    async def delete(self, key: str) -> None:
        """Remove the file; a missing key is not an error."""
        ...
