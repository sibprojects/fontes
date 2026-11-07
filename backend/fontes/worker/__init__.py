"""The ingestion worker: consumes ingest messages until told to stop."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from fontes.application.ingestion import IngestionService, IngestResult

log = logging.getLogger(__name__)


class Consumer(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class Worker:
    def __init__(
        self,
        service: IngestionService,
        consumer: Consumer,
        close: Callable[[], Awaitable[None]],
    ) -> None:
        self._service = service
        self._consumer = consumer
        self._close = close

    async def run(self, stop: asyncio.Event) -> None:
        try:
            await self._consumer.start()
            # Documents whose message never reached the broker (it was down at upload time).
            requeued = await self._service.requeue_queued()
            log.info("Worker started; requeued %d queued document(s)", requeued)
            await stop.wait()
        finally:
            await self._consumer.stop()
            await self._close()
            log.info("Worker stopped")


def logged(
    handle: Callable[[UUID], Awaitable[IngestResult]],
) -> Callable[[UUID], Awaitable[IngestResult]]:
    async def wrapper(document_id: UUID) -> IngestResult:
        result = await handle(document_id)
        log.info("Document %s: %s %s", document_id, result.outcome, result.error or "")
        return result

    return wrapper
