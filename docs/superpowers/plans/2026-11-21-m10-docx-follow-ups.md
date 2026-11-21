# M10: DOCX and Follow-up Questions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest Word (.docx) files, and let a question follow up on an earlier answer ("and for green tea?") instead of always standing alone.

**Architecture:**
- **DOCX** is a fourth uploaded type, parsed with the standard library (`zipfile` + `xml.etree`). Headings become sections, the same way Markdown headings do.
- **Follow-ups.** A follow-up names the stored question it continues (`follow_up_of`). The service walks that chain back at most `ASK_FOLLOW_UP_TURNS` turns, and uses those turns twice:
  - in the text it embeds for retrieval;
  - in the prompt, as context only.

  Verification and `not_found` are unchanged: the answer must still cite the sources retrieved for this turn.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, pgvector, React + Vitest.

**Spec:** `docs/superpowers/specs/2026-11-03-fontes-design.md`. Its Non-goals rule out both features ("Conversational context…" and "DOCX, scanned PDFs, and OCR"). The user chose them as item 4 on 2026-11-19, and Task 5 updates the spec. The public demo, also in item 4, is **not** in this plan: it waits for the user's answer on why and for whom.

## Rulings made while planning (the user said "делай" without design questions)

1. **DOCX without a new dependency.**
   - **How:** `zipfile` reads `word/document.xml`, which is capped at 50 MB uncompressed (a zip bomb guard). Then `xml.etree.ElementTree` parses it; CPython's bundled expat ≥ 2.4 refuses billion-laughs expansion.
   - **Not supported:** `.doc` (the old binary format), text boxes, footnotes, headers and footers, comments.
2. **DOCX sections.**
   - A paragraph whose style id is `Title` or `Heading1`–`Heading9` (case-insensitive; also localised ids that end in a digit 1–9 and start with "heading" or "заголовок") starts a section.
   - A table becomes one line per row, with its cells joined by ` | `.
   - The location label is the section name, as for Markdown.
3. **Follow-ups are explicit.** The user presses "Follow up" under an answer. Nothing guesses whether a new question continues the last one.
4. **The retrieval text** is the earlier questions and the new one, oldest first, joined by newlines. There is no LLM query rewriting: that is a second model call per question, and the 7B model is unreliable at it.
5. **The earlier turns go into the prompt with their citation markers removed.** Their numbers referred to other sources, so in the prompt they would mislead. Each earlier answer is cut to 1500 characters. A system rule says the earlier conversation only explains what the question refers to, and facts must come from the sources.
6. **Chain depth.** `ASK_FOLLOW_UP_TURNS = 2` (the parent and its parent), configurable from 0 to 5. At 0, a follow-up is stored with its link, but the earlier turns are not used.
7. **Unknown parent.** `follow_up_of` naming an unknown question gives **422** "The earlier question was not found" before the stream starts.
8. **Storage.** The `questions` table gets a nullable `follow_up_of` column, with an FK to `questions.id` ON DELETE SET NULL. The column is stored and returned, so history shows what an answer followed up on.
9. **`not_found` follow-ups.** They are stored like any other answer. A further follow-up to one walks past it normally: its question still helps retrieval.
10. **Eval.** Cases gain an optional `after = "<case id>"`, which asks the case as a follow-up to that case's answer. If that answer is missing (the earlier case errored), the follow-up case is an error. Two follow-up cases are added (en, ru), so the set grows from 24 to 26.

## Global Constraints

- Python checks run from `backend/`: `pytest -q -m "integration or not integration"`, `ruff check .`, `ruff format --check .`, `mypy --strict fontes tests alembic`, always under `set -o pipefail`.
- Frontend checks: `npm test`, `npm run lint`, `npm run build`.
- Integration tests wipe the local stack's tables. Before any live check, delete only their leftovers (`a.pdf`, smoke and eval questions).
- Commits carry no AI attribution trailer.
- The layering test (`tests/test_layering.py`) must stay green: adapters may import application ports, never the reverse.

## Review Focus

1. **A follow-up whose parent chain contains a `not_found` answer or a long answer.** Expected: the chain is still walked, and each earlier answer goes into the prompt cut to 1500 characters, without markers.
2. **A DOCX that is not a zip, is a zip without `word/document.xml`, or expands past the cap.** Expected: a permanent ingestion failure with a readable message, never a worker crash or retry loop.
3. **A follow-up to a question from the history (not the one just asked).** Expected: it links to that one, and the UI shows which question it follows.
4. **Asking a fresh question after pressing "Follow up".** Expected: the user can cancel the follow-up chip, and a cancelled chip sends no `follow_up_of`.
5. **A cycle or very deep chain in stored data.** Expected: the walk stops after `ASK_FOLLOW_UP_TURNS` lookups whatever the data holds.

---

### Task 1: DOCX ingestion

**Files:**
- Create: `backend/fontes/adapters/loaders/docx.py`, `backend/tests/adapters/test_docx_loader.py`, `backend/tests/docx_factory.py`
- Modify: `backend/fontes/domain/documents.py` (`SourceType.DOCX = "docx"`, `".docx"` in `_EXTENSIONS`), `backend/fontes/container.py` (`SourceType.DOCX: StoredFileLoader(storage, parse_docx)`), `frontend/src/api/types.ts` (`SourceType` adds `'docx'`), `frontend/src/documents/DocumentsPage.tsx` (accept `.docx`; empty text "Upload a PDF, Word, Markdown or HTML file, or add a URL."), `README.md` (supported formats), `backend/tests/domain/test_documents.py`, `frontend/src/documents/DocumentsPage.test.tsx`

**Interfaces:**
- Produces: `parse_docx(data: bytes) -> list[Segment]`; `docx_factory.make_docx(body_xml: str) -> bytes` (a minimal valid package: `[Content_Types].xml` and `word/document.xml`, with `body_xml` placed inside `<w:body>`); `DOCX_MAX_XML_BYTES = 50 * 1024 * 1024` in `docx.py`.

- [ ] **Step 1: Write the failing tests** in `test_docx_loader.py`:
  - `test_headings_start_sections`: a `Heading1` "Setup" paragraph, then "Fill it." and "Pair it.", then `Heading2` "Care" and "Descale monthly." The result is `[Segment("Setup\nFill it.\nPair it.", section="Setup"), Segment("Care\nDescale monthly.", section="Care")]`.
  - `test_text_before_any_heading_has_no_section`: `Segment("Intro.", section=None)` comes first.
  - `test_runs_tabs_and_breaks_join`: `<w:r><w:t>Hel</w:t></w:r><w:r><w:t>lo</w:t></w:r><w:tab/><w:br/>` gives "Hello\t\n".
  - `test_table_rows_become_lines`: a 2×2 table gives "a | b\nc | d" inside the current section.
  - `test_localised_heading_style`: style id `Заголовок1` starts a section.
  - `test_not_a_zip`: `b"plain"` raises `PermanentIngestionError` matching "not a Word .docx file".
  - `test_zip_without_document`: raises matching "not a Word .docx file".
  - `test_xml_over_the_cap`: monkeypatch `DOCX_MAX_XML_BYTES` to 10 and the parse raises matching "too large".
  - `test_bad_xml`: raises matching "Could not read the DOCX".
  - `test_empty_document` returns `[]`. The pipeline already reports "no text".
  - `test_domain`: `source_type_for_filename("Report.DOCX") == SourceType.DOCX`, and the unsupported message lists `.docx`.
  - Frontend: the file input's `accept` contains `.docx`.
- [ ] **Step 2: Run them and see them fail** (ImportError / missing enum member).
- [ ] **Step 3: Implement `parse_docx` in `backend/fontes/adapters/loaders/docx.py`.** Read only `word/document.xml`. Check its `ZipInfo.file_size` against the cap before reading. Walk the `w:body` children in order: `w:p` → paragraph text, `w:tbl` → row lines. Catch `zipfile.BadZipFile`/`KeyError` → "The file is not a Word .docx file". Catch `ET.ParseError` → "Could not read the DOCX: …". Wire it in the domain, the container and the frontend.
- [ ] **Step 4: Run the backend and frontend checks**; all pass.
- [ ] **Step 5: Live check.**
  1. Build a .docx with `make_docx` in the scratchpad and upload it through the stack (`docker compose build migrate` + `up -d --wait api worker`).
  2. Check it becomes `ready`, and that `GET /documents/{id}/chunks` shows section locations.
  3. Delete it.
- [ ] **Step 6: Commit** "Ingest Word .docx files, headings as sections".

### Task 2: Store what a question follows up on

**Files:**
- Create: `backend/alembic/versions/0004_follow_ups.py`
- Modify: `backend/fontes/domain/answers.py` (`Answer.follow_up_of: UUID | None = None`, a defaulted field at the end), `backend/fontes/adapters/persistence/models.py`, `backend/fontes/adapters/persistence/questions.py`, `backend/fontes/api/schemas.py` (`AnswerOut.follow_up_of: UUID | None`, `QuestionSummaryOut.follow_up_of: UUID | None`), `frontend/src/api/types.ts`, `backend/tests/question_repository_contract.py`, `backend/tests/fakes.py` (the fake repository keeps the field), `backend/tests/integration/test_migrations.py`

**Interfaces:**
- Produces: `Answer.follow_up_of`. The migration adds `follow_up_of UUID NULL REFERENCES questions(id) ON DELETE SET NULL`, revision `0004_follow_ups`, down revision `0003_questions`.

- [ ] **Step 1: Write the failing tests.**
  - Contract: `test_follow_up_round_trips` adds a parent and a child with `follow_up_of=parent.id`; `get(child.id).follow_up_of == parent.id` and `list()` keeps it.
  - Integration: deleting the parent row with SQL sets the child's column to NULL.
  - Migration test: upgrade and downgrade pass through 0004.
  - API: `GET /questions/{id}` and `GET /questions` include `"follow_up_of"`.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement** the migration, the ORM column, the mapping and the schemas.
- [ ] **Step 4: Run the full backend checks**; all pass.
- [ ] **Step 5: Commit** "Store which question an answer follows up on".

### Task 3: Ask a follow-up

**Files:**
- Modify: `backend/fontes/application/asking.py`, `backend/fontes/application/prompting.py`, `backend/fontes/config.py` (`ask_follow_up_turns: int = Field(2, ge=0, le=5)`), `backend/fontes/container.py`, `backend/fontes/api/schemas.py` (`AskIn.follow_up_of: UUID | None = None`), `backend/fontes/api/ask.py`, `.env.example` and the README config table (`ASK_FOLLOW_UP_TURNS`), `backend/tests/application/test_asking.py`, `backend/tests/application/test_prompting.py`, `backend/tests/api/test_ask.py`

**Interfaces:**
- Consumes: `Answer.follow_up_of` (Task 2).
- Produces:
  - `AskService.__init__(..., follow_up_turns: int = 2)`;
  - `AskService.earlier(follow_up_of: UUID) -> list[Answer]`: oldest first; raises `QuestionNotFoundError` when the first lookup misses; at most `follow_up_turns` lookups;
  - `AskService.ask(question: str, follow_up_of: UUID | None = None, earlier: Sequence[Answer] = ()) -> AsyncIterator[AskEvent]`, which stores `follow_up_of` as given and uses `earlier` for retrieval and the prompt;
  - `build_prompt(question, hits, earlier: Sequence[Answer] = ()) -> Prompt`;
  - `EARLIER_ANSWER_MAX_CHARS = 1500` in `prompting.py`.

  The router calls `earlier()` before it returns the `StreamingResponse`, so an unknown id is a plain 422 and not a stream error. With `follow_up_turns == 0`, `earlier()` still checks that the parent exists and returns `[]`; the router then calls `ask(question, follow_up_of=id, earlier=[])`. That pins ruling 6.

- [ ] **Step 1: Write the failing tests.**
  - `test_follow_up_embeds_earlier_questions`: parent "Oolong temperature?", then the follow-up "And green tea?". The embedder's call is `["Oolong temperature?\nAnd green tea?"]`.
  - `test_follow_up_is_stored_with_its_parent`: `stored.follow_up_of == parent.id`.
  - `test_earlier_walks_at_most_n_turns`: chain a←b←c←d with turns=2 gives `[c, d]` for `earlier(d.id)`. A self-referencing row (`x.follow_up_of == x.id`) gives `[x, x]` with turns=2 and does not loop.
  - `test_earlier_unknown_raises`.
  - `test_zero_turns_links_but_adds_nothing`: the embedder sees the question alone, the prompt has no earlier section, `follow_up_of` is set.
  - Prompt tests:
    - with earlier turns, `user` contains "Earlier conversation:" before "Sources:";
    - the earlier answer appears without `[1]`;
    - an answer of 3000 characters appears cut to 1500 plus "…";
    - `SYSTEM` holds the rule line `- The earlier conversation only shows what the question refers to; take facts from the sources only.`;
    - without earlier turns, `user` is unchanged from today (regression).
  - API:
    - `POST /ask {"question": "x", "follow_up_of": "<unknown uuid>"}` gives 422 "The earlier question was not found";
    - a known id streams, and the stored answer carries it;
    - a malformed id gives 422.
  - Config: `ASK_FOLLOW_UP_TURNS=6` is refused.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.**
  - Strip markers with a module-level copy of `verification._MARKER`. Import it rather than duplicating it if the layering allows (same application package): `from fontes.application.verification import strip_markers`, a new small public function.
  - The earlier section format: `Earlier conversation:\n\nQ: {question}\nA: {answer}\n\n…` then `Sources:…`.
- [ ] **Step 4: Run the full backend checks**; all pass.
- [ ] **Step 5: Commit** "Ask a follow-up: earlier turns steer retrieval and the prompt".

### Task 4: Follow up from the UI

**Files:**
- Modify: `frontend/src/api/sse.ts` (`ask(question: string, signal: AbortSignal, followUpOf?: string | null)` sends `follow_up_of` only when set), `frontend/src/ask/AskPage.tsx`, `frontend/src/ask/AnswerView.tsx`, `frontend/src/ask/HistorySidebar.tsx`, `frontend/src/styles.css`, and the matching `*.test.tsx` / `sse.test.ts`

**Interfaces:**
- Consumes: `AnswerOut.follow_up_of`, `QuestionSummaryOut.follow_up_of`, `AskIn.follow_up_of` (Tasks 2–3).
- Produces:
  - AskPage state `followUp: { id: string; question: string } | null`.
  - AnswerView props add `onFollowUp?: () => void` and `followsUp?: string | null` (the parent's question text when known).

- [ ] **Step 1: Write the failing tests.**
  - `sse.test.ts`:
    - `ask('q', s, 'id1')` posts `{"question":"q","follow_up_of":"id1"}`;
    - `ask('q', s)` posts no `follow_up_of` key.
  - AskPage:
    - after a verdict, a "Follow up" button shows. Clicking it focuses the textarea and shows a chip "Following up on: <question>" with a "×" button labelled "Cancel follow-up";
    - submitting sends the id;
    - "×" clears the chip and the next submit sends none;
    - a follow-up opened from the history uses that entry's id;
    - the chip clears after a follow-up is answered, and "Follow up" shows again on the new answer.
  - AnswerView: with `followsUp="Oolong?"` it shows "Follow-up to: Oolong?".
  - HistorySidebar: an entry with `follow_up_of` set gets the class `follow-up` and an `aria-label` that starts with "Follow-up: ".
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.** Find the parent's question text for "Follow-up to:" in this order:
  1. the chip's question for a fresh answer;
  2. for a history answer, `getQuestion(follow_up_of)`. If that fails (for example, the parent was deleted), show nothing.
- [ ] **Step 4: Run `npm test`, `npm run lint` and `npm run build`**; all pass.
- [ ] **Step 5: Live check** through the stack on port 28080:
  1. ask "What temperature should I use for oolong tea?";
  2. press Follow up and ask "And for green tea?";
  3. check that the answer is about 70 °C and cites lumen-kettle.md, and that history marks the follow-up;
  4. delete those questions.
- [ ] **Step 6: Commit** "Follow up on an answer from the UI".

### Task 5: Eval follow-ups, docs and the spec

**Files:**
- Modify: `backend/fontes/eval/cases.py` (`Case.after: str | None = None`; the loader refuses an `after` that names an unknown case, a later case, or an off-topic case), `backend/fontes/eval/runner.py` (`run` keeps `qid` per case id; `EvalClient.ask(question, follow_up_of: str | None = None)`; a case whose `after` has no stored id gets the error "the case it follows has no answer"), `eval/cases.toml` (two cases), `README.md` ("Answer quality" table and text; a short "Follow-up questions" paragraph in the usage section; DOCX in the formats list), `docs/superpowers/specs/2026-11-03-fontes-design.md` (move both features out of Non-goals, with one line each on how they work), `backend/tests/eval/*`, `backend/tests/test_readme.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - case `kettle-green-follow-up`: `after = "kettle-oolong"`, question "And for green tea?", expect `["70"]`, en (the same fact as `kettle-green-tea`, which asks it standalone, so the two results compare);
  - case `garden-fee-follow-up`: `after = "garden-fee"`, question "А до какого числа его платить?", expect `["1 июня"]`, ru. The sample says "4800 рублей в год и вносится до 1 июня".

- [ ] **Step 1: Write the failing tests.**
  - The loader:
    - `after` naming an unknown case, a later case, or an off-topic case raises a `CaseError` that names the case;
    - the set loads 26 cases.
  - The runner (with FakeApi): the second case's `/ask` body carries `follow_up_of` equal to the first case's verdict `question_id`. When the first case errored, the follow-up case is an error with that message.
  - README test: the section says "26" and mentions "follow-up".
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full backend checks**; all pass.
- [ ] **Step 5: Live baseline.**
  1. Clean the stack (test leftovers only) and run `python -m fontes.eval` twice.
  2. Put the table and the misses in the README honestly, whatever they are.
  3. Delete the eval questions.
- [ ] **Step 6: Commit** "Eval follow-ups; README and spec for DOCX and follow-ups".
