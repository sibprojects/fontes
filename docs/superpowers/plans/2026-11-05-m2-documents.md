# M2 — Documents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user can upload a PDF, Markdown or HTML file, or submit a URL, and then list and delete these documents through the API. Each document is stored in Postgres with status `queued`. Processing comes in M3.

**Architecture:**
- **Domain:** the `Document` entity and its validation rules, such as the allowed source types and the URL scheme.
- **Application:** a `DocumentService` use-case class that talks to the `DocumentRepository` and `FileStorage` ports.
- **Adapters:** SQLAlchemy for the repository, with Alembic migrations, and a local disk implementation of file storage.
- **API:** FastAPI routers that call the service.
- **Wiring:** `container.py` stays the only place that connects these pieces.

**Tech Stack:** M1 stack plus Alembic (async env) and python-multipart.

**Spec:** `docs/superpowers/specs/2026-11-03-fontes-design.md`. Previous milestone: `docs/superpowers/plans/2026-11-03-m1-backend-skeleton.md`.

## Global Constraints

- All M1 Global Constraints still hold:
  - Python 3.12;
  - `mypy --strict`, ruff;
  - the layer rule, enforced by `tests/test_layering.py`;
  - integration tests marked `integration`;
  - LF line endings;
  - commit and push per task.
- Commit messages are in English with **no co-author or AI attribution trailers**.
- Supported sources: **PDF, Markdown, HTML files, and a URL to a web page**. No DOCX, OCR or scanned PDFs.
- Document statuses are `queued`, `processing`, `ready` and `failed`. M2 only ever writes `queued`.
- The Postgres `documents` row is the source of truth for status.
- One shared space: no auth and no users.
- Migrations (Alembic) run automatically at startup of `docker compose up`.
- Uploaded files are stored on local disk in a volume. They are named by document id, never by user-supplied filename.

## Decisions for this milestone (designer's calls; the spec leaves them to the builder)

- **Duplicate uploads.** The SHA-256 of the file content is stored. Re-uploading the same bytes returns the existing document with **HTTP 200** (a new document returns 201) and stores no second file. Duplicate URLs work the same way: an exact match after stripping whitespace returns the existing document.
- **Size limit.** `max_upload_bytes = 20 * 1024 * 1024`. A larger file gets 413, an empty file gets 400.
- **Title.** For a file it is the base name of the uploaded filename, with any path removed. For a URL it is the URL itself. M4 may replace it with the page title.
- **Source type** comes from the file extension, case-insensitive:
  - `.pdf` → `pdf`;
  - `.md` or `.markdown` → `markdown`;
  - `.html` or `.htm` → `html`;
  - anything else → 415.
  - URLs → `url`. Only `http` and `https` with a host are accepted, anything else gets 422.

## Review Focus

- **A filename with a path or odd characters**, such as `../../etc/passwd.pdf` or `отчёт 2026.PDF`. Nothing may be written outside the storage directory, the title is the bare file name, and an upper-case extension is accepted. Pinned in Task 1 (`test_source_type_is_case_insensitive`, `test_title_strips_directories`) and Task 4 (`test_upload_with_path_in_filename_is_stored_safely`).
- **A file larger than the limit.** It is rejected with 413 without being read entirely into memory. Pinned in Task 4: `test_upload_too_large_returns_413`, which uses a small limit.
- **The same file uploaded twice.** No second row and no second file. Pinned in Task 2 (`test_upload_duplicate_returns_existing`) and Task 3 (the unique index).
- **Deleting a document whose file is already gone from disk.** This still succeeds with 204. Pinned in Task 2: `test_delete_tolerates_missing_file`.
- **A URL with surrounding whitespace, or a non-http scheme** such as `ftp://`, `javascript:` or `file:///etc/passwd`. Whitespace is stripped, and the other schemes are rejected with 422. Pinned in Task 1: `test_url_validation`.

---

### Task 1: Domain model

**Files:**
- Create: `backend/fontes/domain/__init__.py`, `backend/fontes/domain/documents.py`, `backend/tests/domain/__init__.py`, `backend/tests/domain/test_documents.py`

**Interfaces:**
- Produces, in `fontes.domain.documents`:
  - `class DocumentStatus(StrEnum)` with the members `QUEUED="queued"`, `PROCESSING="processing"`, `READY="ready"` and `FAILED="failed"`.
  - `class SourceType(StrEnum)` with the members `PDF="pdf"`, `MARKDOWN="markdown"`, `HTML="html"` and `URL="url"`.
  - `class DocumentError(Exception)` and its subclasses `UnsupportedSourceError` and `InvalidUrlError`.
  - `def source_type_for_filename(filename: str) -> SourceType`, which raises `UnsupportedSourceError`.
  - `def normalize_url(url: str) -> str`, which strips whitespace, checks the scheme and host, and raises `InvalidUrlError`.
  - `@dataclass(frozen=True) class Document`, with these fields:
    - `id: UUID`, `title: str`, `source_type: SourceType`, `status: DocumentStatus`, `created_at: datetime`;
    - `storage_key: str | None`, `content_hash: str | None`, `url: str | None`;
    - `error: str | None = None`, `attempts: int = 0`.
  - `Document.from_upload(filename: str, content_hash: str, now: datetime) -> Document` sets the status to `queued`, a fresh `uuid4`, `storage_key=f"{id}{ext}"` with a lower-case extension, and the title `PurePath(filename.replace("\\", "/")).name`.
  - `Document.from_url(url: str, now: datetime) -> Document` sets the status to `queued`, uses the normalized URL as both `url` and title, and leaves `storage_key` and `content_hash` as None.

- [ ] **Step 1: Write the failing tests**

  ```python
  @pytest.mark.parametrize("name,expected", [("a.pdf", SourceType.PDF), ("a.md", SourceType.MARKDOWN),
      ("a.markdown", SourceType.MARKDOWN), ("a.html", SourceType.HTML), ("a.htm", SourceType.HTML)])
  def test_source_type_for_filename(name, expected): assert source_type_for_filename(name) == expected

  def test_source_type_is_case_insensitive(): assert source_type_for_filename("отчёт 2026.PDF") == SourceType.PDF

  @pytest.mark.parametrize("name", ["a.docx", "a", "pdf", "a.pdf.exe"])
  def test_unsupported_source(name): with pytest.raises(UnsupportedSourceError): source_type_for_filename(name)

  def test_url_validation():
      assert normalize_url("  https://example.com/a  ") == "https://example.com/a"
      for bad in ["ftp://x.com/a", "javascript:alert(1)", "file:///etc/passwd", "not a url", "https://"]:
          with pytest.raises(InvalidUrlError): normalize_url(bad)

  def test_from_upload():
      d = Document.from_upload("Report.PDF", "abc", now=T0)
      assert (d.status, d.source_type, d.title, d.content_hash, d.created_at) == (DocumentStatus.QUEUED, SourceType.PDF, "Report.PDF", "abc", T0)
      assert d.storage_key == f"{d.id}.pdf"

  def test_title_strips_directories():
      assert Document.from_upload("../../etc/passwd.pdf", "h", now=T0).title == "passwd.pdf"
      assert Document.from_upload("C:\\docs\\a.md", "h", now=T0).title == "a.md"

  def test_from_url():
      d = Document.from_url(" https://example.com/x ", now=T0)
      assert (d.source_type, d.url, d.title, d.storage_key) == (SourceType.URL, "https://example.com/x", "https://example.com/x", None)
  ```

- [ ] **Step 2: Run them.** `uv run pytest tests/domain -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement `fontes/domain/documents.py`.** Use only the standard library (`urllib.parse`, `pathlib.PurePath`, `uuid`). The layering test enforces this.
- [ ] **Step 4: Verify.** Run `uv run pytest -v`, then ruff and mypy. Expected: all pass.
- [ ] **Step 5: Commit and push.** Message: `Add Document domain model`.

### Task 2: Ports and DocumentService

**Files:**
- Create:
  - `backend/fontes/application/ports/documents.py`
  - `backend/fontes/application/documents.py`
  - `backend/tests/fakes.py`
  - `backend/tests/application/__init__.py`
  - `backend/tests/application/test_document_service.py`

**Interfaces:**
- Consumes: Task 1.
- Produces, in `fontes.application.ports.documents`, two Protocols:
  - `DocumentRepository`:
    - `async add(doc: Document) -> None`
    - `async get(id: UUID) -> Document | None`
    - `async find_by_hash(content_hash: str) -> Document | None`
    - `async find_by_url(url: str) -> Document | None`
    - `async list() -> list[Document]` (newest first)
    - `async delete(id: UUID) -> bool`
  - `FileStorage`:
    - `async save(key: str, data: bytes) -> None`
    - `async delete(key: str) -> None` (no error if the key is missing)
- Produces, in `fontes.application.documents`:
  - `class DocumentNotFoundError(Exception)`, `class EmptyFileError(DocumentError)`, `class FileTooLargeError(DocumentError)`.
  - `@dataclass(frozen=True) class AddResult` with the fields `document: Document` and `created: bool`.
  - `class DocumentService` with:
    - `__init__(self, repo: DocumentRepository, storage: FileStorage, max_upload_bytes: int, clock: Callable[[], datetime] = lambda: datetime.now(UTC))`
    - `async upload(filename: str, data: bytes) -> AddResult`
    - `async add_url(url: str) -> AddResult`
    - `async list() -> list[Document]`
    - `async delete(id: UUID) -> None`, which raises `DocumentNotFoundError`
- Produces, in `tests/fakes.py`: `InMemoryDocumentRepository` and `InMemoryFileStorage`. The storage exposes `files: dict[str, bytes]`. Both are reused by Task 4.

- [ ] **Step 1: Write the failing tests.** Each one builds `DocumentService(InMemoryDocumentRepository(), InMemoryFileStorage(), max_upload_bytes=100, clock=lambda: T0)`.

  ```python
  async def test_upload_stores_file_and_queues_document():
      r = await svc.upload("a.pdf", b"%PDF-1")
      assert r.created and r.document.status == DocumentStatus.QUEUED
      assert storage.files[r.document.storage_key] == b"%PDF-1"
      assert await repo.get(r.document.id) == r.document
      assert r.document.content_hash == hashlib.sha256(b"%PDF-1").hexdigest()

  async def test_upload_duplicate_returns_existing():
      first = await svc.upload("a.pdf", b"same"); second = await svc.upload("b.pdf", b"same")
      assert not second.created and second.document.id == first.document.id
      assert len(storage.files) == 1 and len(await repo.list()) == 1

  async def test_upload_rejects_empty(): with pytest.raises(EmptyFileError): await svc.upload("a.pdf", b"")
  async def test_upload_rejects_too_large(): with pytest.raises(FileTooLargeError): await svc.upload("a.pdf", b"x" * 101)
  async def test_upload_rejects_unsupported_before_storing():
      with pytest.raises(UnsupportedSourceError): await svc.upload("a.docx", b"x")
      assert storage.files == {}

  async def test_add_url_and_duplicate():
      a = await svc.add_url("https://e.com/x"); b = await svc.add_url(" https://e.com/x ")
      assert a.created and not b.created and a.document.id == b.document.id

  async def test_list_newest_first(): ...   # two docs with clock T0 then T1 → [second, first]

  async def test_delete_removes_row_and_file():
      r = await svc.upload("a.pdf", b"x"); await svc.delete(r.document.id)
      assert await repo.get(r.document.id) is None and storage.files == {}

  async def test_delete_tolerates_missing_file():
      r = await svc.upload("a.pdf", b"x"); storage.files.clear()
      await svc.delete(r.document.id)          # no exception

  async def test_delete_unknown_raises(): with pytest.raises(DocumentNotFoundError): await svc.delete(uuid4())
  ```

  Extend `tests/test_layering.py` with two tests. Both forbid `fontes.*` imports by prefix, using the existing `ast` walker:

  ```python
  def test_inner_layers_do_not_import_outer_layers():   # domain/, application/ must not import fontes.adapters, fontes.api, fontes.container, fontes.main
  def test_api_does_not_import_adapters():              # api/ must not import fontes.adapters, fontes.container
  ```

  Prove each new layering test can fail by temporarily adding a forbidden import, then remove it.

- [ ] **Step 2: Run them.** `uv run pytest tests/application -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement the ports, the service and the fakes.**
  - Order of work in `upload`:
    1. Validate the size.
    2. Detect the source type, via `Document.from_upload`.
    3. Compute the hash and check for a duplicate.
    4. Save the file.
    5. Add the row.
  - If `repo.add` raises, delete the saved file and re-raise, so no orphan file is left behind.
  - `delete` removes the row first, then the file.
- [ ] **Step 4: Verify.** Run `uv run pytest -v`, then ruff and mypy. Expected: all pass, including the layering test.
- [ ] **Step 5: Commit and push.** Message: `Add DocumentService with repository and storage ports`.

### Task 3: Postgres repository and Alembic

**Files:**
- Modify: `backend/pyproject.toml` (add `alembic`).
- Create:
  - `backend/alembic.ini`
  - `backend/alembic/env.py`
  - `backend/alembic/script.py.mako`
  - `backend/alembic/versions/0001_documents.py`
  - `backend/fontes/adapters/persistence/models.py`
  - `backend/fontes/adapters/persistence/documents.py`
  - `backend/tests/integration/conftest.py`
  - `backend/tests/integration/test_document_repository.py`

**Interfaces:**
- Consumes: the `DocumentRepository` port and `Document`.
- Produces:
  - `fontes.adapters.persistence.models.Base` (a `DeclarativeBase`) and `DocumentRow`, which maps the table `documents`.
  - `fontes.adapters.persistence.documents.SqlDocumentRepository(session_factory: async_sessionmaker[AsyncSession])`.
- Produces the table `documents`:
  - `id uuid pk`
  - `title text not null`
  - `source_type text not null`
  - `status text not null`
  - `storage_key text null`
  - `content_hash text null`
  - `url text null`
  - `error text null`
  - `attempts int not null default 0`
  - `created_at timestamptz not null`
  - The unique partial indexes `uq_documents_content_hash` (where `content_hash is not null`) and `uq_documents_url` (where `url is not null`), plus the index `ix_documents_created_at`.
- `alembic/env.py` reads the database URL from `fontes.config.get_settings().database_url` and runs migrations through the async engine (`connection.run_sync`). Run it as `uv run alembic upgrade head` from `backend/`.

- [ ] **Step 1: Write the failing integration tests.**
  - `conftest.py` provides a session-scoped fixture that runs `alembic upgrade head`, either via `alembic.command.upgrade` in a thread or via subprocess.
  - It also provides a function-scoped `repo` fixture that runs `TRUNCATE documents` before each test.

  ```python
  async def test_add_and_get_roundtrip(repo): d = Document.from_upload("a.pdf", "h1", now=T0); await repo.add(d); assert await repo.get(d.id) == d
  async def test_find_by_hash_and_url(repo): ...   # returns the doc / None for unknown
  async def test_list_newest_first(repo): ...
  async def test_delete_returns_false_for_unknown(repo): assert await repo.delete(uuid4()) is False
  async def test_duplicate_hash_violates_unique_index(repo):
      await repo.add(Document.from_upload("a.pdf", "same", now=T0))
      with pytest.raises(IntegrityError): await repo.add(Document.from_upload("b.pdf", "same", now=T0))
  async def test_created_at_is_timezone_aware(repo): ...   # get(...).created_at.tzinfo is not None
  ```

- [ ] **Step 2: Run them.** Start the dependencies with `docker compose up -d postgres`, then run `uv run pytest -m integration tests/integration/test_document_repository.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement the models, the migration `0001_documents` and the repository.** Convert between `DocumentRow` and `Document` inside the repository, so that the domain never sees ORM objects.
- [ ] **Step 4: Verify.**
  - `uv run pytest -m "integration or not integration" -v`: all pass.
  - `uv run alembic downgrade base && uv run alembic upgrade head`: both succeed.
  - ruff and mypy: clean.
- [ ] **Step 5: Commit and push.** Message: `Add Postgres document repository and first migration`.

### Task 4: Documents API

**Files:**
- Modify:
  - `backend/pyproject.toml` (add `python-multipart`)
  - `backend/fontes/api/app.py`
  - `backend/tests/api/test_health.py` (new `create_app` signature)
- Create:
  - `backend/fontes/api/documents.py`
  - `backend/fontes/api/schemas.py`
  - `backend/tests/api/test_documents.py`

**Interfaces:**
- Consumes: `DocumentService`, `AddResult`, the errors from Tasks 1–2, and the fakes from `tests/fakes.py`.
- Produces `create_app(checks: Sequence[HealthCheck], health_timeout: float, documents: DocumentService, max_upload_bytes: int, lifespan: Lifespan | None = None) -> FastAPI`.
- Produces the endpoints:
  - `POST /documents`: multipart field `file`. Returns 201 for a new document, 200 for a duplicate, 400 for an empty file, 413 for a file that is too large, 415 for an unsupported type.
  - `POST /documents/url`: JSON `{"url": str}`. Returns 201 for a new document, 200 for a duplicate, 422 for an invalid URL.
  - `GET /documents`: 200 with a list.
  - `DELETE /documents/{id}`: 204, or 404 for an unknown id.
- Produces the response model `DocumentOut`: `id: UUID`, `title: str`, `source_type: str`, `status: str`, `url: str | None`, `error: str | None`, `attempts: int`, `created_at: datetime`.
- Every error body is `{"detail": "<human-readable message>"}`.

- [ ] **Step 1: Write the failing tests.**
  - The tests use the real `DocumentService` over the in-memory fakes, with `max_upload_bytes=100`.
  - They call the API through `httpx.AsyncClient(transport=ASGITransport(app))`.

  ```python
  async def test_upload_returns_201_and_lists(): ...      # POST file a.pdf → 201, body.status == "queued"; GET /documents → [that doc]
  async def test_upload_duplicate_returns_200(): ...      # same bytes twice → 201 then 200, same id
  async def test_upload_empty_returns_400(): ...
  async def test_upload_too_large_returns_413(): ...      # 101 bytes → 413
  async def test_upload_unsupported_returns_415(): ...    # a.docx
  async def test_upload_with_path_in_filename_is_stored_safely():
      r = await c.post("/documents", files={"file": ("../../evil.pdf", b"x", "application/pdf")})
      assert r.status_code == 201 and r.json()["title"] == "evil.pdf"
      assert list(storage.files) == [f'{r.json()["id"]}.pdf']
  async def test_add_url_201_then_200(): ...
  async def test_add_url_invalid_returns_422(): ...       # "ftp://x"
  async def test_delete_204_then_404(): ...
  ```

  Update the `test_health.py` helper to pass a `DocumentService` over the fakes.

- [ ] **Step 2: Run them.** `uv run pytest tests/api -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement the routers.**
  - Read the upload with `await file.read(max_upload_bytes + 1)`. If the length is over the limit, return 413 straight away, so the rest of the stream is never read.
  - Map the domain and application errors to HTTP status codes in one place, with exception handlers in `app.py`.
- [ ] **Step 4: Verify.** Run `uv run pytest -v`, then ruff and mypy. Expected: all pass.
- [ ] **Step 5: Commit and push.** Message: `Add documents API`.

### Task 5: Wiring, local storage, migrations on startup

**Files:**
- Create:
  - `backend/fontes/adapters/storage/__init__.py`
  - `backend/fontes/adapters/storage/local.py`
  - `backend/tests/adapters/__init__.py`
  - `backend/tests/adapters/test_local_storage.py`
- Modify:
  - `backend/fontes/config.py` (add `storage_dir: Path = Path("./data/uploads")` and `max_upload_bytes: int = 20 * 1024 * 1024`)
  - `backend/fontes/container.py`
  - `backend/Dockerfile` (copy `alembic/` and `alembic.ini`)
  - `docker-compose.yml`
  - `README.md`

**Interfaces:**
- Produces `LocalFileStorage(root: Path)`, which implements `FileStorage`:
  - it creates `root` lazily on the first save;
  - it rejects any key containing `/`, `\` or `..` by raising `ValueError`;
  - it runs blocking file I/O through `asyncio.to_thread`.
- `build_app(settings)` wires the following:
  - `async_sessionmaker(engine, expire_on_commit=False)`
  - `SqlDocumentRepository`
  - `LocalFileStorage(settings.storage_dir)`
  - `DocumentService(..., max_upload_bytes=settings.max_upload_bytes)`
- Compose changes:
  - A new one-shot service `migrate` uses the same image as `api` and runs `alembic upgrade head`. It depends on `postgres` being healthy.
  - `api` gets `depends_on: migrate: condition: service_completed_successfully`, `STORAGE_DIR=/data/uploads` and a named volume `uploads:/data/uploads`.

- [ ] **Step 1: Write the failing tests.**
  - `test_save_and_delete(tmp_path)`
  - `test_delete_missing_is_noop(tmp_path)`
  - `test_rejects_path_traversal_keys(tmp_path)` covers `"../x"`, `"a/b"` and `"a\\b"`.
  - `test_creates_root_lazily(tmp_path)` uses `tmp_path / "nested"`.
- [ ] **Step 2: Run them.** `uv run pytest tests/adapters -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement `LocalFileStorage`, the config fields, the container wiring, the Dockerfile and the compose changes.**
  - The Dockerfile must create `/data/uploads` owned by the `fontes` user before `USER fontes`. Otherwise the named volume mounts as root and saves fail.
  - The existing `tests/test_wiring.py` must still pass, because `build_app` opens no connections.
- [ ] **Step 4: Verify end to end.**
  1. `docker compose up -d --build`. `docker compose ps` shows `migrate` exited with 0 and `api` running.
  2. `curl -F file=@README.md;filename=readme.md localhost:8000/documents` returns 201 with `"status":"queued"`.
  3. Repeat the upload: it returns 200 with the same id.
  4. `curl localhost:8000/documents` lists it.
  5. `curl -X DELETE localhost:8000/documents/<id>` returns 204.
  6. Run the full suite `uv run pytest -m "integration or not integration"`, then ruff and mypy: all pass.
- [ ] **Step 5: Update the README.** Add a short "API" section with the four endpoints and curl examples.
- [ ] **Step 6: Commit and push.** Message: `Wire documents into the app and run migrations on startup`. Then watch CI: `gh run watch` must be green.
