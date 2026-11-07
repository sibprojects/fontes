from datetime import UTC, datetime
from uuid import uuid4

from fontes.application.ingestion import IngestionService, IngestOutcome, IngestResult
from fontes.application.ports.ingestion import PermanentIngestionError
from fontes.domain.documents import Document, DocumentStatus
from tests.fakes import FakeProcessor, FakePublisher, InMemoryDocumentRepository

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _service(
    repo: InMemoryDocumentRepository,
    processor: FakeProcessor,
    publisher: FakePublisher | None = None,
) -> IngestionService:
    return IngestionService(repo, processor, publisher or FakePublisher(), max_attempts=3)


async def _queued(repo: InMemoryDocumentRepository, name: str = "a.pdf") -> Document:
    doc = Document.from_upload(name, f"hash-{name}", now=NOW)
    await repo.add(doc)
    return doc


async def _stored(repo: InMemoryDocumentRepository, doc: Document) -> Document:
    got = await repo.get(doc.id)
    assert got is not None
    return got


async def test_success_marks_ready() -> None:
    repo, processor = InMemoryDocumentRepository(), FakeProcessor()
    doc = await _queued(repo)
    assert await _service(repo, processor).handle(doc.id) == IngestResult(IngestOutcome.ACK)
    got = await _stored(repo, doc)
    assert (got.status, got.attempts, got.error) == (DocumentStatus.READY, 1, None)
    assert processor.calls == 1


async def test_missing_document_is_dropped() -> None:
    repo, processor = InMemoryDocumentRepository(), FakeProcessor()
    assert (await _service(repo, processor).handle(uuid4())).outcome == IngestOutcome.ACK
    assert await repo.list() == []
    assert processor.calls == 0


async def test_ready_document_is_noop() -> None:
    repo, processor = InMemoryDocumentRepository(), FakeProcessor()
    doc = await _queued(repo)
    await repo.set_status(doc.id, DocumentStatus.READY)
    assert (await _service(repo, processor).handle(doc.id)).outcome == IngestOutcome.ACK
    assert processor.calls == 0
    assert (await _stored(repo, doc)).attempts == 0


async def test_transient_failure_retries_and_requeues() -> None:
    repo = InMemoryDocumentRepository()
    processor = FakeProcessor([ConnectionError("down")])
    doc = await _queued(repo)
    result = await _service(repo, processor).handle(doc.id)
    assert result == IngestResult(IngestOutcome.RETRY, "ConnectionError: down")
    got = await _stored(repo, doc)
    assert (got.status, got.attempts, got.error) == (
        DocumentStatus.QUEUED,
        1,
        "ConnectionError: down",
    )


async def test_transient_failure_exhausted_dead_letters() -> None:
    repo = InMemoryDocumentRepository()
    processor = FakeProcessor([ConnectionError("down") for _ in range(3)])
    service = _service(repo, processor)
    doc = await _queued(repo)
    outcomes = [(await service.handle(doc.id)).outcome for _ in range(3)]
    assert outcomes == [IngestOutcome.RETRY, IngestOutcome.RETRY, IngestOutcome.DEAD_LETTER]
    got = await _stored(repo, doc)
    assert (got.status, got.attempts, got.error) == (
        DocumentStatus.FAILED,
        3,
        "ConnectionError: down",
    )


async def test_permanent_failure_dead_letters_at_once() -> None:
    repo = InMemoryDocumentRepository()
    processor = FakeProcessor([PermanentIngestionError("corrupt PDF")])
    doc = await _queued(repo)
    result = await _service(repo, processor).handle(doc.id)
    assert result == IngestResult(IngestOutcome.DEAD_LETTER, "corrupt PDF")
    got = await _stored(repo, doc)
    assert (got.status, got.attempts, got.error) == (DocumentStatus.FAILED, 1, "corrupt PDF")


async def test_document_deleted_mid_processing_is_discarded() -> None:
    repo = InMemoryDocumentRepository()

    async def delete_row(doc: Document) -> None:
        await repo.delete(doc.id)

    doc = await _queued(repo)
    result = await _service(repo, FakeProcessor(on_process=delete_row)).handle(doc.id)
    assert result.outcome == IngestOutcome.ACK
    assert await repo.list() == []


async def test_document_deleted_during_failed_attempt_is_discarded() -> None:
    repo = InMemoryDocumentRepository()

    async def delete_row(doc: Document) -> None:
        await repo.delete(doc.id)

    doc = await _queued(repo)
    processor = FakeProcessor([ConnectionError("down")], on_process=delete_row)
    assert (await _service(repo, processor).handle(doc.id)).outcome == IngestOutcome.ACK
    assert await repo.list() == []


async def test_requeue_queued_publishes_only_queued() -> None:
    repo, publisher = InMemoryDocumentRepository(), FakePublisher()
    queued = await _queued(repo, "a.pdf")
    ready = await _queued(repo, "b.pdf")
    failed = await _queued(repo, "c.pdf")
    await repo.set_status(ready.id, DocumentStatus.READY)
    await repo.set_status(failed.id, DocumentStatus.FAILED, "boom")
    assert await _service(repo, FakeProcessor(), publisher).requeue_queued() == 1
    assert publisher.published == [queued.id]


async def test_redelivery_past_attempt_limit_dead_letters_without_processing() -> None:
    # The worker died during each of three attempts (no exception, so nothing was recorded):
    # RabbitMQ keeps redelivering, and the attempt counter is the only thing that can stop it.
    repo, processor = InMemoryDocumentRepository(), FakeProcessor()
    doc = await _queued(repo)
    for _ in range(3):
        await repo.start_processing(doc.id)
    result = await _service(repo, processor).handle(doc.id)
    assert result == IngestResult(IngestOutcome.DEAD_LETTER, "Gave up after 3 attempts")
    assert processor.calls == 0
    got = await _stored(repo, doc)
    assert (got.status, got.error) == (DocumentStatus.FAILED, "Gave up after 3 attempts")
