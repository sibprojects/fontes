from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fontes.adapters.persistence.chunks import SqlChunkRepository
from fontes.adapters.persistence.documents import SqlDocumentRepository
from fontes.config import Settings
from fontes.container import build_app
from fontes.domain.chunks import Chunk
from fontes.domain.documents import Document, DocumentStatus
from tests.fakes import FakeEmbedder, FakeLLM
from tests.sse import parse_sse

pytestmark = pytest.mark.integration


async def _client(
    settings: Settings, llm: FakeLLM, embedder: FakeEmbedder
) -> AsyncIterator[AsyncClient]:
    app = build_app(settings, embedder=embedder, llm=llm)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


async def _add_ready(
    repo: SqlDocumentRepository, settings: Settings, embedder: FakeEmbedder
) -> None:
    doc = Document.from_upload("guide.md", "hash-ask", now=datetime.now(UTC))
    await repo.add(doc)
    engine = create_async_engine(settings.database_url)
    try:
        chunks = SqlChunkRepository(async_sessionmaker(engine, expire_on_commit=False))
        chunk = Chunk(0, "Fact about X.", section="Facts")
        await chunks.replace(doc.id, [chunk], await embedder.embed([chunk.text]))
    finally:
        await engine.dispose()
    await repo.set_status(doc.id, DocumentStatus.READY)


async def test_no_relevant_chunks_means_no_llm_call(
    repo: SqlDocumentRepository, settings: Settings
) -> None:
    llm = FakeLLM(["never"])
    async for c in _client(settings, llm, FakeEmbedder()):
        r = await c.post("/ask", json={"question": "What is X?"})
        verdict = parse_sse(r.text)[-1][1]
        assert verdict["label"] == "not_found"
        assert llm.calls == []
        history = (await c.get("/questions")).json()
        assert [q["id"] for q in history] == [verdict["question_id"]]


async def test_invalid_markers_are_discarded_end_to_end(
    repo: SqlDocumentRepository, settings: Settings
) -> None:
    embedder = FakeEmbedder()
    await _add_ready(repo, settings, embedder)
    llm = FakeLLM(["Fact [1] and [9]."])
    async for c in _client(settings.model_copy(update={"ask_min_score": 0.0}), llm, embedder):
        r = await c.post("/ask", json={"question": "What is X?"})
        verdict = parse_sse(r.text)[-1][1]
        assert verdict["label"] == "supported"
        assert verdict["paragraphs"][0]["text"] == "Fact [1] and."
        assert [citation["n"] for citation in verdict["citations"]] == [1]
        stored = (await c.get(f"/questions/{verdict['question_id']}")).json()
        assert stored["answer"] == "Fact [1] and."
        assert "[9]" not in stored["answer"]
        assert stored["citations"][0]["location"] == "Facts"
