# M1 — Backend Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a runnable, tested, CI-checked backend skeleton:
- `docker compose up` starts Postgres (pgvector), RabbitMQ and the FastAPI `api` service;
- `GET /health` reports whether the database and the broker are reachable.

**Architecture:** Hexagonal from day one.
- The application layer defines a `HealthCheck` port.
- Adapters implement the port for Postgres (SQLAlchemy async) and RabbitMQ (aio-pika).
- A composition root (`container.py`) wires them into the FastAPI app.
- The API layer depends only on the port, never on the adapters.

**Tech Stack:** Python 3.12, uv, FastAPI, uvicorn, pydantic-settings, SQLAlchemy 2.0 async + asyncpg, aio-pika, pytest + pytest-asyncio + httpx, ruff, mypy --strict, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-03-fontes-design.md`

## Roadmap (one plan per milestone; only M1 is detailed here)

| # | Milestone | Ends with |
|---|---|---|
| **M1** | Backend skeleton: tooling, health endpoint, compose, CI | `/health` green in compose and in CI |
| M2 | Documents: domain model, Alembic migration, upload/URL/list/delete API (status stays `queued`) | documents can be created and listed |
| M3 | Messaging: aio-pika topology, publisher, worker, retries, DLQ, statuses; stub processing | a document goes `queued → processing → ready/failed` through RabbitMQ |
| M4 | Ingestion: loaders (PDF/MD/HTML/URL), chunking with locations, Ollama embeddings, pgvector storage | real documents end up as searchable chunks |
| M5 | Ask: retrieval, LLM port (Ollama), citation verification, SSE, history | questions answered with verified citations |
| M6 | Frontend: React + Vite (documents, ask, history) | usable UI |
| M7 | Claude provider, README (architecture diagram, Why not Celery, screenshots) | portfolio-ready |

Each milestone gets its own plan file written when the previous one is done.

## Global Constraints

- Python `>=3.12`, pinned to 3.12 via `.python-version`. The Docker image is `python:3.12-slim`.
- Package: `backend/fontes/`, with imports like `from fontes.api import ...`.
- Layer rule: `fontes/domain` and `fontes/application` must not import fastapi, sqlalchemy, aio_pika or any LLM SDK.
- `mypy --strict` passes on `fontes/` and `tests/`. `ruff check` and `ruff format --check` pass.
- Tests must not need Ollama or Claude. Integration tests are marked `@pytest.mark.integration` and are excluded from the default run.
- Settings come from environment variables via pydantic-settings, with no prefix: `DATABASE_URL`, `RABBITMQ_URL`.
- Every task ends with a commit and a push to `origin main`. Commit messages are in English, with no co-author or AI attribution trailers.
- The repo is developed on Windows, so files use LF line endings, enforced by `.gitattributes`.

## Review Focus

- **The api starts before Postgres/RabbitMQ are ready.** The api must not crash on startup. `/health` returns 503 until the dependencies are up, then 200. Pinned in Task 2: no connections at import or startup time.
- **A dependency hangs** (for example, an unreachable host that silently drops packets). `/health` must answer within about 3 s with 503, not hang. Pinned in Task 2: `test_health_times_out_slow_check`.
- **One check fails and the others pass.** The response must name which dependency failed, so the user knows what to fix. Pinned in Task 2: `test_health_reports_failing_check`.
- **CRLF line endings from a Windows checkout break the Docker build or the shell.** Pinned in Task 1 with `.gitattributes`.
- **Error details leak credentials.** A failing database check must not echo `DATABASE_URL`, which contains the password, into the response. Pinned in Task 3: `test_postgres_check_error_hides_password`.

---

### Task 1: Python project tooling

**Files:**
- Create: `.gitattributes`, `.gitignore`, `backend/.python-version`, `backend/pyproject.toml`, `backend/fontes/__init__.py`, `backend/fontes/config.py`, `backend/tests/__init__.py`, `backend/tests/test_config.py`

**Interfaces:**
- Produces: `fontes.config.Settings` (pydantic `BaseSettings`), with these fields:
  - `database_url: str = "postgresql+asyncpg://fontes:fontes@localhost:5432/fontes"`
  - `rabbitmq_url: str = "amqp://fontes:fontes@localhost:5672/"`
  - `health_check_timeout: float = 3.0`
- Produces: `fontes.config.get_settings() -> Settings`, cached with `functools.lru_cache`.

- [ ] **Step 1: Install uv**

  Run (PowerShell): `py -3.14 -m pip install --user uv`, then check with `py -3.14 -m uv --version`. If `uv` is not on PATH, invoke it as `py -3.14 -m uv` in all later steps.

- [ ] **Step 2: Create the uv project**

  - In `backend/`, add `pyproject.toml` with `name = "fontes"`, `requires-python = ">=3.12"`, a hatchling build with the package `fontes`.
  - Runtime dependencies: `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `sqlalchemy[asyncio]`, `asyncpg`, `aio-pika`.
  - Dependency group `dev`: `pytest`, `pytest-asyncio`, `httpx`, `mypy`, `ruff`.
  - Tool config:
    - `[tool.pytest.ini_options]`: `asyncio_mode = "auto"`, `markers = ["integration: needs running Postgres/RabbitMQ"]`, `addopts = "-m 'not integration'"`.
    - `[tool.mypy]`: `strict = true`, `plugins = ["pydantic.mypy"]`.
    - `[tool.ruff]`: `line-length = 100`, `target-version = "py312"`, lint `select = ["E","F","I","UP","B","SIM","ASYNC"]`.
  - `.python-version` contains `3.12`.

  Run `uv sync` in `backend/`. Expected: `.venv` is created and `uv.lock` is written.

- [ ] **Step 3: Add `.gitattributes` and `.gitignore`**

  - `.gitattributes`: `* text=auto eol=lf`.
  - `.gitignore`: `.venv/`, `__pycache__/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `.env`, `node_modules/`, `dist/`.

- [ ] **Step 4: Write the failing test**

  ```python
  # backend/tests/test_config.py
  from fontes.config import Settings

  def test_settings_read_env(monkeypatch):
      monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
      monkeypatch.setenv("RABBITMQ_URL", "amqp://u:p@mq:5672/")
      s = Settings()
      assert s.database_url == "postgresql+asyncpg://u:p@db:5432/x"
      assert s.rabbitmq_url == "amqp://u:p@mq:5672/"
      assert s.health_check_timeout == 3.0
  ```

- [ ] **Step 5: Run it.** `uv run pytest tests/test_config.py -v`. Expected: FAIL (ImportError).

- [ ] **Step 6: Implement `Settings` and `get_settings()`** in `fontes/config.py`, with the values listed under Interfaces.

- [ ] **Step 7: Verify.** Run `uv run pytest -v`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy fontes tests`. Expected: all pass.

- [ ] **Step 8: Commit and push.** Message: `Set up backend project tooling`.

### Task 2: Health port and `/health` endpoint

**Files:**
- Create: `backend/fontes/application/__init__.py`, `backend/fontes/application/ports/__init__.py`, `backend/fontes/application/ports/health.py`, `backend/fontes/api/__init__.py`, `backend/fontes/api/app.py`, `backend/fontes/api/health.py`, `backend/tests/api/__init__.py`, `backend/tests/api/test_health.py`

**Interfaces:**
- Consumes: `Settings.health_check_timeout`.
- Produces: `fontes.application.ports.health.HealthCheck`, a Protocol with:
  - `name: str`;
  - `async def check(self) -> None`, which raises any `Exception` on failure.
- Produces: `fontes.api.app.create_app(checks: Sequence[HealthCheck], health_timeout: float) -> FastAPI`.
- Produces: `GET /health` response JSON `{"status": "ok" | "fail", "checks": {<name>: "ok" | "<error text>"}}`. HTTP 200 when every check is ok, 503 otherwise.

- [ ] **Step 1: Write the failing tests**

  These use in-test fakes: an `OkCheck(name)`, a `FailCheck(name, msg)` that raises `RuntimeError(msg)`, and a `SlowCheck(name)` that runs `await asyncio.sleep(10)`. They call the app with `httpx.AsyncClient(transport=ASGITransport(app))`.

  ```python
  async def test_health_ok():
      app = create_app([OkCheck("database"), OkCheck("rabbitmq")], health_timeout=1.0)
      r = await client(app).get("/health")
      assert r.status_code == 200
      assert r.json() == {"status": "ok", "checks": {"database": "ok", "rabbitmq": "ok"}}

  async def test_health_reports_failing_check():
      app = create_app([OkCheck("database"), FailCheck("rabbitmq", "connection refused")], health_timeout=1.0)
      r = await client(app).get("/health")
      assert r.status_code == 503
      assert r.json() == {"status": "fail", "checks": {"database": "ok", "rabbitmq": "connection refused"}}

  async def test_health_times_out_slow_check():
      app = create_app([SlowCheck("database")], health_timeout=0.1)
      started = time.monotonic()
      r = await client(app).get("/health")
      assert time.monotonic() - started < 1.0
      assert r.status_code == 503
      assert r.json()["checks"]["database"] == "timeout"
  ```

- [ ] **Step 2: Run them.** `uv run pytest tests/api -v`. Expected: FAIL (ImportError).

- [ ] **Step 3: Implement the port, the router and `create_app`**

  - Run the checks concurrently with `asyncio.gather`. Wrap each check in `asyncio.wait_for(check.check(), health_timeout)`.
  - `TimeoutError` maps to `"timeout"`. Any other exception maps to `str(exc)`, or to the exception class name if the message is empty.
  - Pass the checks to the router via `app.state` or a dependency, never via module globals.
  - `create_app` must not open any connections.

- [ ] **Step 4: Verify.** Run `uv run pytest -v`, then ruff and mypy as in Task 1. Expected: all pass.

- [ ] **Step 5: Commit and push.** Message: `Add health port and /health endpoint`.

### Task 3: Postgres and RabbitMQ health adapters, plus dev compose

**Files:**
- Create: `docker-compose.yml`, `.env.example`, `backend/fontes/adapters/__init__.py`, `backend/fontes/adapters/persistence/__init__.py`, `backend/fontes/adapters/persistence/health.py`, `backend/fontes/adapters/messaging/__init__.py`, `backend/fontes/adapters/messaging/health.py`, `backend/fontes/container.py`, `backend/fontes/main.py`, `backend/tests/integration/__init__.py`, `backend/tests/integration/test_health_adapters.py`, `backend/tests/test_layering.py`

**Interfaces:**
- Consumes: `HealthCheck`, `create_app`, `Settings`.
- Produces:
  - `PostgresHealthCheck(engine: AsyncEngine)` with `name = "database"`. It runs `SELECT 1`.
  - `RabbitMQHealthCheck(url: str)` with `name = "rabbitmq"`. It runs `aio_pika.connect(url)` and then closes the connection.
- Produces: `fontes.container.build_app(settings: Settings) -> FastAPI`. It creates the engine with `create_async_engine(settings.database_url, pool_pre_ping=True)`, registers both checks, and disposes the engine in the lifespan shutdown.
- Produces: `fontes.main:app`, which equals `build_app(get_settings())`, as the uvicorn target.

- [ ] **Step 1: Write the compose file and `.env.example`**

  - `docker-compose.yml`:
    - `postgres` uses `pgvector/pgvector:pg17`, with env `POSTGRES_USER/PASSWORD/DB = fontes`, port `5432:5432`, a named volume `pgdata`, and a healthcheck `pg_isready -U fontes`.
    - `rabbitmq` uses `rabbitmq:4-management`, with env `RABBITMQ_DEFAULT_USER/PASS = fontes`, ports `5672:5672` and `15672:15672`, and a healthcheck `rabbitmq-diagnostics -q ping`.
  - `.env.example` lists `DATABASE_URL` and `RABBITMQ_URL` with the localhost defaults.

  Run `docker compose up -d postgres rabbitmq`, then `docker compose ps`. Expected: both containers are `healthy`.

- [ ] **Step 2: Write the failing tests**

  ```python
  # tests/integration/test_health_adapters.py  (all marked integration)
  async def test_postgres_check_ok(): ...          # default Settings, check() returns None
  async def test_rabbitmq_check_ok(): ...          # default Settings, check() returns None
  async def test_postgres_check_error_hides_password():
      engine = create_async_engine("postgresql+asyncpg://fontes:s3cret@localhost:5999/fontes")
      with pytest.raises(Exception) as exc:
          await PostgresHealthCheck(engine).check()
      assert "s3cret" not in str(exc.value)
  async def test_build_app_health_ok():            # build_app(Settings()) via ASGITransport, GET /health == 200
  ```

  ```python
  # tests/test_layering.py  (unit; protects the layer rule)
  def test_inner_layers_do_not_import_frameworks():
      # walk fontes/domain and fontes/application *.py, parse with ast,
      # assert no import whose top-level module is in {"fastapi","sqlalchemy","aio_pika","anthropic","ollama"}
  ```

- [ ] **Step 3: Run them.** `uv run pytest -m integration -v`. Expected: FAIL (ImportError).

- [ ] **Step 4: Implement the adapters, `container.py` and `main.py`**

  - If `PostgresHealthCheck` catches an exception whose text contains the password, it re-raises `RuntimeError("database unavailable: <ExceptionClass>")`.
  - Use a timeout on the aio-pika connect so that a hung broker ends with an error.

- [ ] **Step 5: Verify.**
  - `uv run pytest -m integration -v`: PASS.
  - `uv run pytest -v`: PASS, including the layering test.
  - ruff and mypy: clean.
  - Then run `docker compose stop rabbitmq` and `uv run uvicorn fontes.main:app`. `curl localhost:8000/health` must return 503 with a rabbitmq error. Then `docker compose start rabbitmq`, wait until it is healthy, and expect 200.

- [ ] **Step 6: Commit and push.** Message: `Add Postgres and RabbitMQ health checks with dev compose`.

### Task 4: Containerised api service

**Files:**
- Create: `backend/Dockerfile`, `backend/.dockerignore`
- Modify: `docker-compose.yml` (add the `api` service)

**Interfaces:**
- Consumes: `fontes.main:app`.
- Produces: the compose service `api` on `localhost:8000`.

- [ ] **Step 1: Write the Dockerfile.** It has two stages on `python:3.12-slim`:
  - copy the uv binary from `ghcr.io/astral-sh/uv`;
  - `uv sync --frozen --no-dev` into `/app/.venv`;
  - run as a non-root user;
  - `CMD ["uvicorn", "fontes.main:app", "--host", "0.0.0.0", "--port", "8000"]`.

  `.dockerignore` excludes `.venv`, the caches and `tests`.

- [ ] **Step 2: Add the `api` service to compose.**
  - `build: ./backend`, port `8000:8000`.
  - Env: `DATABASE_URL=postgresql+asyncpg://fontes:fontes@postgres:5432/fontes` and `RABBITMQ_URL=amqp://fontes:fontes@rabbitmq:5672/`.
  - `depends_on` both services with `condition: service_healthy`.

- [ ] **Step 3: Verify.** Run `docker compose up -d --build`, then `curl -s localhost:8000/health`. Expected: `{"status":"ok","checks":{"database":"ok","rabbitmq":"ok"}}`.

- [ ] **Step 4: Commit and push.** Message: `Containerise api service`.

### Task 5: CI and README run instructions

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `README.md`

- [ ] **Step 1: Write the workflow.** It triggers on push and pull_request to `main` and has one job, `backend`, on `ubuntu-latest`:
  - Service containers:
    - `pgvector/pgvector:pg17` with the same credentials as compose, port 5432, and a `pg_isready` health option;
    - `rabbitmq:4-management` with the same credentials, port 5672, and a `rabbitmq-diagnostics -q ping` health option.
  - Steps:
    1. checkout;
    2. `astral-sh/setup-uv` with caching;
    3. `uv sync --frozen`;
    4. `uv run ruff check .`;
    5. `uv run ruff format --check .`;
    6. `uv run mypy fontes tests`;
    7. `uv run pytest -v`;
    8. `uv run pytest -m integration -v`.
  - All steps run with `working-directory: backend`.

- [ ] **Step 2: Update the README.**
  - Add a "Run locally" section: `cp .env.example .env`, `docker compose up --build`, `curl localhost:8000/health`, and the RabbitMQ UI at `http://localhost:15672` (fontes/fontes).
  - Add a "Development" section: `cd backend`, `uv sync`, the test, lint and type commands, and the note that integration tests need `docker compose up -d postgres rabbitmq`.

- [ ] **Step 3: Commit and push.** Message: `Add CI workflow and run instructions`.

- [ ] **Step 4: Verify CI.** Run `gh run list -R sibprojects/fontes --limit 1`, then `gh run watch <id> -R sibprojects/fontes`. Expected: the run is green. The repo is public, so this works with the current gh account.
