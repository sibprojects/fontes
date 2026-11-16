# M7 Claude Provider and README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude becomes an optional LLM provider, switched on by configuration alone. The README is portfolio-ready, with an architecture diagram, a "Switch to Claude" section and screenshots.

**Architecture:**
- **Adapter.** A second `LLMProvider` adapter, `ClaudeLLM`, lives next to `OllamaLLM` in `fontes/adapters/llm/`. It streams through the official `anthropic` SDK. Only the adapter imports `anthropic`.
- **Choosing the provider.** `build_llm(settings)` in the composition root picks the adapter from `LLM_PROVIDER`.
- **Configuration checks.** `Settings` rejects `LLM_PROVIDER=claude` without a key at startup, so the api never starts half-configured.
- **Embeddings** stay on Ollama (`bge-m3`) whichever chat provider is chosen.
- **Screenshots** come from a small Playwright script run against the compose stack. It uses fictional sample documents committed under `docs/samples/`.

**Tech Stack:**
- `anthropic` 2.9 (built on `httpx2`; it sends API version `2026-10-21`, which rejects `temperature`);
- Claude Opus 5.5 (`claude-opus-5-5`) with server-side refusal fallback;
- Playwright (`playwright` npm package, Chromium) for screenshots only;
- Mermaid in the README (GitHub renders it).

**Spec:** `docs/superpowers/specs/2026-11-03-fontes-design.md` (Goals; LLM provider; Quality bar → README; Open questions → default Claude model)

## Global Constraints

- "The LLM provider is chosen by configuration. `LLM_PROVIDER=ollama` is the default. `LLM_PROVIDER=claude` also needs `ANTHROPIC_API_KEY`. Switching providers needs no code change."
- "Tests must not need Ollama or Claude." Adapter tests use `httpx2.MockTransport` through the SDK's `http_client` argument. No test makes a network call.
- Layer rule: `fontes/domain` and `fontes/application` must not import `anthropic` (already enforced by `tests/test_layering.py`).
- README: "what the project is and why, an architecture diagram, how to run it, how to switch to Claude, a short **"Why not Celery"** section, and screenshots." The Celery section already exists; keep it.
- Default Claude model `claude-opus-5-5`, configurable via `CLAUDE_MODEL`. No `temperature` is sent to Claude: API version 2026-10-21 rejects it, and Opus 5.5 always thinks, so `thinking` is not sent either.
- `mypy --strict`, ruff, a test first for every change. Commits show only the user's account and carry no AI attribution trailer.
- Screenshots and samples show only fictional generated documents, never the owner's files.

## Review Focus

1. **Wrong or missing key.** A 401 must reach the UI as an `error` event that names `ANTHROPIC_API_KEY`, not as a stack trace or a bare `AuthenticationError`. Test: `test_claude_llm.py::test_401_names_the_key` (Task 1).
2. **Overloaded or rate-limited API (429/529, including an `error` event mid-stream).** After the SDK's own retries, the user sees the HTTP status and Claude's message. Test: `test_status_error_carries_status_and_message` and `test_error_event_mid_stream` (Task 1).
3. **Refusal or cut-off answer.** `stop_reason` `refusal` or `max_tokens` must end as an error, never a stored answer built from partial text. Tests: `test_refusal_is_an_error` and `test_max_tokens_is_an_error` (Task 1).
4. **Compose with `LLM_PROVIDER=claude` and no key.** Compose passes `ANTHROPIC_API_KEY` as an empty string. The api must fail at startup with a message that names the variable, not at the first question. Test: `test_config.py::test_claude_needs_a_key` (Task 2).
5. **A question with no clear language** (only numbers or names, as in the smoke test). The answer must come back in the language of the sources, not in Chinese. Test: `test_prompting.py::test_unclear_language_falls_back_to_the_sources` (Task 3), plus the live smoke check.

---

### Task 1: `ClaudeLLM` adapter

**Files:**
- Modify: `backend/pyproject.toml`, `backend/uv.lock` (`uv add anthropic`, `uv add --dev httpx2`)
- Create: `backend/fontes/adapters/llm/claude.py`
- Test: `backend/tests/adapters/test_claude_llm.py`

**Interfaces:**
- Consumes: the `LLMProvider` protocol (`provider`, `model`, `stream(system, user) -> AsyncIterator[str]`) from `fontes/application/ports/llm.py`.
- Produces:
  ```python
  class ClaudeLLM:
      def __init__(self, api_key: str, model: str, effort: str, max_tokens: int,
                   timeout: float, max_retries: int = 2,
                   http_client: httpx2.AsyncClient | None = None) -> None
      provider -> "claude"; model -> the given model
      async def aclose(self) -> None
      async def stream(self, system: str, user: str) -> AsyncIterator[str]
  ```

The adapter builds `anthropic.AsyncAnthropic(api_key=..., timeout=..., max_retries=..., http_client=...)`. `stream` calls `client.beta.messages.stream(model=..., max_tokens=..., system=system, messages=[{"role": "user", "content": user}], output_config={"effort": effort}, betas=["server-side-fallback-2026-07-01"], fallbacks="default")`. It yields `stream.text_stream`, so thinking blocks never reach the answer. Then it checks `(await stream.get_final_message()).stop_reason`.

Errors become plain exceptions whose text the user sees in the `error` event (`api/ask.py` sends `str(exc)`). Catch in this order:

| Condition | Raised | Message |
|---|---|---|
| `anthropic.APITimeoutError` | `TimeoutError` | `"The Claude API did not answer in time ({timeout:g} s)"` |
| `anthropic.APIConnectionError` | `ConnectionError` | `"Cannot reach the Claude API: {exc}"` |
| `anthropic.AuthenticationError` | `RuntimeError` | `"The Claude API rejected ANTHROPIC_API_KEY (HTTP 401): {message}"` |
| `anthropic.APIStatusError` | `RuntimeError` | `"The Claude API returned HTTP {status}: {message}"` |
| `stop_reason == "refusal"` | `RuntimeError` | `"Claude declined to answer this question"`, plus `" ({category})"` when `stop_details.category` is set |
| `stop_reason == "max_tokens"` | `RuntimeError` | `"The answer was cut off at {max_tokens} tokens (CLAUDE_MAX_TOKENS); try a narrower question"` |

`{message}` is `body["error"]["message"]` when the body has that shape, else `exc.message`.

- [ ] **Step 1: Add the dependencies.** Run `cd backend && uv add anthropic && uv add --dev httpx2`. Expected: `anthropic` 2.x in `pyproject.toml`; `uv run python -c "import anthropic, httpx2"` succeeds.

- [ ] **Step 2: Write the failing tests.** Add a helper `_sse(*events: dict[str, object]) -> bytes` that writes `event: {type}\ndata: {json}\n\n` per event. Add `_message(*deltas: str, stop_reason: str = "end_turn", stop_details: dict | None = None)`, which builds the standard sequence `message_start`, `content_block_start` (text), one `text_delta` per piece, `content_block_stop`, `message_delta`, `message_stop`. Add `_llm(handle, max_tokens=8000)`, which builds `ClaudeLLM("k", "claude-opus-5-5", "low", max_tokens, 5.0, max_retries=0, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)))`. Tests:
  - `test_streams_text_and_sends_the_request`: the pieces come back as `["Hel", "lo [1]."]`; `provider == "claude"`, `model == "claude-opus-5-5"`. The captured request body has `system == "sys"`, `messages == [{"role": "user", "content": "user"}]`, `output_config == {"effort": "low"}`, `fallbacks == "default"` and `max_tokens == 8000`, and has no `temperature` or `thinking` key. The `anthropic-beta` header contains `server-side-fallback-2026-07-01`. The object satisfies `LLMProvider` (assign it to a `provider: LLMProvider` variable).
  - `test_thinking_is_not_part_of_the_answer`: a `thinking` block with a `thinking_delta` before the text block. Only the text pieces are yielded.
  - `test_401_names_the_key`: the response is 401 with body `{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}`. Expect `RuntimeError` matching `ANTHROPIC_API_KEY.*401.*invalid x-api-key`.
  - `test_status_error_carries_status_and_message`: a 529 `overloaded_error` with "Overloaded". Expect `RuntimeError` matching `HTTP 529: Overloaded`.
  - `test_error_event_mid_stream`: a 200 stream with one text delta, then `event: error` / `{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}`. Expect `RuntimeError` containing `Overloaded`.
  - `test_refusal_is_an_error`: `stop_reason="refusal"`, `stop_details={"type":"refusal","category":"cyber","explanation":"x"}`. Expect `RuntimeError` matching `declined.*cyber`.
  - `test_max_tokens_is_an_error`: `stop_reason="max_tokens"` with `_llm(..., max_tokens=50)`. Expect `RuntimeError` matching `cut off at 50 tokens.*CLAUDE_MAX_TOKENS`.
  - `test_unreachable_api_is_a_connection_error`: the handler raises `httpx2.ConnectError("refused")`. Expect `ConnectionError` matching `Cannot reach the Claude API`.
  - `test_timeout_is_a_timeout_error`: the handler raises `httpx2.ReadTimeout("slow")`. Expect `TimeoutError`.

- [ ] **Step 3: Run them.** Run `cd backend && uv run pytest tests/adapters/test_claude_llm.py -q`. Expected: collection fails with `ModuleNotFoundError: fontes.adapters.llm.claude`.

- [ ] **Step 4: Implement** `fontes/adapters/llm/claude.py` as in Interfaces and the table, with a module docstring that names the fallback beta and why no `temperature` is sent.

- [ ] **Step 5: Full backend check.** Run `cd backend && uv run pytest -q -m "integration or not integration" && uv run ruff check . && uv run ruff format --check . && uv run mypy --strict fontes tests alembic`. Expected: all pass, 339 tests.

- [ ] **Step 6: Commit**
  ```bash
  git add backend/pyproject.toml backend/uv.lock backend/fontes/adapters/llm/claude.py backend/tests/adapters/test_claude_llm.py
  git commit -m "Add the Claude LLM adapter"
  ```

### Task 2: Choose the provider by configuration

**Files:**
- Modify: `backend/fontes/config.py`, `backend/fontes/container.py`, `backend/.env.example`, `docker-compose.yml` (api environment), `README.md`
- Test: `backend/tests/test_config.py`, `backend/tests/test_wiring.py`, `backend/tests/test_compose.py`

**Interfaces:**
- Consumes: `ClaudeLLM` (Task 1) and `OllamaLLM`.
- Produces:
  - Settings fields:
    - `llm_provider: Literal["ollama", "claude"] = "ollama"`;
    - `anthropic_api_key: SecretStr | None = None`;
    - `claude_model: str = "claude-opus-5-5"`;
    - `claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"`;
    - `claude_max_tokens: int = 8000`.
  - An `@model_validator(mode="after")`: when `llm_provider == "claude"` and the key is missing or blank, it raises `ValueError("LLM_PROVIDER=claude needs ANTHROPIC_API_KEY")`.
  - `build_llm(settings: Settings) -> OllamaLLM | ClaudeLLM` in `container.py`. `build_app` uses it when no `llm` is passed and closes it on shutdown, as it does today. Claude uses `llm_timeout_seconds` for its timeout. `LLM_MAX_TOKENS`, `LLM_NUM_CTX` and `LLM_TEMPERATURE` stay Ollama-only, because with Claude `max_tokens` also counts thinking.

- [ ] **Step 1: Write the failing tests**
  - `test_config.py::test_provider_defaults_to_ollama`: `Settings().llm_provider == "ollama"` and `claude_model == "claude-opus-5-5"`.
  - `test_config.py::test_claude_needs_a_key`: `pytest.raises(ValidationError, match="ANTHROPIC_API_KEY")` for both `Settings(llm_provider="claude")` and `Settings(llm_provider="claude", anthropic_api_key="  ")`.
  - `test_config.py::test_claude_with_a_key`: `Settings(llm_provider="claude", anthropic_api_key="k").anthropic_api_key.get_secret_value() == "k"`. Its `repr` does not contain `"k'"`.
  - `test_wiring.py::test_build_llm_picks_the_provider`: `build_llm(Settings())` gives `provider == "ollama"`. `build_llm(Settings(llm_provider="claude", anthropic_api_key="k", claude_model="claude-sonnet-5-5"))` is a `ClaudeLLM` with `model == "claude-sonnet-5-5"`. Close both.
  - `test_compose.py::test_api_passes_the_provider_settings`: the api service environment contains `LLM_PROVIDER: ${LLM_PROVIDER:-ollama}`, `ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}`, `CLAUDE_MODEL: ${CLAUDE_MODEL:-claude-opus-5-5}`, `CLAUDE_EFFORT: ${CLAUDE_EFFORT:-low}` and `CLAUDE_MAX_TOKENS: ${CLAUDE_MAX_TOKENS:-8000}`.

  Isolate the config tests from the developer's `.env` and environment, the way the existing tests in `test_config.py` do.

- [ ] **Step 2: Run them.** Run `cd backend && uv run pytest tests/test_config.py tests/test_wiring.py tests/test_compose.py -q`. Expected: the 5 new tests FAIL (unknown field / `ImportError: build_llm` / missing compose lines).

- [ ] **Step 3: Implement** the settings, the validator, `build_llm` and the compose lines. Add commented `LLM_PROVIDER` and `ANTHROPIC_API_KEY` lines to `backend/.env.example`. In README, add a section `## Switch to Claude` after "Ask". It holds:
  - the two commands (`export LLM_PROVIDER=claude ANTHROPIC_API_KEY=sk-ant-…` and `docker compose up -d api`, or a `.env` next to `docker-compose.yml`);
  - a table of the `CLAUDE_*` settings with defaults;
  - that embeddings stay local on Ollama;
  - that with Claude the question and the retrieved excerpts are sent to Anthropic's API;
  - that the history records `provider` and `model` for each answer;
  - that a refused question falls back server-side to another Claude model (`fallbacks: "default"`).

  Change "Ollama (local LLM) or Claude" in the intro only if its wording no longer matches.

- [ ] **Step 4: Full backend check** (as in Task 1, Step 5). Expected: all pass, 344 tests.

- [ ] **Step 5: Live check, only if a key is already in the environment.** Run `LLM_PROVIDER=claude docker compose up -d --wait api`, ask one question in the UI, check that `GET /questions/{id}` shows `"provider": "claude"`, then restore with `docker compose up -d --wait api`. Never ask the owner to paste a key into the chat. Without a key, record the skip in the ledger.

- [ ] **Step 6: Commit**
  ```bash
  git add backend/fontes/config.py backend/fontes/container.py backend/.env.example backend/tests docker-compose.yml README.md
  git commit -m "Choose the LLM provider with LLM_PROVIDER; Claude needs ANTHROPIC_API_KEY"
  ```

### Task 3: Answer language when the question has none

**Files:**
- Modify: `backend/fontes/application/prompting.py`
- Test: `backend/tests/application/test_prompting.py`

**Interfaces:** none change. `SYSTEM` gets one more rule.

- [ ] **Step 1: Write the failing test**
  ```python
  def test_unclear_language_falls_back_to_the_sources() -> None:
      system = build_prompt("Q", []).system
      assert "Answer in the language of the question." in system
      assert "If the question has no clear language (only names, numbers or codes), answer in the language of the sources." in system
  ```

- [ ] **Step 2: Run it.** Run `cd backend && uv run pytest tests/application/test_prompting.py -q`. Expected: FAIL on the second assert.

- [ ] **Step 3: Implement.** Add that sentence as a rule right after "Answer in the language of the question."

- [ ] **Step 4: Full backend check.** Expected: all pass, 345 tests.

- [ ] **Step 5: Live check.** Rebuild with `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build --wait api worker frontend`, then run `bash scripts/smoke.sh` 3 times. Expected: every verdict's paragraph text has no CJK characters. Check with `grep -P '[\x{4e00}-\x{9fff}]'` on the saved output. If it still slips, record the measured rate in the ledger as a ruling; do not tune further in this task.

- [ ] **Step 6: Commit**
  ```bash
  git add backend/fontes/application/prompting.py backend/tests/application/test_prompting.py
  git commit -m "Answer in the sources' language when the question has none"
  ```

### Task 4: README architecture diagram, samples and screenshots

**Files:**
- Create:
  - `docs/samples/lumen-kettle.md` and `docs/samples/sad-pravila.md` (the fictional test documents from M5/M6; the second shows Cyrillic);
  - `frontend/scripts/screenshots.mjs`;
  - `docs/screenshots/documents.png`, `docs/screenshots/ask.png`, `docs/screenshots/history.png`.
- Modify: `frontend/package.json` and `package-lock.json` (`playwright` devDependency, script `"screenshots": "node scripts/screenshots.mjs"`), `README.md`
- Test: `backend/tests/test_readme.py`

**Interfaces:** none. `screenshots.mjs` takes an optional base URL argument (default `http://localhost:28080`) and talks only to `/api/*` and the UI. In order, it:
1. uploads each `docs/samples/*.md` through `POST /api/documents` unless a document with that title is already listed;
2. polls until all are `ready` (60 s limit, else exit 1);
3. at 1280×800, saves `documents.png` of the Documents tab;
4. asks "How do I descale the kettle?" on the Ask tab, waits until the `verifying…` label is gone, opens the first `<details>` source, and saves `ask.png`;
5. selects the newest history entry and saves `history.png` at 390×844 (phone width).

- [ ] **Step 1: Write the failing test**
  ```python
  README = Path(__file__).resolve().parents[2] / "README.md"

  def test_readme_links_point_at_files() -> None:
      text = README.read_text(encoding="utf-8")
      targets = re.findall(r"\]\(((?!https?://|#)[^)\s]+)\)", text)
      assert any(t.startswith("docs/screenshots/") for t in targets)
      missing = [t for t in targets if not (README.parent / t).exists()]
      assert missing == []

  def test_readme_has_the_architecture_diagram() -> None:
      text = README.read_text(encoding="utf-8")
      assert "```mermaid" in text
      for node in ("nginx", "api", "worker", "RabbitMQ", "Postgres", "Ollama", "Claude"):
          assert node in text.split("```mermaid", 1)[1].split("```", 1)[0]
      assert "Work in progress" not in text
  ```

- [ ] **Step 2: Run it.** Run `cd backend && uv run pytest tests/test_readme.py -q`. Expected: both FAIL (no screenshot links; no mermaid block).

- [ ] **Step 3: Implement the script.** Run `cd frontend && npm i -D playwright` and add the script. Then run `npx playwright install chromium` once, and `npm run screenshots` against the running stack. Expected: three PNGs in `docs/screenshots/`, each under 400 KB. Look at each one before committing. Run `npm run lint` and `npm test`; both must still pass, and oxlint must accept the `.mjs`.

- [ ] **Step 4: README.**
  - Replace "🚧 Work in progress." with a screenshot (`ask.png`) right under the intro.
  - Add `## Architecture` before "Run locally", holding:
    - a `mermaid` flowchart: browser → nginx (frontend) → api; api → Postgres+pgvector; api → RabbitMQ → worker; worker → Postgres; worker and api → Ollama (embeddings); api → Ollama or Claude (chat), with a dashed edge for Claude;
    - one paragraph each on the ingest path and the ask path.
  - Add `## Screenshots` with `documents.png` and `history.png` and one caption line each.
  - Mention `docs/samples/` in "Run locally" as documents to try.
  - In Development, add `npm run screenshots` with the one-time `npx playwright install chromium`.

- [ ] **Step 5: Checks.** Run the full backend check (expected: 347 tests). Then run `cd frontend && npm run lint && npm test && npm run build`. Expected: all pass.

- [ ] **Step 6: Commit**
  ```bash
  git add docs/samples docs/screenshots frontend/scripts frontend/package.json frontend/package-lock.json backend/tests/test_readme.py README.md
  git commit -m "README: architecture diagram, screenshots and sample documents"
  ```
