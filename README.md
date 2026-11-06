# Fontes

[![CI](https://github.com/sibprojects/fontes/actions/workflows/ci.yml/badge.svg)](https://github.com/sibprojects/fontes/actions/workflows/ci.yml)

> *Fontes* is Latin for "sources".

Fontes answers questions about your own documents, and every answer cites its sources. You upload PDFs or other docs, ask a question, and each claim in the answer links back to the document and page it came from.

**Stack:** FastAPI · PostgreSQL + pgvector · RabbitMQ · Ollama (local LLM) or Claude · React

🚧 Work in progress.

## Run locally

You need Docker with Compose.

```bash
docker compose up --build
```

To check that it works, run:

```bash
curl localhost:8000/health
# {"status":"ok","checks":{"database":"ok","rabbitmq":"ok"}}
```

| Service | URL |
|---|---|
| API | http://localhost:8000 (OpenAPI docs at `/docs`) |
| RabbitMQ management | http://localhost:15672 (login `fontes` / `fontes`) |

Database migrations run automatically: the one-shot `migrate` service applies them before `api` starts.

## API

| Method | Path | What it does |
|---|---|---|
| `POST` | `/documents` | Upload a file (multipart field `file`): `.pdf`, `.md`, `.markdown`, `.html`, `.htm`, up to 20 MiB |
| `POST` | `/documents/url` | Add a web page by URL: `{"url": "https://..."}` |
| `GET` | `/documents` | List documents, newest first |
| `DELETE` | `/documents/{id}` | Delete a document and its stored file |

A new document is `201 Created`. Uploading the same content again, or adding the same URL, returns the existing document with `200 OK`. Errors come back as `{"detail": "..."}` with `400` (empty file), `413` (too large), `415` (unsupported type), `422` (invalid URL) or `404` (unknown id).

```bash
curl -F file=@notes.md localhost:8000/documents
curl -H 'content-type: application/json' -d '{"url":"https://example.com"}' localhost:8000/documents/url
curl localhost:8000/documents
curl -X DELETE localhost:8000/documents/<id>
```

New documents stay `queued` for now: ingestion (parsing, chunking, embeddings) arrives in the next milestones.

## Development

The backend lives in `backend/` and is managed with [uv](https://docs.astral.sh/uv/):

```bash
cd backend
uv sync
cp .env.example .env            # optional: override DATABASE_URL / RABBITMQ_URL

uv run pytest                  # unit tests
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
uv run mypy fontes tests       # type check (strict)
```

The integration tests need real Postgres and RabbitMQ. Start them first, then run the tests:

```bash
docker compose up -d postgres rabbitmq
cd backend && uv run pytest -m integration
```

CI runs all of the above on every push and pull request to `main`.
