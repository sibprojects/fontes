from typing import Protocol
from uuid import UUID

from fontes.domain.documents import Document


class PermanentIngestionError(Exception):
    """The document can never be processed (e.g. corrupt file); retrying will not help."""


class MessagePublisher(Protocol):
    async def publish_ingest(self, document_id: UUID) -> None: ...


class DocumentProcessor(Protocol):
    async def process(self, doc: Document) -> None:
        """Raise PermanentIngestionError for hopeless input; any other exception is transient."""
        ...
