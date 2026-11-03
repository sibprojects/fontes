# Fontes — Design

*Fontes* is Latin for "sources". You upload your own documents, ask a question, and get an answer in which every claim points back to the document and page it came from.

## Intent

This is a portfolio project for a senior backend developer with 20 years of experience, mostly in PHP: Symfony, Laravel, AWS, SQS, RabbitMQ, and third-party integrations. It shows that he can build a modern Python system of good quality.

The main audience is a **technical reviewer**, such as a tech lead or a senior engineer. That person will read the code and also run the demo locally. Both experiences have to hold up:

- `docker compose up` gives a working app that answers questions about the reviewer's own documents.
- The repository reads as clean, deliberate architecture, with real background processing through a message broker.

What the owner most wants to show: **architecture**, plus **queues and background processing**.

## Goals

- Ingest documents asynchronously. Supported sources: PDF, Markdown, HTML files, and a URL to a web page.
- Answer a single question at a time, using retrieval over the ingested documents.
- Cite **document and page** for every answer. Stream the answer to the UI over SSE.
- Store the **history** of questions and answers, so past Q&As can be browsed and reopened.
- Run fully **free and local** by default: local LLM and local embeddings, with no paid API needed.
- Make Claude available as an optional LLM provider, enabled by configuration.
- Hold a professional quality bar: typed code (mypy), tests (pytest), lint, CI in GitHub Actions, and a good README.

## Non-goals

- Authentication, users, or multi-tenancy. There is one shared space.
- Conversational context, i.e. follow-up questions that use earlier answers. Every question stands alone. History is stored for browsing, not fed back to the model.
- Production deployment or hosting. The app runs locally only.
- DOCX, scanned PDFs, and OCR.
- A polished, design-heavy frontend.

## Anti-goals

These would make the project a failure even if it technically works.

- **An answer without sources.** This is the one the owner named explicitly. The system must never present an uncited answer as a normal answer:
  - If retrieval finds nothing relevant, the system says that it found nothing and does not call the LLM.
  - Support is checked **per paragraph** (see "Citation verification"). A paragraph with no valid `[n]` marker is highlighted as unsupported. The answer as a whole is labelled `supported`, `partially_supported` or `unsupported`.
  - While the answer streams, the text is shown as **provisional** ("verifying…"). It never looks verified before the check has finished.
- Looking like a copy-paste RAG tutorial, for example a single `main.py` with LangChain. The architecture has to be visible and intentional.

## Architecture

### Services (docker-compose)

| Service | Role |
|---|---|
| `postgres` | PostgreSQL with the pgvector extension. Stores documents, chunks with embeddings, and Q&A history. |
| `rabbitmq` | Message broker, with the management UI exposed on `localhost:15672` for the demo. |
| `ollama` | Local LLM and local embedding model. |
| `api` | FastAPI app: uploads, URL submission, document list and status, ask (SSE), history. |
| `worker` | Consumes ingestion messages from RabbitMQ, then parses, chunks, embeds, and stores. |
| `frontend` | React SPA. |

A single command, `docker compose up`, brings everything up. Database migrations (Alembic) run automatically at startup. The first startup pulls the Ollama models. The README must say that this takes a while and roughly how much disk space it needs.

### Code structure (backend)

```
backend/
  pyproject.toml           # uv
  alembic/
  fontes/
    domain/                # entities and value objects, no framework imports
    application/           # use cases and ports (Protocols)
    adapters/              # implementations of the ports
      persistence/         # SQLAlchemy (async), pgvector
      messaging/           # aio-pika publisher and consumer
      llm/                 # ollama.py, claude.py
      embeddings/          # ollama embeddings
      loaders/             # pdf, markdown, html, url
      storage/             # local file storage for uploads
    api/                   # FastAPI routers, schemas, SSE
    worker/                # worker entrypoint
    config.py              # pydantic-settings
    container.py           # composition root / wiring
  tests/
frontend/
docker-compose.yml
.github/workflows/ci.yml
README.md
```

The design is hexagonal (ports and adapters). The domain and application layers must not import FastAPI, SQLAlchemy, aio-pika, or any LLM SDK. All wiring happens in one composition root.

### Ports (application layer)

- `LLMProvider`: streams an answer for a prompt built from the question and the retrieved chunks.
- `Embedder`: turns texts into vectors.
- `DocumentRepository`, `ChunkRepository` (including vector search), `QuestionRepository` (history).
- `MessagePublisher`: publishes an "ingest document" message.
- `DocumentLoader`: one loader per source type (PDF, Markdown, HTML, URL). Each produces text segments with location metadata.
- `FileStorage`: stores uploaded files.

The LLM provider is chosen by configuration. `LLM_PROVIDER=ollama` is the default. `LLM_PROVIDER=claude` also needs `ANTHROPIC_API_KEY`. Switching providers needs no code change.

### Ingestion flow

1. The `api` receives a file upload or a URL. It stores the file, creates a `Document` row with status `queued`, publishes a message `{document_id}` to RabbitMQ, and returns right away.
2. The `worker` consumes the message and sets the status to `processing`. Then it:
   - loads the document with the loader for its type;
   - splits it into chunks, each keeping its location (see Citations);
   - embeds the chunks and stores them;
   - sets the status to `ready`.
3. The message is **acked only after success**.
4. **Retries.** On failure, the message is retried with a delay, up to a fixed number of attempts (3 by default). Use a retry queue with a TTL and a dead-letter exchange back to the main queue, or an equivalent native RabbitMQ mechanism.
5. **Dead letter.** When the attempts run out, the message goes to a **dead-letter queue**. The document is marked `failed` and the error message is stored.
6. **Idempotent processing.** A redelivered message for a document that is already `ready` is a no-op. A partial earlier attempt must not leave duplicate chunks.

The RabbitMQ topology (exchanges, queues, DLX, and ack semantics) is written explicitly with `aio-pika`, **not** hidden behind Celery or a similar framework. Showing this is the point.

The UI shows each document's status (`queued`, `processing`, `ready`, `failed` with the reason). Polling is acceptable.

### Ask flow

1. A question arrives at `POST /ask`, and the response is an SSE stream.
2. The question is embedded, and vector search returns the top-k chunks.
3. **If no chunk passes the relevance threshold:** the system streams a fixed "not found in your documents" answer, stores it in history, and makes **no LLM call**.
4. **Otherwise:**
   - Build a prompt with numbered sources. Instruct the model to put at least one `[n]` marker in every paragraph.
   - Stream the tokens to the client as provisional text.
   - After generation, run citation verification (below).
   - Send a final SSE event with the verdict: the per-paragraph support, the overall label, and the resolved citations (document title, page or location, and an excerpt).
5. Store the Q&A in history. The record holds:
   - the question and the answer text;
   - the paragraphs with their support flags;
   - the overall label;
   - the citations, as a snapshot of title, location, and excerpt, so history survives if the document is deleted;
   - the provider and model used, and the timing.

### Citation verification

This is decided **per paragraph**.

1. Split the answer into paragraphs on blank lines. A list item counts as its own paragraph.
2. In each paragraph, find the `[n]` markers. A marker is valid only if `n` refers to a source that was actually provided to the model. Invalid markers are removed from the text.
3. A paragraph with at least one valid marker is `supported`. Otherwise it is `unsupported`.
4. The overall label is:
   - `supported` if all paragraphs are supported;
   - `unsupported` if none are;
   - `partially_supported` otherwise.

Verification is a pure function in the application layer, with thorough unit tests.

**SSE events:**
- `token`: provisional text.
- `verdict`: the paragraphs with their flags, the label, and the citations.
- `error`

The UI shows the streaming text with a "verifying…" state. When `verdict` arrives, it re-renders the answer from the verified paragraphs, highlights the unsupported ones, and shows the label.

### Citations

- **PDF:** the page number.
- **Markdown, HTML, and URL:** these have no pages, so the location is the nearest preceding heading (the section title). When there is no heading, use the chunk's position in the document, for example "part 3 of 12". For URLs, the citation also shows the link.
- A citation shown in the UI shows the document name and location. Clicking it shows the excerpt of the chunk.

### History

- A list of past questions, newest first, with the ability to open one and see its answer and citations.
- No editing or re-asking is needed. Re-asking can simply be typing the question again.

### Frontend

The stack is React, TypeScript, and Vite. The owner does not know React, so the frontend must stay simple and conventional, and readable by a backend developer. There are three areas:

1. **Documents:** upload a file or paste a URL, see a list with statuses, delete a document.
2. **Ask:** a question box and the answer streaming in, marked "verifying…" until the verdict arrives. Then the answer shows the unsupported paragraphs highlighted, the label, and the citation list below it.
3. **History:** a sidebar or page listing past questions.

The frontend is never the focus of the project and should not grow its own complexity: no state-management library unless it is clearly needed.

## Quality bar

- **Python version and types.** Python 3.12+, `mypy --strict` on `fontes/`, and `ruff` for lint and format.
- **Unit tests** (pytest) for the domain and application layers, using in-memory fakes for the ports.
- **Integration tests** for the adapters against real Postgres and RabbitMQ, for example with testcontainers or the compose services in CI. These must cover:
  - the retry path and the dead-letter path;
  - the "no relevant chunks means no LLM call" behaviour;
  - discarding invalid citation markers.
- **Fakes for slow services.** Tests must not need Ollama or Claude. Use a fake `LLMProvider` and a fake `Embedder`.
- **CI** in GitHub Actions: lint, type check, tests, and a frontend build.
- **README:** what the project is and why, an architecture diagram, how to run it, how to switch to Claude, a short **"Why not Celery"** section, and screenshots. The "Why not Celery" section should give two reasons: the stack is async end-to-end, and the queue topology is explicit on purpose. The screenshots are added once the UI exists.

## Decided by the owner

- The audience is technical reviewers, and both the demo and the code matter.
- The documents are the owner's own. The supported formats are PDF, Markdown, HTML, and URLs.
- Citations are at the level of document and page.
- One shared space, with no auth.
- Single questions, with history stored.
- Emphasis on architecture and queues/background processing. RabbitMQ is used.
- Runs fully free and local, locally only.
- The failure the owner fears most is answers without sources.
- LLM: Ollama by default, Claude optional through config, behind one port.
- Citation support is checked per paragraph: unsupported paragraphs are highlighted, and the answer is labelled supported, partially supported or unsupported.
- While streaming, the answer is shown as provisional ("verifying…"), and the verdict is applied when generation ends.

## Calls made by the designer (not chosen by the owner)

- Hexagonal architecture with an explicit composition root.
- Direct `aio-pika`, not Celery, Dramatiq, or Taskiq.
- Embeddings come from Ollama as well, so there is one local model runtime. The default is a multilingual embedding model such as `bge-m3`, because the owner's documents may be in Russian as well as English. The vector dimension follows from the model and is set in config and in the migration.
- The Postgres `Document` row is the source of truth for status. RabbitMQ only carries work.
- Tooling: uv, SQLAlchemy 2.0 (async), Alembic, pydantic-settings, ruff, mypy, pytest.
- Frontend: React, TypeScript, and Vite.
- For non-PDF sources, the location is the heading or the chunk position.
- The "not found" path skips the LLM entirely.
- **Permanent and transient errors.** Errors that can never succeed are not retried: a corrupt or unparsable file, an unsupported content type, an HTTP 4xx when fetching a URL. Such a document goes straight to `failed`, and its message to the DLQ. Only transient errors are retried: network, database, and Ollama unavailable.
- **Status between retries.** The document goes back to `queued`, and the attempt count is stored and shown in the UI ("retry 2/3").
- **Delete during ingestion.** Deleting a document removes its row and its chunks. If the worker later receives a message for a missing document, it acks the message and drops it. If the document disappears mid-processing, the worker discards its results.
- **Chunks crossing PDF pages.** Chunking prefers page boundaries. A chunk that still spans two pages cites the page range, for example "pp. 4–5".
- **Changing the embedding model.** The vector dimension is fixed in the migration. Changing the model means a new migration and re-embedding everything. The README documents this, and no re-index tool is built for now.

## Left to the builder

- The chunking strategy and its sizes, top-k, and the relevance threshold. Keep them configurable.
- The default Ollama chat model. Pick a 7–8B instruct model that works reasonably on CPU and handles Russian and English. Make it configurable.
- The default Claude model, which is configurable.
- The parsing libraries for PDF, HTML, and URL extraction.
- UI styling.
- Duplicate-upload handling, such as a content hash.
- Exact API paths and schemas, apart from `POST /ask` being SSE.
- Retry delays.
