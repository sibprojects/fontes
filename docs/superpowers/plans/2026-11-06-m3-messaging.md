# M3 — Messaging, Worker, Retries, DLQ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every new document travels through RabbitMQ: the api publishes `{document_id}`, a separate `worker` process consumes it and moves the document `queued → processing → ready`. Transient failures are retried with a delay, up to 3 attempts. Permanent failures and exhausted retries end in a dead-letter queue, with the document marked `failed` and its error stored. Processing itself is a stub here; M4 plugs in real loading, chunking and embedding.

**Architecture:**
- **Application:** an `IngestionService` decides what happens to one message, and returns an `IngestOutcome`: ack, retry or dead-letter. It talks to the ports `DocumentRepository` (plus new status methods), `DocumentProcessor` (stub now, real in M4) and `MessagePublisher`. All retry and status rules live here and are unit-tested on fakes.
- **Messaging adapter (aio-pika):** the explicit topology, a publisher and a consumer that turns an `IngestOutcome` into ack, republish to the retry queue, or republish to the DLQ. One lazily opened, long-lived connection is shared by the publisher and `/health`.
- **Worker:** `python -m fontes.worker`, wired in `container.py`, runs as its own compose service.

**Tech Stack:** M2 stack. aio-pika is already a dependency.

**Spec:** `docs/superpowers/specs/2026-11-03-fontes-design.md` (Ingestion flow; Calls made by the designer: permanent vs transient errors, status between retries, delete during ingestion). Previous milestone: `docs/superpowers/plans/2026-11-05-m2-documents.md`.

## Global Constraints

- All M1 and M2 Global Constraints still hold: Python 3.12, `mypy --strict`, ruff, the layering tests, integration tests marked `integration`, LF endings, commit and push per task, **no co-author or AI attribution trailers**.
- The domain and application layers must not import aio-pika (already in `FORBIDDEN`).
- "The message is **acked only after success**." A message is acked only after the document's new status is written, or after its retry/DLQ copy is confirmed by the broker.
- "Retries … up to a fixed number of attempts (3 by default)." "Use a retry queue with a TTL and a dead-letter exchange back to the main queue."
- "When the attempts run out, the message goes to a **dead-letter queue**. The document is marked `failed` and the error message is stored."
- "A redelivered message for a document that is already `ready` is a no-op."
- Permanent errors (corrupt file, unsupported content, HTTP 4xx) are not retried: straight to `failed` and the DLQ. Transient errors (network, database, Ollama) are retried.
- Between retries the document goes back to `queued`, and `attempts` is stored.
- A message for a missing document is acked and dropped. If the document disappears mid-processing, the results are discarded.
- The Postgres row is the source of truth for status; RabbitMQ only carries work.
- The topology is written explicitly with aio-pika, not hidden behind Celery or similar.

## Decisions for this milestone (designer's calls)

- **Topology** (all durable, names prefixed by `amqp_prefix`, default `fontes`):
  - `fontes.ingest` — main work queue. Messages are published to it through the default exchange.
  - `fontes.ingest.retry` — no consumers. Arguments: `x-message-ttl = ingest_retry_delay_ms` (default **5000**), `x-dead-letter-exchange = ""`, `x-dead-letter-routing-key = "fontes.ingest"`. An expired message flows back into the main queue.
  - `fontes.ingest.dlq` — final resting place, inspected in the management UI.
  - Retry and dead-letter are **explicit republishes by the consumer, then ack** (publisher confirms on). This lets the app decide between retry and DLQ and attach the error as a header, which `reject()` cannot.
  - A fixed delay, not exponential: one TTL queue keeps the topology readable. The README explains this.
- **Message:** JSON `{"document_id": "<uuid>"}`, `content_type=application/json`, persistent delivery. A body that does not parse goes straight to the DLQ (poison message).
- **Attempts** are counted in Postgres (`documents.attempts`, incremented when processing starts). `ingest_max_attempts = 3`.
- **Handler crash** (for example, Postgres down while the service runs): the consumer cannot ask the DB, so it retries via the retry queue with a header `x-fontes-crashes`. Past `ingest_max_attempts` crashes the message goes to the DLQ.
- **Publish failure in the api** (broker down): the upload still returns 201 and the document stays `queued`. At startup the worker republishes every `queued` document (the **recovery sweep**). Duplicate messages are harmless because processing is idempotent.
- **Stub processing:** `StubDocumentProcessor(delay_seconds)` sleeps `stub_processing_seconds` (default **1.0**) so `processing` is visible in the demo, then succeeds.
- **Prefetch:** `worker_prefetch = 1`.
- **Deferred minors from M1 folded in here:** `/health` uses the shared long-lived connection; the RabbitMQ check reports a clear message on timeout; compose gets an api healthcheck and `restart: unless-stopped`; CI builds the image and runs a compose smoke test.

## Review Focus

- **The broker is down when a file is uploaded.** The upload still returns 201 and the document is not lost: the worker's startup sweep republishes it. Pinned in Task 4 (`test_upload_succeeds_when_publish_fails`) and Task 2 (`test_requeue_queued_publishes_only_queued`).
- **A poison message** (not JSON, or no valid `document_id`). It goes to the DLQ once, never loops. Pinned in Task 3 (`test_poison_message_goes_to_dlq`).
- **The document is deleted before or during processing.** The message is acked and dropped, and no status write resurrects the row. Pinned in Task 2 (`test_missing_document_is_dropped`, `test_document_deleted_mid_processing_is_discarded`).
- **A redelivered message for a `ready` document.** A no-op: attempts unchanged, processor not called. Pinned in Task 2 (`test_ready_document_is_noop`).
- **The worker dies mid-processing.** The unacked message is redelivered by RabbitMQ and processed again. Pinned in Task 3 (`test_unacked_message_is_redelivered_after_consumer_dies`).

---

### Task 1: Status methods on the repository

**Files:**
- Modify: `backend/fontes/application/ports/documents.py`, `backend/fontes/adapters/persistence/documents.py`, `backend/tests/fakes.py`
- Test: `backend/tests/integration/test_document_repository.py`, `backend/tests/test_fakes.py` (new)

**Interfaces:**
- Produces on `DocumentRepository` (port, fake and SQL):
  - `async start_processing(id: UUID) -> Document | None`: in one statement sets `status='processing'`, `attempts = attempts + 1`, `error = NULL`, **only where `status != 'ready'`**; returns the updated document, or `None` if the row is missing or already ready.
  - `async set_status(id: UUID, status: DocumentStatus, error: str | None = None) -> bool`: updates status and error; `False` if the row is missing. Never inserts.
  - `async list_by_status(status: DocumentStatus) -> list[Document]`: oldest first.

- [ ] **Step 1: Write the failing tests.** The same cases run against the fake (`tests/test_fakes.py`, unit) and the SQL repo (integration):
  ```python
  async def test_start_processing_increments_attempts(repo): d=add queued doc; got = await repo.start_processing(d.id); assert got.status == PROCESSING and got.attempts == 1 and got.error is None
  async def test_start_processing_skips_ready(repo): ...set_status READY → start_processing returns None; attempts unchanged
  async def test_start_processing_missing_returns_none(repo): assert await repo.start_processing(uuid4()) is None
  async def test_set_status_with_error(repo): set_status(id, FAILED, "boom") → True; get → status FAILED, error "boom"
  async def test_set_status_missing_returns_false(repo): assert await repo.set_status(uuid4(), READY) is False; assert await repo.list() == []
  async def test_list_by_status_oldest_first(repo): ...
  ```
- [ ] **Step 2: Run them.** `uv run pytest tests/test_fakes.py` and `uv run pytest -m integration tests/integration/test_document_repository.py`. Expected: FAIL (AttributeError).
- [ ] **Step 3: Implement** in port, fake and SQL repo. The SQL `start_processing` is a single `UPDATE … WHERE id = :id AND status != 'ready' RETURNING *`.
- [ ] **Step 4: Verify.** Full suite with integration, ruff, mypy: all pass.
- [ ] **Step 5: Commit and push.** `Add document status transitions to the repository`.

### Task 2: IngestionService

**Files:**
- Create: `backend/fontes/application/ports/ingestion.py`, `backend/fontes/application/ingestion.py`, `backend/tests/application/test_ingestion_service.py`
- Modify: `backend/tests/fakes.py`

**Interfaces:**
- Consumes: Task 1 methods.
- Produces in `fontes.application.ports.ingestion`:
  - `class MessagePublisher(Protocol)`: `async publish_ingest(document_id: UUID) -> None`.
  - `class DocumentProcessor(Protocol)`: `async process(doc: Document) -> None`. Raises `PermanentIngestionError` for errors that can never succeed; any other exception is transient.
  - `class PermanentIngestionError(Exception)`.
- Produces in `fontes.application.ingestion`:
  - `class IngestOutcome(StrEnum)`: `ACK = "ack"`, `RETRY = "retry"`, `DEAD_LETTER = "dead_letter"`.
  - `@dataclass(frozen=True) class IngestResult`: `outcome: IngestOutcome`, `error: str | None = None`.
  - `class IngestionService(repo: DocumentRepository, processor: DocumentProcessor, publisher: MessagePublisher, max_attempts: int)` with:
    - `async handle(document_id: UUID) -> IngestResult`
    - `async requeue_queued() -> int` — publishes every `queued` document, returns the count.
- Produces in `tests/fakes.py`: `FakePublisher` (`published: list[UUID]`, optional `fail: bool`), `FakeProcessor` (a queue of exceptions to raise per call, `calls: int`).

- [ ] **Step 1: Write the failing tests** (fakes, `max_attempts=3`):
  ```python
  async def test_success_marks_ready(): handle → ACK; doc READY, attempts 1, processor.calls 1
  async def test_missing_document_is_dropped(): handle(uuid4()) → ACK; repo.list() == []
  async def test_ready_document_is_noop(): READY doc → ACK; processor.calls 0; attempts unchanged
  async def test_transient_failure_retries_and_requeues(): processor raises ConnectionError("down") → RETRY, error "ConnectionError: down"; doc QUEUED, attempts 1, error stored
  async def test_transient_failure_exhausted_dead_letters(): three ConnectionErrors over three handle() calls → RETRY, RETRY, DEAD_LETTER; doc FAILED, attempts 3, error stored
  async def test_permanent_failure_dead_letters_at_once(): PermanentIngestionError("corrupt PDF") → DEAD_LETTER on the first attempt; doc FAILED, error "corrupt PDF"
  async def test_document_deleted_mid_processing_is_discarded(): processor deletes the row inside process() → ACK; repo.list() == []
  async def test_requeue_queued_publishes_only_queued(): one queued, one ready, one failed → returns 1; publisher.published == [queued.id]
  ```
  The stored error is the user-facing text: `str(exc)` for permanent errors, `f"{type(exc).__name__}: {exc}"` for transient ones.
- [ ] **Step 2: Run them.** `uv run pytest tests/application/test_ingestion_service.py`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement.** `handle`: `start_processing` → `None` means ACK (missing or ready). Run the processor. Success → `set_status(READY)`. Permanent → `set_status(FAILED, msg)` + DEAD_LETTER. Transient → `attempts < max_attempts` ? `set_status(QUEUED, msg)` + RETRY : `set_status(FAILED, msg)` + DEAD_LETTER. A `set_status` returning `False` (row gone) means ACK.
- [ ] **Step 4: Verify.** Full suite, ruff, mypy, layering: all pass.
- [ ] **Step 5: Commit and push.** `Add IngestionService with retry and dead-letter decisions`.

### Task 3: RabbitMQ adapter: topology, publisher, consumer

**Files:**
- Create: `backend/fontes/adapters/messaging/connection.py`, `topology.py`, `publisher.py`, `consumer.py`; `backend/tests/integration/test_messaging.py`
- Modify: `backend/fontes/adapters/messaging/health.py`, `backend/tests/integration/test_health_adapters.py`, `backend/fontes/config.py`, `backend/fontes/container.py` (one `AmqpConnection` for the health check, closed in the lifespan)

**Interfaces:**
- Config: `amqp_prefix: str = "fontes"`, `ingest_max_attempts: int = 3`, `ingest_retry_delay_ms: int = 5000`, `worker_prefetch: int = 1`, `stub_processing_seconds: float = 1.0`.
- `AmqpConnection(url: str, connect_timeout: float)`: `async get() -> AbstractRobustConnection` connects on first call (`aio_pika.connect_robust`) and caches; a failed connect raises and the next call tries again; `async close() -> None`. Building it opens nothing.
- `Topology(prefix: str, retry_delay_ms: int)`: properties `main`, `retry`, `dlq` (queue names); `async declare(channel) -> None` declares the three queues as above, idempotently.
- `AmqpPublisher(connection: AmqpConnection, topology: Topology)` implements `MessagePublisher` with publisher confirms.
- `IngestConsumer(connection, topology, handle: Callable[[UUID], Awaitable[IngestResult]], max_crashes: int, prefetch: int)`: `async start() -> None` declares the topology and starts consuming; `async stop() -> None`. Per message:
  - body not parseable → publish to DLQ with header `x-fontes-error`, ack;
  - `ACK` → ack; `RETRY` → publish copy to retry queue, then ack; `DEAD_LETTER` → publish copy to DLQ with `x-fontes-error`, then ack;
  - handler raises → `x-fontes-crashes + 1` ≤ `max_crashes` ? retry : DLQ; then ack;
  - a failed republish → `nack(requeue=True)`.
- `RabbitMQHealthCheck(connection: AmqpConnection)`: calls `get()` and fails if the connection is closed; a `TimeoutError` becomes `"rabbitmq unavailable: connect timed out"`; the password is still scrubbed.

- [ ] **Step 1: Write the failing integration tests.** Each test uses a unique prefix (`f"test-{uuid4().hex[:8]}"`), `retry_delay_ms=200`, and deletes its queues afterwards. The handler is a scripted fake returning `IngestResult`s.
  ```python
  async def test_declare_is_idempotent(): declare twice; queues exist with the TTL/DLX arguments
  async def test_published_message_is_consumed_and_acked(): publish id → handler receives the same UUID; main queue empty afterwards
  async def test_retry_comes_back_after_ttl(): handler script [RETRY, ACK] → handler called twice for the same id, second call ≥ 0.2 s after first; DLQ empty
  async def test_dead_letter_lands_in_dlq_with_error(): [DEAD_LETTER("corrupt")] → DLQ holds one message, body has the id, header x-fontes-error == "corrupt"
  async def test_poison_message_goes_to_dlq(): raw body b"not json" → handler never called; DLQ holds it
  async def test_handler_crash_is_retried_then_dead_lettered(): handler always raises, max_crashes=2 → called 3 times, then DLQ
  async def test_unacked_message_is_redelivered_after_consumer_dies(): handler blocks; close consumer's channel; a second consumer receives the same id
  async def test_health_uses_shared_connection(): two checks → one connection opened
  ```
  Update `test_health_adapters.py` to the new `RabbitMQHealthCheck(AmqpConnection(...))` and add `test_rabbitmq_timeout_message_is_clear` (black-hole address, `connect_timeout=0.3` → message contains "timed out").
- [ ] **Step 2: Run them.** `uv run pytest -m integration tests/integration/test_messaging.py`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** the four modules and the health change.
- [ ] **Step 4: Verify.** Full suite with integration, ruff, mypy. `tests/test_wiring.py` must still pass (building the app opens no connection).
- [ ] **Step 5: Commit and push.** `Add RabbitMQ topology, publisher and consumer with retry and DLQ`.

### Task 4: Publish on upload

**Files:**
- Modify: `backend/fontes/application/documents.py`, `backend/fontes/container.py` (an `AmqpPublisher` over the shared `AmqpConnection` from Task 3), `backend/tests/application/test_document_service.py`, `backend/tests/api/test_documents.py`, `backend/tests/api/test_health.py`, `backend/tests/integration/test_documents_api.py`

**Interfaces:**
- Consumes: `MessagePublisher` (Task 2), `AmqpPublisher` and `AmqpConnection` (Task 3).
- `DocumentService.__init__(repo, storage, publisher: MessagePublisher, max_upload_bytes, clock=...)`.
- `upload` and `add_url` publish `document.id` **only when `created`**. A publish failure is logged at WARNING (`logging.getLogger(__name__)`) and swallowed: the result is still returned.

- [ ] **Step 1: Write the failing tests:**
  ```python
  async def test_upload_publishes_new_document(): r = upload → publisher.published == [r.document.id]
  async def test_duplicate_upload_does_not_publish(): second upload of same bytes → published has one id
  async def test_add_url_publishes(): ...
  async def test_upload_succeeds_when_publish_fails(): FakePublisher(fail=True) → r.created; repo has the doc, status QUEUED
  ```
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Update all `DocumentService(...)` call sites in tests to pass `FakePublisher()`.
- [ ] **Step 4: Verify.** Full suite, ruff, mypy.
- [ ] **Step 5: Commit and push.** `Publish an ingest message for each new document`.

### Task 5: Worker process and wiring

**Files:**
- Create: `backend/fontes/adapters/processing.py` (`StubDocumentProcessor`), `backend/fontes/worker/__init__.py`, `backend/fontes/worker/__main__.py`, `backend/tests/integration/test_worker.py`
- Modify: `backend/fontes/container.py`, `docker-compose.yml`, `backend/Dockerfile` (no change expected; the image already has the code)

**Interfaces:**
- `container.build_app(settings)` keeps the shared `AmqpConnection` from Tasks 3–4.
- `container.build_worker(settings) -> Worker`, where `Worker` has `async run(stop: asyncio.Event) -> None`: opens the connection, starts `IngestConsumer` with `IngestionService.handle`, runs `requeue_queued()` once, waits for `stop`, then stops the consumer and disposes engine and connection.
- `python -m fontes.worker`: `asyncio.run`, with SIGTERM/SIGINT setting the event (signal handlers only where the platform supports them). Logs at INFO: started, each outcome with document id, stopped.
- Compose: service `worker` (image `fontes-backend`, `command: ["python", "-m", "fontes.worker"]`, same env as api plus `STORAGE_DIR` and the `uploads` volume, depends on `migrate` completed and `rabbitmq` healthy, `restart: unless-stopped`). `api` gets `restart: unless-stopped` and a healthcheck: `python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"`, interval 10s. Only `migrate` keeps `build:`; `api` and `worker` use `image: fontes-backend` (fixes the M2 double-build minor).

- [ ] **Step 1: Write the failing integration test** (`test_worker.py`, real Postgres + RabbitMQ, unique prefix, `stub_processing_seconds=0`):
  ```python
  async def test_upload_goes_queued_to_ready_through_rabbitmq(): build_app + build_worker on the same settings; POST a file → poll GET /documents until status == "ready" (timeout 10 s); attempts == 1
  async def test_worker_sweep_publishes_queued_documents(): insert a queued doc directly via the repo (no message) → start worker → becomes ready
  async def test_failing_processor_ends_failed_in_dlq(): worker with a processor that always raises ConnectionError, retry_delay_ms=100 → doc FAILED, attempts 3, error stored; DLQ holds one message
  ```
  `build_worker` accepts an optional `processor: DocumentProcessor | None = None` override for the last test.
- [ ] **Step 2: Run them.** Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** the stub processor, `build_worker`, the entrypoint, the api wiring and the compose changes.
- [ ] **Step 4: Verify end to end.**
  1. `docker compose up -d --build`; `docker compose ps` shows `api` healthy, `worker` running, `migrate` exited 0.
  2. Upload a file with curl; `GET /documents` shows `queued`/`processing`, then `ready` within a few seconds.
  3. `docker compose stop rabbitmq`, upload a file (201, stays `queued`), `docker compose start rabbitmq`, `docker compose restart worker`: the document becomes `ready` (sweep).
  4. Management UI shows the three queues.
  5. Full suite, ruff, mypy: all pass.
- [ ] **Step 5: Commit and push.** `Add ingestion worker and wire RabbitMQ into the app`.

### Task 6: CI compose smoke test and README

**Files:**
- Create: `scripts/smoke.sh` (bash, `set -euo pipefail`, base URL from `$1`, default `http://127.0.0.1:8000`)
- Modify: `.github/workflows/ci.yml`, `README.md`

- [ ] **Step 1: Write `scripts/smoke.sh`:** `curl -fsS $BASE/health`; upload a small generated Markdown file with a random line (so it is never a duplicate); poll `GET $BASE/documents/` for that id up to 30 s until `ready`; exit 1 with the last status on timeout. It needs only curl and grep/sed (no jq).
- [ ] **Step 2: Prove it can fail, locally:** `docker compose stop worker` → `scripts/smoke.sh` exits 1 within 30 s; `docker compose start worker` → exits 0.
- [ ] **Step 3:** Add a CI job `compose-smoke` (`needs: backend`): `docker compose up -d --build --wait api worker`, then `scripts/smoke.sh`; on failure print `docker compose logs`; always `docker compose down -v`.
- [ ] **Step 4: README:** a "How ingestion works" section with the three queues as a small diagram (text or Mermaid), the retry/DLQ rules, how to watch it in the management UI, and the **"Why not Celery"** section with the spec's two reasons: the stack is async end to end, and the queue topology is explicit on purpose. Add the worker to the services table.
- [ ] **Step 5: Commit and push.** `Add compose smoke test to CI; document ingestion and why not Celery`. Watch CI: both jobs green.
