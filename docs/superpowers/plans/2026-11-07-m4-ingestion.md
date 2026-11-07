# M4 — Ingestion Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Real documents end up as searchable chunks. The worker loads each document (PDF, Markdown, HTML file, or URL), splits it into chunks that keep their location (page, or section heading, or position), embeds the chunks with Ollama, and stores them with their vectors in pgvector. This replaces M3's stub processor. `GET /documents/{id}/chunks` shows the result.

**Architecture:**
- **Domain:** `Segment` (loaded text plus where it came from) and `Chunk` (a stored piece, with `location_label`).
- **Application:**
  - a pure `Chunker`;
  - an `IngestionPipeline` that implements M3's `DocumentProcessor` port: it runs load, then chunk, then embed, then store;
  - new ports `DocumentLoader`, `Embedder` and `ChunkRepository`.
- **Adapters:**
  - `adapters/loaders/`: parsers for Markdown, HTML and PDF, a stored-file loader, and a URL loader with an SSRF guard;
  - `adapters/embeddings/ollama.py`: Ollama's HTTP API, called via httpx;
  - `adapters/persistence/chunks.py`: pgvector storage.
- **Errors:** every adapter maps its failures to the M3 rule. Anything that can never succeed raises `PermanentIngestionError`; everything else propagates and is retried.

**Tech Stack:** M3 stack, plus:
- `pypdf` for PDFs;
- `beautifulsoup4` with the stdlib `html.parser` (no lxml);
- `httpx`, moved from dev to the main dependencies;
- `pgvector` for the SQLAlchemy `Vector` type;
- the `ollama/ollama` image in compose.

**Spec:** `docs/superpowers/specs/2026-11-03-fontes-design.md`. The relevant sections are "Ingestion flow", "Citations" and "Calls made by the designer" (permanent vs transient errors, delete during ingestion, chunks crossing PDF pages, changing the embedding model). Previous milestone: `docs/superpowers/plans/2026-11-06-m3-messaging.md`.

## Global Constraints

- All M1–M3 Global Constraints still hold:
  - Python 3.12, `mypy --strict`, ruff, and the layering test;
  - integration tests are marked `integration`;
  - LF line endings;
  - commit and push per task;
  - **no co-author or AI attribution trailers**.
- The domain and application layers must not import httpx, pypdf, bs4, pgvector or sqlalchemy. Add `pypdf`, `bs4` and `pgvector` to `FORBIDDEN` in `tests/test_layering.py`; `httpx` is already there.
- "Tests must not need Ollama or Claude. Use a fake … `Embedder`."
- "Embeddings come from Ollama … The default is a multilingual embedding model such as `bge-m3` … The vector dimension follows from the model and is set in config and in the migration."
- "**PDF:** the page number." "A chunk that still spans two pages cites the page range, for example 'pp. 4–5'." "Chunking prefers page boundaries."
- "**Markdown, HTML, and URL:** … the location is the nearest preceding heading (the section title). When there is no heading, use the chunk's position in the document, for example 'part 3 of 12'."
- "A partial earlier attempt must not leave duplicate chunks." "Deleting a document removes its row and its chunks." "If the document disappears mid-processing, the worker discards its results."
- Permanent errors are not retried: "a corrupt or unparsable file, an unsupported content type, an HTTP 4xx when fetching a URL". Only transient errors are retried: "network, database, and Ollama unavailable".
- Non-goals: DOCX, scanned PDFs, OCR. A scanned PDF must fail with a clear message, not hang or retry.
- "Changing the model means a new migration and re-embedding everything. The README documents this, and no re-index tool is built for now."
- "The first startup pulls the Ollama models. The README must say that this takes a while and roughly how much disk space it needs."

## Decisions for this milestone (designer's calls; the spec leaves them to the builder)

- **Embedding model:** `bge-m3`, dimension **1024**, about 1.2 GB on disk.
  - Settings: `OLLAMA_URL` (default `http://localhost:11434`), `EMBEDDING_MODEL` (`bge-m3`), `EMBEDDING_DIMENSION` (1024), `EMBED_BATCH_SIZE` (16), `OLLAMA_TIMEOUT_SECONDS` (120.0).
  - The adapter calls `POST {OLLAMA_URL}/api/embed` with `{"model": ..., "input": [...]}` and reads `{"embeddings": [[...], ...]}`.
  - We call the API with httpx directly, without the `ollama` SDK: the API is one endpoint, and this keeps the dependency list short.
- **Chunk sizes are in characters,** so no tokenizer dependency is needed.
  - Settings: `CHUNK_MAX_CHARS` 1500 (about 400 tokens), `CHUNK_OVERLAP_CHARS` 200, `CHUNK_MIN_CHARS` 300.
  - Top-k and the relevance threshold belong to M5.
- **Chunking rules** (Task 1 owns them):
  1. Normalize each segment's text, then drop empty segments. Normalizing means:
     - remove NUL and other control characters except `\n` and `\t`;
     - turn `\r\n` and `\r` into `\n`;
     - collapse runs of spaces or tabs into one space;
     - collapse three or more newlines into two;
     - strip.
  2. Group consecutive segments by location key `(page, section)`. A key change starts a new group, **unless the current group is shorter than `min_chars`**. A short group absorbs the next segment instead. This is how a chunk comes to span pages ("pp. 4–5"). A group keeps the section of its first segment.
  3. Join a group's segments with `"\n\n"`. If the result fits `max_chars`, it is one chunk. Otherwise split it into pieces of at most `max_chars`. Each cut goes at the last `"\n\n"` in the window if that point is past half the window. Failing that, it goes after the last sentence end (`. `, `! `, `? `). Failing that, at the last whitespace. Failing all of these, it is a hard cut.
  4. The next piece starts `overlap_chars` before the cut, moved forward to the next whitespace so that no piece starts mid-word. The start must always advance.
  5. A piece's `page_start` and `page_end` are the min and max page of the segments its character range overlaps.
  6. Ordinals run from 0 to n−1 across the whole document.
- **Location label** (`Chunk.location_label(total)`):
  - `"p. 4"`, or `"pp. 4–5"` with an en dash;
  - otherwise the section title;
  - otherwise `"part {ordinal+1} of {total}"`.
- **Loaders:**
  - **Markdown:** ATX headings (`#` to `######`) only. Headings inside fenced code are ignored. Leading YAML front matter is dropped. The heading line, minus its `#` marks, starts its section's text. Input must be UTF-8 (a BOM is allowed); anything else is a permanent error.
  - **HTML:** BeautifulSoup decodes the bytes, which honours `<meta charset>`.
    - Removed: `script`, `style`, `noscript`, `template`, `svg`, `nav`, `header`, `footer`, `aside`, `form`.
    - The root is the first `<main>`, else the first `<article>`, else `<body>`.
    - `h1` to `h6` start sections. All remaining text, including bare `<div>` text, is kept, with block elements on separate lines.
  - **PDF:** pypdf, one segment per non-empty page, with 1-based page numbers. Corrupt or password-protected files are permanent errors.
  - **Stored file missing** from storage: permanent error.
- **URL fetching:**
  - Uses httpx with `follow_redirects=False`. We follow up to 5 redirects ourselves and check every hop.
  - Every host must resolve only to global addresses (`ipaddress.ip_address(a).is_global`). Otherwise the fetch fails permanently ("Refusing to fetch a private or local address"). This closes the M2 deferred SSRF minor.
  - DNS rebinding between our check and httpx's own resolve is a known gap, accepted for a local-only app and noted in the README.
  - Status handling:
    - 2xx is OK;
    - 4xx other than 408 and 429 is permanent;
    - 408, 429 and 5xx are transient, raised as `RuntimeError("HTTP 503 from <url>")`.
  - Only `text/html` and `application/xhtml+xml` are accepted; any other content type is permanent.
  - The body is limited to `MAX_UPLOAD_BYTES`; a larger page is permanent. The timeout is `URL_FETCH_TIMEOUT_SECONDS` (20.0).
  - URL documents keep the URL as their title. M5's citations show the link anyway.
- **Chunk storage:**
  - Migration `0002_chunks` runs `CREATE EXTENSION IF NOT EXISTS vector` and creates the `chunks` table. Columns:
    - `id uuid pk`;
    - `document_id uuid not null references documents(id) on delete cascade`;
    - `ordinal int not null`, `text text not null`;
    - `page_start int null`, `page_end int null`, `section text null`;
    - `embedding vector(1024) not null`.
  - Constraints and indexes: a unique constraint on `(document_id, ordinal)`, and an HNSW index `ix_chunks_embedding` on `embedding vector_cosine_ops`.
  - The migration holds `EMBEDDING_DIMENSION = 1024`, and a test pins it equal to `Settings().embedding_dimension`.
- **Idempotent writes:** `ChunkRepository.replace` runs in one transaction:
  1. lock the document row (`SELECT … FOR UPDATE`);
  2. if the document is missing, return `False`;
  3. otherwise delete its chunks, insert the new ones, and return `True`.

  This closes the M3 deferred minor about sweep duplicates.
- **The stub goes away.** `StubDocumentProcessor` and `STUB_PROCESSING_SECONDS` are deleted.
- **Compose:**
  - an `ollama` service with an `ollama` volume, port `11434`, and the healthcheck `ollama list`;
  - a one-shot `ollama-pull` service that uses the same image with `OLLAMA_HOST=ollama:11434` and the command `pull bge-m3`;
  - `worker` depends on `ollama-pull` having completed successfully.

  The CI smoke job pulls the real model.

## Review Focus

- **PDF text containing NUL bytes.** Postgres rejects `\x00` in `text`, so without the fix such a document would fail after 3 retries with a database error. The NUL bytes must be stripped instead. Pinned in Task 1 (`test_nul_and_control_characters_removed`) and Task 2 (`test_text_with_unusual_characters_round_trips`).
- **A scanned or image-only PDF.** It must go to `failed` at once with "No text could be extracted (scanned PDFs are not supported)", with no retries. Pinned in Task 7 (`test_no_text_is_permanent`).
- **A URL that points at, or redirects to, a local or private address.** It must be refused before any request is sent to that address. Pinned in Task 6 (`test_private_address_rejected_before_any_request`, `test_redirect_to_private_address_is_refused`).
- **Ollama not running, or the model not pulled.** The error is transient, so it is retried. The stored error tells the user what to do. Pinned in Task 3 (`test_model_missing_raises_clear_error`).
- **The same document processed twice** (redelivery, a sweep duplicate, or a retry after a partial attempt). It must still end with exactly one set of chunks. Pinned in Task 2 (`test_replace_twice_leaves_only_second`) and Task 7 (`test_rerun_replaces_chunks`).

---

### Task 1: Segments, chunks and the chunker

**Files:**
- Create: `backend/fontes/domain/chunks.py`, `backend/fontes/application/chunking.py`, `backend/tests/domain/test_chunks.py`, `backend/tests/application/test_chunking.py`

**Interfaces:**
- Produces in `fontes.domain.chunks`:
  - `@dataclass(frozen=True) Segment(text: str, page: int | None = None, section: str | None = None)`
  - `@dataclass(frozen=True) Chunk(ordinal: int, text: str, page_start: int | None = None, page_end: int | None = None, section: str | None = None)` with `location_label(total: int) -> str`
- Produces in `fontes.application.chunking`: `Chunker(max_chars: int, overlap_chars: int, min_chars: int)` with `split(segments: Sequence[Segment]) -> list[Chunk]`. The constructor raises `ValueError` unless `0 <= overlap_chars < max_chars // 2` and `0 < min_chars <= max_chars`.

- [ ] **Step 1: Write the failing tests.**

  The label tests:
  ```python
  def test_label_single_page(): Chunk(0, "t", 4, 4).location_label(9) == "p. 4"
  def test_label_page_range(): Chunk(0, "t", 4, 5).location_label(9) == "pp. 4–5"
  def test_label_section(): Chunk(0, "t", section="Install").location_label(9) == "Install"
  def test_label_position(): Chunk(2, "t").location_label(12) == "part 3 of 12"
  ```

  The chunker tests use `Chunker(1500, 200, 300)` unless stated otherwise:
  ```python
  def test_short_segments_on_one_page_merge(): two 400-char segments, page 1 → one chunk, pages (1, 1)
  def test_page_boundary_starts_new_chunk(): 400 chars on p.1, 400 on p.2 → two chunks, (1,1) and (2,2)
  def test_short_page_tail_joins_next_page(): 50 chars on p.1, 400 on p.2 → one chunk, (1, 2)
  def test_section_change_starts_new_chunk(): 400 chars "A", 400 chars "B" → sections ["A", "B"]
  def test_long_text_splits_with_overlap(): 5000 chars of "Sentence n. " → every len ≤ 1500; chunks[1].text[:40] in chunks[0].text; every sentence appears in some chunk
  def test_split_prefers_paragraph_break(): paragraphs of 1000 + 1000 chars → first chunk ends exactly at the first paragraph
  def test_never_starts_or_ends_mid_word(): words of 7 letters, no punctuation → each chunk starts and ends on a whole word
  def test_word_longer_than_max_is_hard_cut(): Chunker(100, 10, 50), one 350-char word → 4 chunks, terminates
  def test_nul_and_control_characters_removed(): "a\x00b\x07c\r\nd" → text "abc\nd"
  def test_blank_segments_give_no_chunks(): [Segment("  \n "), Segment("")] → []
  def test_ordinals_are_sequential(): any multi-chunk input → [0, 1, 2, ...]
  def test_invalid_sizes_raise(): Chunker(100, 60, 50) and Chunker(100, 10, 0) → ValueError
  ```
- [ ] **Step 2: Run them.** `uv run pytest tests/domain/test_chunks.py tests/application/test_chunking.py`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** the label and the chunker, following the chunking rules under "Decisions" above.
- [ ] **Step 4: Verify.** Full suite, ruff, mypy: all pass.
- [ ] **Step 5: Commit and push.** `Add chunk model and a location-preserving chunker`.

### Task 2: Chunk storage in pgvector

**Files:**
- Create:
  - `backend/alembic/versions/0002_chunks.py`
  - `backend/fontes/application/ports/chunks.py`
  - `backend/fontes/adapters/persistence/chunks.py`
  - `backend/tests/chunk_repository_contract.py`
  - `backend/tests/integration/test_chunk_repository.py`
- Modify:
  - `backend/pyproject.toml` (add `pgvector`)
  - `backend/fontes/adapters/persistence/models.py` (`ChunkRow`)
  - `backend/fontes/config.py` (`embedding_dimension: int = 1024`)
  - `backend/tests/fakes.py` (`InMemoryChunkRepository`)
  - `backend/tests/test_fakes.py`
  - `backend/tests/integration/conftest.py` (`TRUNCATE documents CASCADE`)
  - `backend/tests/test_layering.py` (FORBIDDEN gains `pgvector`, `pypdf`, `bs4`)

**Interfaces:**
- Consumes: `Chunk` (Task 1).
- Produces a `ChunkRepository(Protocol)` in `fontes.application.ports.chunks` with two methods:
  - `async replace(document_id: UUID, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]) -> bool`. It runs the transaction described under "Idempotent writes" above. It raises `ValueError` when the lengths differ.
  - `async list_for_document(document_id: UUID) -> list[Chunk]`, ordered by ordinal.
- Produces `SqlChunkRepository(session_factory)`.
- Produces `InMemoryChunkRepository(documents: InMemoryDocumentRepository)`, which checks that the document exists in the given repo and exposes `embeddings: dict[UUID, list[list[float]]]`.

- [ ] **Step 1: Write the failing tests.**

  The contract runs on both the fake and Postgres. It follows the M3 pattern: shared module, imported with `# noqa: F401`.
  ```python
  async def test_replace_then_list_in_order(chunks, docs): 3 chunks → list == chunks, ordinals 0..2
  async def test_replace_twice_leaves_only_second(chunks, docs): replace 3, then 2 → list has the 2
  async def test_replace_for_missing_document_writes_nothing(chunks): uuid4() → False; list == []
  async def test_replace_with_mismatched_embeddings_raises(chunks, docs): 2 chunks, 1 vector → ValueError
  async def test_text_with_unusual_characters_round_trips(chunks, docs): "Глава 1 — «цитата» ✓ \t tab" survives
  ```

  Postgres only:
  ```python
  async def test_deleting_document_deletes_its_chunks(): replace, then DocumentRepository.delete → list == [], and SELECT count(*) FROM chunks == 0
  async def test_embedding_round_trips(): the stored vector equals the input (1024 floats, within float32 tolerance)
  def test_migration_dimension_matches_settings(): the migration module's EMBEDDING_DIMENSION == Settings().embedding_dimension
  ```

  The `chunks` and `docs` fixtures come from each test module. The contract inserts a document via `docs.add(Document.from_upload(...))`. The vectors are `[float(i)] * 1024`.
- [ ] **Step 2: Run them.** `uv run pytest -m "integration or not integration" tests/test_fakes.py tests/integration/test_chunk_repository.py`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** the migration, `ChunkRow` (with `pgvector.sqlalchemy.Vector(1024)`), the repository and the fake.
  - If mypy reports missing stubs for pgvector, add a `[[tool.mypy.overrides]]` with `module = ["pgvector.*"]` and `ignore_missing_imports = true`.
  - `docker compose up -d postgres` uses the `pgvector/pgvector:pg17` image, which already ships the extension.
- [ ] **Step 4: Verify.** Run `alembic upgrade head`, then `alembic downgrade 0001_documents`, then `upgrade head` again, against the dev database: all three succeed. Then run the full suite with integration tests, ruff and mypy: all pass.
- [ ] **Step 5: Commit and push.** `Store chunks with embeddings in pgvector`.

### Task 3: Ollama embedder

**Files:**
- Create: `backend/fontes/application/ports/embeddings.py`, `backend/fontes/adapters/embeddings/__init__.py`, `backend/fontes/adapters/embeddings/ollama.py`, `backend/tests/adapters/test_ollama_embedder.py`
- Modify: `backend/pyproject.toml` (move `httpx` into the main dependencies), `backend/fontes/config.py`, `backend/tests/fakes.py` (`FakeEmbedder`)

**Interfaces:**
- Produces an `Embedder(Protocol)`: `async embed(texts: Sequence[str]) -> list[list[float]]`, one vector per text, in order.
- Produces `OllamaEmbedder(base_url: str, model: str, dimension: int, batch_size: int, timeout: float, transport: httpx.AsyncBaseTransport | None = None)` with `embed` and `async aclose() -> None`.
- Produces `FakeEmbedder(dimension: int = 1024, fail: Exception | None = None)`. Its vectors are deterministic and derived from a hash of the text. It exposes `calls: list[list[str]]`, and it raises `fail` when that is set.
- Adds config: `ollama_url`, `embedding_model`, `embed_batch_size`, `ollama_timeout_seconds`, with the values listed under "Decisions".

- [ ] **Step 1: Write the failing tests.** They use `httpx.MockTransport`.
  ```python
  async def test_embeds_in_batches_preserving_order(): 5 texts, batch_size 2 → 3 POSTs to /api/embed with inputs of 2, 2, 1; the model is in the body; the result is in input order
  async def test_empty_input_makes_no_request(): embed([]) == [] and the transport is never called
  async def test_model_missing_raises_clear_error(): 404 {"error": "model \"bge-m3\" not found, try pulling it first"} → RuntimeError matching "ollama pull bge-m3"
  async def test_wrong_dimension_raises(): vectors of length 3 with dimension=1024 → RuntimeError matching "dimension"
  async def test_connection_error_is_not_permanent(): the transport raises httpx.ConnectError → httpx.ConnectError propagates (not PermanentIngestionError)
  async def test_server_error_is_not_permanent(): 500 → an exception that is not PermanentIngestionError
  ```
- [ ] **Step 2: Run them.** Expected: FAIL (ImportError).
- [ ] **Step 3: Implement.** The adapter owns one `httpx.AsyncClient(base_url, timeout, transport)`.
- [ ] **Step 4: Verify.** Full suite, ruff, mypy: all pass. Optionally, with a local Ollama that has `bge-m3` pulled, run a one-off script that embeds `["привет", "hello"]` and gets two vectors of 1024 floats. Report the result, but don't commit the script.
- [ ] **Step 5: Commit and push.** `Add Ollama embedder`.

### Task 4: Markdown and HTML loaders

**Files:**
- Create:
  - `backend/fontes/application/ports/loading.py`
  - `backend/fontes/adapters/loaders/__init__.py`
  - `backend/fontes/adapters/loaders/markdown.py`
  - `backend/fontes/adapters/loaders/html.py`
  - `backend/fontes/adapters/loaders/stored.py`
  - `backend/tests/adapters/test_markdown_loader.py`
  - `backend/tests/adapters/test_html_loader.py`
  - `backend/tests/adapters/test_stored_loader.py`
- Modify:
  - `backend/pyproject.toml` (add `beautifulsoup4`)
  - `backend/fontes/application/ports/documents.py` (`FileStorage.read`)
  - `backend/fontes/adapters/storage/local.py`
  - `backend/tests/fakes.py`
  - `backend/tests/adapters/test_local_storage.py`

**Interfaces:**
- Produces a `DocumentLoader(Protocol)`: `async load(doc: Document) -> list[Segment]`.
- Produces `FileStorage.read(key: str) -> bytes`, which raises `FileNotFoundError` when the file is absent. Both the local storage and the in-memory storage implement it.
- Produces the parsers `parse_markdown(data: bytes) -> list[Segment]` and `parse_html(data: bytes) -> list[Segment]`. They are pure and synchronous, and raise `PermanentIngestionError` on undecodable input.
- Produces `StoredFileLoader(storage: FileStorage, parse: Callable[[bytes], list[Segment]])`. It reads `doc.storage_key` and runs `parse` in `asyncio.to_thread`. A `FileNotFoundError` becomes `PermanentIngestionError("The uploaded file is missing from storage")`.

- [ ] **Step 1: Write the failing tests:**
  ```python
  # markdown
  def test_sections_follow_atx_headings(): b"intro\n# A\ntext a\n## B ##\ntext b" → [("intro", None), ("A\ntext a", "A"), ("B\ntext b", "B")]
  def test_heading_inside_fenced_code_is_ignored(): "# A\n```\n# not a heading\n```" → one segment, section "A"
  def test_front_matter_is_dropped(): "---\ntitle: x\n---\n# A\nbody" → front matter absent
  def test_bom_and_cyrillic(): "﻿# Глава\nтекст".encode() → section "Глава"
  def test_non_utf8_is_permanent(): "Глава".encode("cp1251") → PermanentIngestionError matching "UTF-8"
  # html
  def test_scripts_styles_and_navigation_removed(): their text is absent from all segments
  def test_sections_follow_headings(): <h1>A</h1><p>x</p><h2>B</h2><p>y</p> → sections ["A", "B"]
  def test_text_in_plain_divs_is_kept(): <div>bare text</div> → present
  def test_main_is_preferred_over_body(): text outside <main> is absent
  def test_meta_charset_is_honoured(): windows-1251 bytes with <meta charset="windows-1251"> → Cyrillic decoded
  def test_list_items_are_separate_lines(): <li>a</li><li>b</li> → "a\nb" inside the text
  # stored-file loader
  async def test_reads_storage_and_parses(): InMemoryFileStorage holding b"# A\nx" → segments from parse_markdown
  async def test_missing_file_is_permanent(): empty storage → PermanentIngestionError
  # local storage
  async def test_read_returns_saved_bytes(); async def test_read_missing_raises_file_not_found()
  ```
- [ ] **Step 2: Run them.** Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** the parsers, following the loader rules under "Decisions".
- [ ] **Step 4: Verify.** Full suite, ruff, mypy, and the layering test: all pass.
- [ ] **Step 5: Commit and push.** `Add Markdown and HTML loaders`.

### Task 5: PDF loader

**Files:**
- Create: `backend/fontes/adapters/loaders/pdf.py`, `backend/tests/pdf_factory.py`, `backend/tests/adapters/test_pdf_loader.py`
- Modify: `backend/pyproject.toml` (add `pypdf`)

**Interfaces:**
- Produces `parse_pdf(data: bytes) -> list[Segment]`: one segment per page whose text is non-empty, with `page = index + 1`.
- Produces the test helper `make_pdf(pages: list[str]) -> bytes` in `tests/pdf_factory.py`.
  - It writes a minimal PDF 1.4 by hand: a catalog, a pages object, and one page per string.
  - Each page has a content stream `BT /F1 12 Tf 72 720 Td (<text>) Tj ET` using the standard Helvetica font.
  - The xref offsets are computed from the bytes.
  - It handles ASCII text only; an empty string makes a blank page.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_one_segment_per_page_with_page_numbers(): make_pdf(["Alpha text", "", "Gamma text"]) → [("Alpha text", 1), ("Gamma text", 3)]
  def test_corrupt_pdf_is_permanent(): b"%PDF-1.4 garbage" → PermanentIngestionError matching "PDF"
  def test_password_protected_pdf_is_permanent(): a pypdf PdfWriter page encrypted with user_password="pw" → PermanentIngestionError matching "password"
  def test_pdf_without_text_returns_no_segments(): make_pdf(["", ""]) → []
  ```
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Parse with `pypdf.PdfReader(io.BytesIO(data))`.
  - If the file is encrypted and `decrypt("")` fails, raise "The PDF is password-protected".
  - `PdfReadError` and `ValueError` from parsing become "Could not read the PDF: …".
- [ ] **Step 4: Verify.** Full suite, ruff, mypy: all pass.
- [ ] **Step 5: Commit and push.** `Add PDF loader`.

### Task 6: URL loader with SSRF guard

**Files:**
- Create: `backend/fontes/adapters/loaders/url.py`, `backend/tests/adapters/test_url_loader.py`
- Modify: `backend/fontes/config.py` (`url_fetch_timeout_seconds: float = 20.0`)

**Interfaces:**
- Consumes `parse_html` (Task 4).
- Produces `UrlLoader(max_bytes: int, timeout: float, transport: httpx.AsyncBaseTransport | None = None, resolve: Callable[[str], Awaitable[list[str]]] | None = None)`. It implements `DocumentLoader` and fetches `doc.url`. The default `resolve` uses `loop.getaddrinfo`. A host that is a literal IP is checked without resolving.

- [ ] **Step 1: Write the failing tests.** They use `MockTransport`, and the resolver returns `["93.184.215.14"]` unless the test says otherwise.
  ```python
  async def test_fetches_and_parses_html(): 200 text/html → segments from parse_html
  async def test_private_address_rejected_before_any_request(): the resolver returns ["10.0.0.5"] → PermanentIngestionError matching "private or local"; the transport was never called
  @pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/latest"])
  async def test_literal_local_addresses_rejected(url): PermanentIngestionError
  async def test_redirect_to_private_address_is_refused(): 302 Location http://127.0.0.1/admin → PermanentIngestionError; the second request is never sent
  async def test_follows_public_redirect(): 301 → 200 → parsed
  async def test_too_many_redirects_is_permanent(): 6 redirects in a row → PermanentIngestionError
  async def test_http_404_is_permanent()
  @pytest.mark.parametrize("status", [408, 429, 503])
  async def test_retryable_status_is_transient(status): raises something that is not PermanentIngestionError, with message containing f"HTTP {status}"
  async def test_non_html_content_type_is_permanent(): application/pdf → PermanentIngestionError matching "content type"
  async def test_oversized_page_is_permanent(): max_bytes=1000, 5000-byte body → PermanentIngestionError
  async def test_network_error_is_transient(): the transport raises httpx.ConnectError → it propagates
  ```
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement**, following "URL fetching" under "Decisions". Stream the body with `client.stream` and stop once more than `max_bytes` have arrived.
- [ ] **Step 4: Verify.** Full suite, ruff, mypy: all pass.
- [ ] **Step 5: Commit and push.** `Add URL loader that refuses private addresses`.

### Task 7: IngestionPipeline

**Files:**
- Create: `backend/fontes/application/pipeline.py`, `backend/tests/application/test_pipeline.py`
- Modify: `backend/tests/fakes.py` (`FakeLoader`)

**Interfaces:**
- Consumes: `Chunker` (Task 1), `ChunkRepository` (Task 2), `Embedder` (Task 3), `DocumentLoader` (Task 4), and `DocumentProcessor` and `PermanentIngestionError` (M3).
- Produces `IngestionPipeline(loaders: Mapping[SourceType, DocumentLoader], chunker: Chunker, embedder: Embedder, chunks: ChunkRepository)`, which implements `DocumentProcessor`. Its `process(doc)` runs these steps:
  1. Pick the loader for `doc.source_type`. If none exists, raise `PermanentIngestionError("No loader for <type>")`.
  2. Load, then split with the chunker.
  3. If there are no chunks, raise `PermanentIngestionError("No text could be extracted (scanned PDFs are not supported)")`.
  4. Embed the chunk texts and call `chunks.replace`. If `replace` returns `False`, the document is gone: return quietly.
- Produces `FakeLoader(segments: list[Segment] | Exception)`.

- [ ] **Step 1: Write the failing tests:**
  ```python
  async def test_document_ends_up_as_embedded_chunks(): 2 sections → 2 stored chunks, 2 embeddings of the fake's dimension
  async def test_no_text_is_permanent(): FakeLoader([]) → PermanentIngestionError matching "No text could be extracted"
  async def test_rerun_replaces_chunks(): process twice → still 2 chunks
  async def test_deleted_document_discards_results(): document not in docs repo → returns, nothing stored
  async def test_embedder_failure_propagates_and_stores_nothing(): FakeEmbedder(fail=ConnectionError("down")) → ConnectionError; list_for_document == []
  async def test_unknown_source_type_is_permanent(): loaders={} → PermanentIngestionError
  async def test_loader_permanent_error_passes_through(): FakeLoader(PermanentIngestionError("corrupt")) → the same error
  ```
- [ ] **Step 2: Run them.** Expected: FAIL (ImportError).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify.** Full suite, ruff, mypy, layering: all pass.
- [ ] **Step 5: Commit and push.** `Add ingestion pipeline: load, chunk, embed, store`.

### Task 8: Wire the pipeline into the worker and show chunks in the API

**Files:**
- Modify:
  - `backend/fontes/container.py`
  - `backend/fontes/config.py` (chunk settings; remove `stub_processing_seconds`)
  - `backend/fontes/application/documents.py` (`list_chunks`)
  - `backend/fontes/api/documents.py`, `backend/fontes/api/schemas.py`
  - `backend/fontes/adapters/messaging/consumer.py` (catch-all)
  - `backend/tests/integration/test_worker.py`, `backend/tests/integration/test_messaging.py`
  - `backend/tests/api/test_documents.py`, `backend/tests/application/test_document_service.py`
  - all call sites of `DocumentService(...)`
- Delete: `backend/fontes/adapters/processing.py`

**Interfaces:**
- `DocumentService.__init__(repo, storage, chunks: ChunkRepository, publisher, max_upload_bytes, clock=..., publish_timeout=...)`. Here `chunks` is new, placed after `storage`.
- `DocumentService.list_chunks(id: UUID) -> list[Chunk]`, which raises `DocumentNotFoundError`.
- `GET /documents/{id}/chunks` returns `200 [{"ordinal": int, "location": str, "text": str}]`, where `location = chunk.location_label(len(chunks))`, or `404` for an unknown id.
- `build_worker(settings, processor: DocumentProcessor | None = None, embedder: Embedder | None = None) -> Worker`. By default it builds:
  - `IngestionPipeline` with the loaders `{PDF: StoredFileLoader(storage, parse_pdf), MARKDOWN: StoredFileLoader(storage, parse_markdown), HTML: StoredFileLoader(storage, parse_html), URL: UrlLoader(...)}`;
  - a `Chunker` from the settings;
  - an `OllamaEmbedder` unless one is passed in;
  - a `SqlChunkRepository`.

  The worker's close callback also closes the embedder it built.
- Config: `chunk_max_chars: int = 1500`, `chunk_overlap_chars: int = 200`, `chunk_min_chars: int = 300`.
- Consumer: any unexpected exception in `_on_message` outside the handler call is forwarded to the DLQ with its error, and the original message is acked. This closes the M3 RecursionError minor.

- [ ] **Step 1: Write the failing tests:**
  ```python
  # api (fakes)
  async def test_list_chunks_returns_locations(): chunks stored for a doc → [{"ordinal": 0, "location": "A", "text": ...}, ...]
  async def test_list_chunks_unknown_document_404()
  # integration, real Postgres + RabbitMQ, build_worker(settings, embedder=FakeEmbedder())
  async def test_markdown_upload_ends_up_as_chunks(): POST "# A\n..." "# B\n..." → ready → GET chunks → locations ["A", "B"]
  async def test_pdf_upload_cites_pages(): POST make_pdf([400 chars, 400 chars]) → ready → locations ["p. 1", "p. 2"]
  async def test_unreadable_pdf_fails_without_retry(): POST b"%PDF-1.4 garbage" as a.pdf → failed, attempts 1, error matching "Could not read the PDF"
  async def test_delete_removes_chunks(): ready doc → DELETE → no rows in chunks for it
  async def test_deeply_nested_body_goes_to_dlq(): (test_messaging) publish b"[" * 100_000 → the DLQ holds it; a following valid message is still consumed
  ```
  The existing `test_upload_goes_queued_to_ready_through_rabbitmq` and `test_worker_sweep_publishes_queued_documents` switch from the stub to `embedder=FakeEmbedder()`. The sweep test needs a stored file, so insert it via the storage too.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Delete the stub and its setting.
- [ ] **Step 4: Verify.** Full suite with integration tests, ruff and mypy: all pass. `tests/test_wiring.py` still passes, since building the app or the worker opens no connection.
- [ ] **Step 5: Commit and push.** `Run the real ingestion pipeline in the worker; list a document's chunks`.

### Task 9: Ollama in compose, CI smoke with real embeddings, README

**Files:**
- Modify: `docker-compose.yml`, `scripts/smoke.sh`, `.github/workflows/ci.yml`, `README.md`

**Interfaces:**
- Compose, as listed under "Decisions":
  - the `ollama` and `ollama-pull` services;
  - `worker` gets `OLLAMA_URL: http://ollama:11434` and depends on `ollama-pull: service_completed_successfully`;
  - a new `ollama` volume.
- `smoke.sh`:
  - the timeout becomes 180 s, because the first embedding loads the model;
  - it exits 1 at once, printing the stored error, when the status becomes `failed`;
  - after `ready`, it checks that `GET /documents/{id}/chunks` returns at least one chunk (the body contains `"ordinal":0`).

- [ ] **Step 1: Prove the smoke check fails first.** Change `smoke.sh` and run it against the current stack, before the compose change. The worker has no Ollama, so the document ends `failed` (or stays `processing` while it retries), and the script exits 1.
- [ ] **Step 2: Change compose.** `docker compose up -d --build --wait api worker`. The first run pulls `bge-m3`. Then `scripts/smoke.sh` exits 0.
- [ ] **Step 3: Check end to end by hand.**
  1. Upload a real multi-page PDF. Its chunks show `p. N` locations.
  2. Upload a Markdown file with Cyrillic headings. Its chunks show those headings.
  3. Add `https://example.com`. It becomes `ready`.
  4. Add `http://localhost:8000/health`. It becomes `failed` with "Refusing to fetch a private or local address", attempts 1.
  5. `docker compose stop ollama`, then upload a file. It retries, and after 3 attempts it is `failed` with an Ollama connection error. `docker compose start ollama`.
- [ ] **Step 4: CI.** The `compose-smoke` job runs unchanged apart from the timeout; it pulls the model through `ollama-pull`. Push and watch: both jobs green. Note the job's duration in the ledger.
- [ ] **Step 5: README.**
  - Supported formats and how each is cited: page, section, or "part N of M".
  - `GET /documents/{id}/chunks` in the API table.
  - The first `docker compose up` downloads `bge-m3` (about 1.2 GB) into the `ollama` volume, which takes a few minutes.
  - **Changing the embedding model:** set `EMBEDDING_MODEL` and `EMBEDDING_DIMENSION`, add a migration that changes the column dimension, and re-upload the documents. There is no re-index tool.
  - **Known limits:**
    - scanned PDFs are rejected;
    - URLs that resolve to private or local addresses are refused, and DNS rebinding is not defended against;
    - RabbitMQ's default 30-minute consumer timeout caps how long one document may take on CPU.
  - Remove the "stub" wording from "How ingestion works".
  - The new settings in the settings list.
- [ ] **Step 6: Commit and push.** `Run Ollama in compose; smoke-test real embeddings in CI; document ingestion formats`.
