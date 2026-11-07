import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fontes.application.ports.documents import (
    DocumentRepository,
    DuplicateDocumentError,
    FileStorage,
)
from fontes.application.ports.ingestion import MessagePublisher
from fontes.domain.documents import Document, DocumentError, normalize_url

log = logging.getLogger(__name__)


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
        publisher: MessagePublisher,
        max_upload_bytes: int,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repo = repo
        self._storage = storage
        self._publisher = publisher
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
        except BaseException as exc:
            await self._storage.delete(doc.storage_key)
            # A concurrent upload of the same content won the race: return its document.
            if isinstance(exc, DuplicateDocumentError) and (
                existing := await self._repo.find_by_hash(content_hash)
            ):
                return AddResult(existing, created=False)
            raise
        return await self._queued(doc)

    async def add_url(self, url: str) -> AddResult:
        normalized = normalize_url(url)
        if existing := await self._repo.find_by_url(normalized):
            return AddResult(existing, created=False)
        doc = Document.from_url(normalized, now=self._clock())
        try:
            await self._repo.add(doc)
        except DuplicateDocumentError:
            if existing := await self._repo.find_by_url(normalized):
                return AddResult(existing, created=False)
            raise
        return await self._queued(doc)

    async def _queued(self, doc: Document) -> AddResult:
        # The document is already saved as queued; if the broker is down, the worker's
        # startup sweep publishes it later, so the upload itself still succeeds.
        try:
            await self._publisher.publish_ingest(doc.id)
        except Exception as exc:
            log.warning("Could not publish document %s for ingestion: %r", doc.id, exc)
        return AddResult(doc, created=True)

    async def list(self) -> list[Document]:
        return await self._repo.list()

    async def delete(self, id: UUID) -> None:
        doc = await self._repo.get(id)
        if doc is None or not await self._repo.delete(id):
            raise DocumentNotFoundError(f"Document {id} not found")
        if doc.storage_key is not None:
            await self._storage.delete(doc.storage_key)
