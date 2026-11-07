from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from fontes.application.ports.documents import DocumentRepository
from fontes.application.ports.ingestion import (
    DocumentProcessor,
    MessagePublisher,
    PermanentIngestionError,
)
from fontes.domain.documents import DocumentStatus


class IngestOutcome(StrEnum):
    ACK = "ack"
    RETRY = "retry"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True)
class IngestResult:
    outcome: IngestOutcome
    error: str | None = None


class IngestionService:
    """Decides what happens to one ingest message; the transport carries out the decision."""

    def __init__(
        self,
        repo: DocumentRepository,
        processor: DocumentProcessor,
        publisher: MessagePublisher,
        max_attempts: int,
    ) -> None:
        self._repo = repo
        self._processor = processor
        self._publisher = publisher
        self._max_attempts = max_attempts

    async def handle(self, document_id: UUID) -> IngestResult:
        doc = await self._repo.start_processing(document_id)
        if doc is None:  # deleted, or already ready
            return IngestResult(IngestOutcome.ACK)
        if doc.attempts > self._max_attempts:
            # Earlier attempts died with the worker (nothing was recorded), and RabbitMQ
            # keeps redelivering; without this the message would block the queue forever.
            error = f"Gave up after {self._max_attempts} attempts"
            return await self._finish(doc.id, DocumentStatus.FAILED, error)

        try:
            await self._processor.process(doc)
        except PermanentIngestionError as exc:
            return await self._finish(doc.id, DocumentStatus.FAILED, str(exc))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if doc.attempts < self._max_attempts:
                return await self._finish(doc.id, DocumentStatus.QUEUED, error)
            return await self._finish(doc.id, DocumentStatus.FAILED, error)
        return await self._finish(doc.id, DocumentStatus.READY, None)

    async def requeue_unfinished(self) -> int:
        """Publish every queued or processing document; meant for worker startup.

        With a single worker, a `processing` row at startup has no live message behind it.
        Duplicates of messages still in the queues are harmless: processing is idempotent.
        """
        unfinished = [
            *await self._repo.list_by_status(DocumentStatus.QUEUED),
            *await self._repo.list_by_status(DocumentStatus.PROCESSING),
        ]
        for doc in unfinished:
            await self._publisher.publish_ingest(doc.id)
        return len(unfinished)

    async def _finish(
        self, document_id: UUID, status: DocumentStatus, error: str | None
    ) -> IngestResult:
        if not await self._repo.set_status(document_id, status, error):
            return IngestResult(IngestOutcome.ACK)  # deleted while we worked
        outcome = {
            DocumentStatus.READY: IngestOutcome.ACK,
            DocumentStatus.QUEUED: IngestOutcome.RETRY,
            DocumentStatus.FAILED: IngestOutcome.DEAD_LETTER,
        }[status]
        return IngestResult(outcome, error)
