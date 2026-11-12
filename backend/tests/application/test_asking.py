from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from fontes.application.asking import (
    NOT_FOUND_TEXT,
    AskEvent,
    AskService,
    QuestionNotFoundError,
    TokenEvent,
    VerdictEvent,
)
from fontes.domain.answers import Answer, AnswerLabel, Citation
from fontes.domain.chunks import Chunk
from fontes.domain.documents import Document, DocumentStatus
from tests.fakes import (
    FakeEmbedder,
    FakeLLM,
    InMemoryChunkRepository,
    InMemoryDocumentRepository,
    InMemoryQuestionRepository,
)

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
CHUNKS = ["The answer ", "is X [1].\n\nAlso Y [5]."]


class World:
    def __init__(self, llm: FakeLLM | None = None, min_score: float = 0.0) -> None:
        self.docs = InMemoryDocumentRepository()
        self.chunks = InMemoryChunkRepository(self.docs)
        self.questions = InMemoryQuestionRepository()
        self.llm = llm or FakeLLM(CHUNKS)
        self.embedder = FakeEmbedder()
        ticks = iter([0.0, 1.5])
        self.service = AskService(
            self.embedder,
            self.chunks,
            self.llm,
            self.questions,
            top_k=6,
            min_score=min_score,
            clock=lambda: NOW,
            timer=lambda: next(ticks),
        )

    async def add_ready(self, title: str = "guide.md") -> tuple[Document, Chunk]:
        doc = Document.from_upload(title, f"hash-{uuid4()}", now=NOW)
        await self.docs.add(doc)
        await self.docs.set_status(doc.id, DocumentStatus.READY)
        chunk = Chunk(0, "X is the answer.", section="Install")
        await self.chunks.replace(doc.id, [chunk], await self.embedder.embed([chunk.text]))
        return doc, chunk


async def _collect(events: AsyncIterator[AskEvent]) -> list[AskEvent]:
    return [event async for event in events]


def _verdict(events: list[AskEvent]) -> Answer:
    last = events[-1]
    assert isinstance(last, VerdictEvent)
    return last.answer


async def test_no_hits_skips_llm() -> None:
    world = World()
    events = await _collect(world.service.ask("What is X?"))
    assert events[0] == TokenEvent(NOT_FOUND_TEXT)
    answer = _verdict(events)
    assert len(events) == 2
    assert answer.label == AnswerLabel.NOT_FOUND
    assert answer.text == NOT_FOUND_TEXT
    assert (answer.paragraphs, answer.citations) == ((), ())
    assert (answer.provider, answer.model) == (None, None)
    assert world.llm.calls == []
    assert await world.questions.list(10) == [answer]


async def test_hits_below_threshold_skip_llm() -> None:
    world = World(min_score=1.01)
    await world.add_ready()
    answer = _verdict(await _collect(world.service.ask("What is X?")))
    assert answer.label == AnswerLabel.NOT_FOUND
    assert world.llm.calls == []


async def test_tokens_streamed_then_verdict() -> None:
    world = World()
    await world.add_ready()
    events = await _collect(world.service.ask("What is X?"))
    assert [type(e) for e in events] == [TokenEvent, TokenEvent, VerdictEvent]
    assert [e.text for e in events if isinstance(e, TokenEvent)] == CHUNKS
    ((system, user),) = world.llm.calls
    assert "[1] guide.md — Install" in user
    assert user.rstrip().endswith("What is X?")


async def test_verdict_verifies_and_resolves_citations() -> None:
    world = World()
    doc, chunk = await world.add_ready()
    answer = _verdict(await _collect(world.service.ask("What is X?")))
    assert answer.text == "The answer is X [1].\n\nAlso Y."
    assert answer.label == AnswerLabel.PARTIALLY_SUPPORTED
    assert answer.citations == (Citation(1, doc.id, doc.title, "Install", None, chunk.text),)


async def test_answer_stored_with_provider_model_timing() -> None:
    world = World()
    await world.add_ready()
    answer = _verdict(await _collect(world.service.ask("  What is X?  ")))
    assert await world.questions.get(answer.id) == answer
    assert answer.question == "What is X?"
    assert (answer.provider, answer.model) == ("fake", "fake-1")
    assert answer.duration_ms == 1500
    assert answer.created_at == NOW


async def test_llm_failure_stores_nothing() -> None:
    world = World(FakeLLM(["part"], fail=ConnectionError("Cannot reach Ollama"), fail_after=1))
    await world.add_ready()
    seen: list[AskEvent] = []
    with pytest.raises(ConnectionError, match="Cannot reach Ollama"):
        async for event in world.service.ask("What is X?"):
            seen.append(event)
    assert seen == [TokenEvent("part")]
    assert await world.service.history() == []


async def test_embedder_failure_stores_nothing() -> None:
    world = World()
    world.embedder.fail = ConnectionError("Cannot reach Ollama")
    with pytest.raises(ConnectionError):
        await _collect(world.service.ask("What is X?"))
    assert await world.service.history() == []


async def test_history_and_get() -> None:
    world = World()
    answer = _verdict(await _collect(world.service.ask("What is X?")))
    assert await world.service.history() == [answer]
    assert await world.service.get(answer.id) == answer


async def test_get_unknown_raises() -> None:
    with pytest.raises(QuestionNotFoundError):
        await World().service.get(uuid4())
