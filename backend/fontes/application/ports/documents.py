import builtins
from typing import Protocol
from uuid import UUID

from fontes.domain.documents import Document, DocumentStatus


class DuplicateDocumentError(Exception):
    """`add` hit an existing document with the same content hash or URL."""


class DocumentRepository(Protocol):
    async def add(self, doc: Document) -> None:
        """Raise DuplicateDocumentError if the content hash or URL is already stored."""
        ...

    async def get(self, id: UUID) -> Document | None: ...

    async def find_by_hash(self, content_hash: str) -> Document | None: ...

    async def find_by_url(self, url: str) -> Document | None: ...

    async def list(self) -> list[Document]:
        """All documents, newest first."""
        ...

    async def delete(self, id: UUID) -> bool:
        """Return False if there was no such document."""
        ...

    async def start_processing(self, id: UUID) -> Document | None:
        """Atomically mark the document processing, count the attempt and clear the error.

        Return the updated document, or None if it is missing, ready or failed.
        """
        ...

    async def set_status(self, id: UUID, status: DocumentStatus, error: str | None = None) -> bool:
        """Set status and error; return False if the document is missing. Never inserts."""
        ...

    async def list_by_status(self, status: DocumentStatus) -> builtins.list[Document]:
        """Documents with this status, oldest first."""
        ...


class FileStorage(Protocol):
    async def save(self, key: str, data: bytes) -> None: ...

    async def read(self, key: str) -> bytes:
        """Raise FileNotFoundError if there is no such file."""
        ...

    async def delete(self, key: str) -> None:
        """Remove the file; a missing key is not an error."""
        ...
