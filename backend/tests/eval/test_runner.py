import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

import fontes.eval.__main__ as cli
from fontes.eval.cases import DEFAULT_SAMPLES, Case
from fontes.eval.runner import EvalClient, StackError, run

KETTLE = "lumen-kettle.md"
GARDEN = "sad-pravila.md"


def sse(name: str, data: object) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def verdict(qid: str, label: str, paragraphs: list[str], titles: list[str]) -> str:
    return sse(
        "verdict",
        {
            "question_id": qid,
            "label": label,
            "paragraphs": [{"text": t, "supported": True, "citations": [1]} for t in paragraphs],
            "citations": [
                {
                    "n": n,
                    "document_id": "d",
                    "document_title": title,
                    "location": "",
                    "url": None,
                    "excerpt": "",
                }
                for n, title in enumerate(titles, 1)
            ],
        },
    )


class FakeApi:
    """Just enough of the Fontes API for the eval: documents, /ask (SSE) and /questions."""

    def __init__(self, *docs: tuple[str, str]) -> None:
        self.docs: list[dict[str, Any]] = [
            {"id": str(uuid4()), "title": t, "status": s, "error": None} for t, s in docs
        ]
        self.answers: dict[str, httpx.Response] = {}
        self.uploads: list[str] = []
        # Polls of /documents a new upload stays `processing` for.
        self.processing_polls = 1
        self.stored: dict[str, tuple[str | None, str | None]] = {}
        # When set, `GET /documents` answers with this instead.
        self.documents_response: httpx.Response | None = None
        self.questions_down = False

    def answer(self, question: str, body: str, provider: str = "ollama") -> None:
        self.answers[question] = httpx.Response(200, text=body)
        if '"question_id": "' in body:
            qid = body.split('"question_id": "', 1)[1].split('"', 1)[0]
            self.stored[qid] = (provider, "qwen2.5:7b")

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/documents" and self.documents_response:
            return self.documents_response
        if request.method == "GET" and path.startswith("/questions/") and self.questions_down:
            raise httpx.ConnectError("connection refused", request=request)
        if request.method == "GET" and path == "/documents":
            for doc in self.docs:
                if doc["status"] == "processing" and doc.get("polls", 0) >= self.processing_polls:
                    doc["status"] = "ready"
                doc["polls"] = doc.get("polls", 0) + 1
            return httpx.Response(
                200, json=[{k: d[k] for k in ("id", "title", "status", "error")} for d in self.docs]
            )
        if request.method == "POST" and path == "/documents":
            title = request.content.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
            self.uploads.append(title)
            self.docs.append(
                {"id": str(uuid4()), "title": title, "status": "processing", "error": None}
            )
            return httpx.Response(201, json={"id": self.docs[-1]["id"]})
        if request.method == "POST" and path == "/ask":
            question = json.loads(request.content)["question"]
            default = httpx.Response(200, text=verdict("nf", "not_found", ["Nothing."], []))
            return self.answers.get(question, default)
        if request.method == "GET" and path.startswith("/questions/"):
            qid = path.rsplit("/", 1)[1]
            if qid not in self.stored:
                return httpx.Response(404, json={"detail": "Question not found"})
            provider, model = self.stored[qid]
            return httpx.Response(200, json={"id": qid, "provider": provider, "model": model})
        return httpx.Response(404, json={"detail": "no route"})

    def client(self, **kwargs: Any) -> EvalClient:
        return EvalClient(
            "http://fontes.test",
            transport=httpx.MockTransport(self.handle),
            poll_seconds=0,
            **kwargs,
        )


async def test_prepare_uploads_missing_samples_and_waits() -> None:
    api = FakeApi((KETTLE, "ready"))
    async with api.client() as client:
        await client.prepare(DEFAULT_SAMPLES)
    assert api.uploads == [GARDEN]
    assert all(d["status"] == "ready" for d in api.docs)


async def test_prepare_refuses_foreign_documents() -> None:
    api = FakeApi((KETTLE, "ready"), ("notes.pdf", "ready"), ("secret.md", "failed"))
    async with api.client() as client:
        with pytest.raises(StackError) as caught:
            await client.prepare(DEFAULT_SAMPLES)
    assert "notes.pdf" in str(caught.value) and "secret.md" in str(caught.value)
    assert api.uploads == []


async def test_prepare_refuses_a_failed_sample() -> None:
    api = FakeApi((KETTLE, "ready"), (GARDEN, "failed"))
    api.docs[1]["error"] = "boom"
    async with api.client() as client:
        with pytest.raises(StackError, match="sad-pravila.md failed: boom") as caught:
            await client.prepare(DEFAULT_SAMPLES)
    assert "delete it" in str(caught.value)


async def test_prepare_gives_up_after_the_timeout() -> None:
    api = FakeApi((KETTLE, "ready"), (GARDEN, "processing"))
    api.processing_polls = 10**6
    async with api.client(ready_timeout=0) as client:
        with pytest.raises(StackError, match=GARDEN):
            await client.prepare(DEFAULT_SAMPLES)


async def test_ask_reads_the_verdict() -> None:
    api = FakeApi()
    body = (
        sse("token", {"text": "Use 90 °C "})
        + sse("token", {"text": "[1]."})
        + verdict("q1", "supported", ["Use 90 °C [1].", "For oolong [1]."], [KETTLE, KETTLE])
    )
    api.answer("Oolong?", body)
    async with api.client() as client:
        outcome, provider, model = await client.ask("Oolong?")
    assert outcome.answer == "Use 90 °C [1].\n\nFor oolong [1]."
    assert (outcome.label, outcome.documents, outcome.error) == ("supported", (KETTLE,), None)
    assert outcome.seconds >= 0
    assert (provider, model) == ("ollama", "qwen2.5:7b")


async def test_ask_records_an_error_event() -> None:
    api = FakeApi()
    api.answer("Q?", sse("error", {"detail": "Chat model 'x' is not available"}))
    async with api.client() as client:
        outcome, provider, model = await client.ask("Q?")
    assert outcome.error == "Chat model 'x' is not available"
    assert outcome.label is None
    assert (provider, model) == (None, None)


async def test_ask_without_a_verdict() -> None:
    api = FakeApi()
    api.answer("Q?", sse("token", {"text": "Hal"}))
    async with api.client() as client:
        outcome, _, _ = await client.ask("Q?")
    assert outcome.error == "the stream ended without a verdict"


async def test_ask_http_error() -> None:
    api = FakeApi()
    api.answers["Q?"] = httpx.Response(422, json={"detail": "Question is too long"})
    async with api.client() as client:
        outcome, _, _ = await client.ask("Q?")
    assert outcome.error == "HTTP 422: Question is too long"


async def test_run_continues_after_an_error() -> None:
    api = FakeApi()
    api.answer("A?", verdict("qa", "supported", ["90 [1]."], [KETTLE]))
    api.answer("B?", sse("error", {"detail": "timeout"}))
    cases = [
        Case("a", "A?", KETTLE, ("90",), "en"),
        Case("b", "B?", KETTLE, ("90",), "en"),
        Case("c", "C?", None, (), "en"),
    ]
    async with api.client() as client:
        results, provider, model = await run(cases, client)
    assert [r.case.id for r in results] == ["a", "b", "c"]
    assert [r.passed for r in results] == [False, False, True]
    assert results[0].checks["facts"] is True
    assert results[1].outcome.error == "timeout"
    assert (provider, model) == ("ollama", "qwen2.5:7b")


def test_main_unreachable_stack_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--base-url", "http://127.0.0.1:9"]) == 1
    assert capsys.readouterr().err.startswith("error: cannot reach the API at http://127.0.0.1:9")


def test_main_writes_the_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeApi((KETTLE, "ready"), (GARDEN, "ready"))
    api.answer(
        "What temperature should I use for oolong tea?",
        verdict("q1", "supported", ["Use 90 °C [1]."], [KETTLE]),
    )
    monkeypatch.setattr(cli, "EvalClient", lambda base_url, **_: api.client())
    out = tmp_path / "r.json"
    assert cli.main(["--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert len(report["results"]) == 24
    assert (report["provider"], report["model"]) == ("ollama", "qwen2.5:7b")
    first = report["results"][0]
    assert set(first) == {
        "id",
        "passed",
        "checks",
        "label",
        "documents",
        "error",
        "seconds",
        "answer",
    }
    assert (first["id"], first["passed"]) == ("kettle-oolong", True)
    assert report["summary"]["cases"] == 24
    assert "| facts |" in capsys.readouterr().out


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="Internal Server Error"),
        httpx.Response(200, text="<!doctype html><html></html>"),
        httpx.Response(200, json={"detail": "not a list"}),
    ],
    ids=["server-error", "html", "not-a-list"],
)
async def test_prepare_on_something_that_is_not_the_api(response: httpx.Response) -> None:
    api = FakeApi()
    api.documents_response = response
    async with api.client() as client:
        with pytest.raises(StackError, match="http://fontes.test"):
            await client.prepare(DEFAULT_SAMPLES)


async def test_foreign_documents_message_names_the_samples_dir(tmp_path: Path) -> None:
    (tmp_path / "only.md").write_text("# Only\n", encoding="utf-8")
    api = FakeApi(("other.md", "ready"))
    async with api.client() as client:
        with pytest.raises(StackError) as caught:
            await client.prepare(tmp_path)
    assert str(tmp_path) in str(caught.value) and "Delete them" in str(caught.value)


@pytest.mark.parametrize(
    "body",
    ["event: verdict\ndata: {not json\n\n", sse("verdict", {"label": "supported"})],
    ids=["bad-json", "missing-keys"],
)
async def test_ask_records_a_malformed_event(body: str) -> None:
    api = FakeApi()
    api.answer("Q?", body)
    async with api.client() as client:
        outcome, _, _ = await client.ask("Q?")
    assert outcome.error is not None and outcome.error.startswith("malformed event")
    assert outcome.label is None


async def test_ask_survives_a_failed_history_lookup() -> None:
    api = FakeApi()
    api.answer("Q?", verdict("q1", "supported", ["90 [1]."], [KETTLE]))
    api.questions_down = True
    async with api.client() as client:
        outcome, provider, model = await client.ask("Q?")
    assert (outcome.label, outcome.error) == ("supported", None)
    assert (provider, model) == (None, None)


@pytest.mark.parametrize(
    "text",
    ["[[case]\n", '[[case]]\nid = "x"\nlanguage = "en"\n'],
    ids=["bad-toml", "missing-key"],
)
def test_main_broken_cases_file_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    cases = tmp_path / "cases.toml"
    cases.write_text(text, encoding="utf-8")
    assert cli.main(["--cases", str(cases), "--base-url", "http://127.0.0.1:9"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ") and str(cases) in err


def test_main_missing_cases_file_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope.toml"
    assert cli.main(["--cases", str(missing)]) == 1
    assert capsys.readouterr().err.startswith("error: ")
