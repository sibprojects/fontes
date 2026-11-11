from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from fontes.adapters.persistence.documents import SqlDocumentRepository
from fontes.adapters.persistence.questions import SqlQuestionRepository
from fontes.config import Settings
from fontes.domain.answers import Citation
from fontes.domain.documents import Document
from tests.question_repository_contract import (  # noqa: F401
    T0,
    make_answer,
    test_add_then_get_round_trips,
    test_get_unknown_is_none,
    test_list_newest_first_with_limit,
    test_not_found_answer_round_trips,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine(migrated: None) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(Settings().database_url)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE documents, questions CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
def questions(engine: AsyncEngine) -> SqlQuestionRepository:
    return SqlQuestionRepository(async_sessionmaker(engine, expire_on_commit=False))


@pytest.fixture
def docs(engine: AsyncEngine) -> SqlDocumentRepository:
    return SqlDocumentRepository(async_sessionmaker(engine, expire_on_commit=False))


async def test_history_survives_document_delete(
    questions: SqlQuestionRepository, docs: SqlDocumentRepository
) -> None:
    doc = Document.from_upload("report.pdf", "hash-report", now=T0)
    await docs.add(doc)
    citation = Citation(1, doc.id, doc.title, "p. 2", None, "Revenue grew.")
    answer = make_answer(citations=(citation,))
    await questions.add(answer)
    assert await docs.delete(doc.id)
    stored = await questions.get(answer.id)
    assert stored is not None
    assert stored.citations == (citation,)
