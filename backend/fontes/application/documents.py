import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fontes.application.ports.documents import DocumentRepository, FileStorage
from fontes.domain.documents import Document, DocumentError, normalize_url


class DocumentNotFoundError(Exception):
    pass


class EmptyFileError(DocumentError):
    pass


class FileTooLargeError(DocumentError):
    pass


@dataclass(frozen=True)
class AddResult:
    document: Document
    created: bool


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DocumentService:
    def __init__(
        self,
        repo: DocumentRepository,
        storage: FileStorage,
        max_upload_bytes: int,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repo = repo
        self._storage = storage
        self._max_upload_bytes = max_upload_bytes
        self._clock = clock

    async def upload(self, filename: str, data: bytes) -> AddResult:
        if not data:
            raise EmptyFileError("The file is empty")
        if len(data) > self._max_upload_bytes:
            raise FileTooLargeError(f"The file exceeds the {self._max_upload_bytes}-byte limit")
        content_hash = hashlib.sha256(data).hexdigest()
        doc = Document.from_upload(filename, content_hash, now=self._clock())
        if existing := await self._repo.find_by_hash(content_hash):
            return AddResult(existing, created=False)
        assert doc.storage_key is not None
        await self._storage.save(doc.storage_key, data)
        try:
            await self._repo.add(doc)
        except BaseException:
            await self._storage.delete(doc.storage_key)
            raise
        return AddResult(doc, created=True)

    async def add_url(self, url: str) -> AddResult:
        if existing := await self._repo.find_by_url(normalize_url(url)):
            return AddResult(existing, created=False)
        doc = Document.from_url(url, now=self._clock())
        await self._repo.add(doc)
        return AddResult(doc, created=True)

    async def list(self) -> list[Document]:
        return await self._repo.list()

    async def delete(self, id: UUID) -> None:
        doc = await self._repo.get(id)
        if doc is None or not await self._repo.delete(id):
            raise DocumentNotFoundError(f"Document {id} not found")
        if doc.storage_key is not None:
            await self._storage.delete(doc.storage_key)
