import itertools
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from fontes.api.app import create_app
from fontes.application.asking import AskService
from fontes.application.documents import DocumentService
from fontes.domain.chunks import Chunk
from fontes.domain.documents import Document, DocumentStatus
from tests.fakes import (
    FakeEmbedder,
    FakeLLM,
    FakePublisher,
    InMemoryChunkRepository,
    InMemoryDocumentRepository,
    InMemoryFileStorage,
    InMemoryQuestionRepository,
)
from tests.sse import parse_sse

T0 = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


class Env:
    def __init__(self, llm: FakeLLM) -> None:
        self.docs = InMemoryDocumentRepository()
        self.chunks = InMemoryChunkRepository(self.docs)
        self.embedder = FakeEmbedder()
        self.llm = llm
        minutes = itertools.count()
        self.ask = AskService(
            self.embedder,
            self.chunks,
            llm,
            InMemoryQuestionRepository(),
            top_k=6,
            min_score=0.0,
            clock=lambda: T0 + timedelta(minutes=next(minutes)),
        )

    async def add_ready(self, text: str = "X is the answer.") -> None:
        doc = Document.from_upload("guide.md", f"hash-{uuid4()}", now=T0)
        await self.docs.add(doc)
        await self.docs.set_status(doc.id, DocumentStatus.READY)
        chunk = Chunk(0, text, section="Install")
        await self.chunks.replace(doc.id, [chunk], await self.embedder.embed([text]))

    async def client(self) -> AsyncIterator[AsyncClient]:
        documents = DocumentService(
            self.docs, InMemoryFileStorage(), self.chunks, FakePublisher(), max_upload_bytes=100
        )
        app = create_app(
            [],
            health_timeout=1.0,
            documents=documents,
            max_upload_bytes=100,
            max_attempts=3,
            ask=self.ask,
            question_max_chars=2000,
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
def env() -> Env:
    return Env(FakeLLM(["The answer ", "is X [1]."]))


@pytest.fixture
async def c(env: Env) -> AsyncIterator[AsyncClient]:
    async for client in env.client():
        yield client


async def _ask(c: AsyncClient, question: str = "What is X?") -> list[tuple[str, Any]]:
    r = await c.post("/ask", json={"question": question})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"
    return parse_sse(r.text)


async def test_ask_streams_tokens_then_verdict(env: Env, c: AsyncClient) -> None:
    await env.add_ready()
    events = await _ask(c)
    assert [name for name, _ in events] == ["token", "token", "verdict"]
    assert [data["text"] for _, data in events[:2]] == ["The answer ", "is X [1]."]
    verdict = events[-1][1]
    assert set(verdict) == {"question_id", "label", "paragraphs", "citations"}
    assert verdict["label"] == "supported"
    assert verdict["paragraphs"] == [
        {"text": "The answer is X [1].", "supported": True, "citations": [1]}
    ]
    (citation,) = verdict["citations"]
    assert citation["n"] == 1
    assert citation["location"] == "Install"
    assert citation["document_title"] == "guide.md"
    assert citation["url"] is None
    assert citation["excerpt"] == "X is the answer."


async def test_not_found_has_no_llm_call(env: Env, c: AsyncClient) -> None:
    events = await _ask(c)
    assert [name for name, _ in events] == ["token", "verdict"]
    assert events[-1][1]["label"] == "not_found"
    assert env.llm.calls == []


async def test_error_event_when_llm_fails() -> None:
    detail = "Cannot reach Ollama at http://ollama:11434"
    env = Env(FakeLLM(fail=ConnectionError(detail)))
    await env.add_ready()
    async for c in env.client():
        events = await _ask(c)
        assert events[-1] == ("error", {"detail": detail})
        assert (await c.get("/questions")).json() == []


async def test_error_without_message_names_its_class() -> None:
    env = Env(FakeLLM(fail=TimeoutError()))
    await env.add_ready()
    async for c in env.client():
        assert (await _ask(c))[-1] == ("error", {"detail": "TimeoutError"})


async def test_blank_question_is_422(c: AsyncClient) -> None:
    r = await c.post("/ask", json={"question": "   "})
    assert r.status_code == 422
    assert "detail" in r.json()


async def test_too_long_question_is_422(c: AsyncClient) -> None:
    r = await c.post("/ask", json={"question": "x" * 2001})
    assert r.status_code == 422
    assert "2000" in r.json()["detail"]


async def test_question_at_limit_is_accepted(c: AsyncClient) -> None:
    assert (await _ask(c, "x" * 2000))[-1][0] == "verdict"


async def test_history_lists_newest_first_and_opens_one(env: Env, c: AsyncClient) -> None:
    await env.add_ready()
    first = (await _ask(c, "first?"))[-1][1]["question_id"]
    second = (await _ask(c, "second?"))[-1][1]["question_id"]
    listed = (await c.get("/questions")).json()
    assert [q["id"] for q in listed] == [second, first]
    assert set(listed[0]) == {"id", "question", "label", "created_at"}
    r = await c.get(f"/questions/{first}")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "id",
        "question",
        "answer",
        "label",
        "paragraphs",
        "citations",
        "provider",
        "model",
        "duration_ms",
        "created_at",
    }
    assert body["id"] == first
    assert body["question"] == "first?"
    assert body["answer"] == "The answer is X [1]."
    assert body["label"] == "supported"
    assert (body["provider"], body["model"]) == ("fake", "fake-1")
    assert body["paragraphs"][0]["supported"] is True
    assert body["citations"][0]["location"] == "Install"


async def test_unknown_question_is_404(c: AsyncClient) -> None:
    r = await c.get(f"/questions/{uuid4()}")
    assert r.status_code == 404
    assert "detail" in r.json()


async def test_cyrillic_survives_sse() -> None:
    env = Env(FakeLLM(["Ответ: икс [1]."]))
    await env.add_ready("Икс — это ответ.")
    async for c in env.client():
        r = await c.post("/ask", json={"question": "Что такое икс?"})
        assert "Ответ" in r.text
        assert "\\u04" not in r.text
        verdict = parse_sse(r.text)[-1][1]
        assert verdict["paragraphs"][0]["text"] == "Ответ: икс [1]."
        assert verdict["citations"][0]["excerpt"] == "Икс — это ответ."
        stored = (await c.get(f"/questions/{verdict['question_id']}")).json()
        assert stored["question"] == "Что такое икс?"
