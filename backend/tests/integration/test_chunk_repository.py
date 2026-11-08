import importlib.util
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from fontes.adapters.persistence.chunks import SqlChunkRepository
from fontes.adapters.persistence.documents import SqlDocumentRepository
from fontes.config import Settings
from fontes.domain.chunks import Chunk
from fontes.domain.documents import Document
from tests.chunk_repository_contract import (  # noqa: F401
    T0,
    test_replace_for_missing_document_writes_nothing,
    test_replace_then_list_in_order,
    test_replace_twice_leaves_only_second,
    test_replace_with_mismatched_embeddings_raises,
    test_text_with_unusual_characters_round_trips,
)
from tests.integration.conftest import BACKEND

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine(migrated: None) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(Settings().database_url)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE documents CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
def docs(engine: AsyncEngine) -> SqlDocumentRepository:
    return SqlDocumentRepository(async_sessionmaker(engine, expire_on_commit=False))


@pytest.fixture
def chunks(engine: AsyncEngine) -> SqlChunkRepository:
    return SqlChunkRepository(async_sessionmaker(engine, expire_on_commit=False))


async def test_deleting_document_deletes_its_chunks(
    engine: AsyncEngine, docs: SqlDocumentRepository, chunks: SqlChunkRepository
) -> None:
    doc = Document.from_upload("a.pdf", "hash-a", now=T0)
    await docs.add(doc)
    await chunks.replace(doc.id, [Chunk(0, "a"), Chunk(1, "b")], [[0.1] * 1024, [0.2] * 1024])
    assert await docs.delete(doc.id)
    assert await chunks.list_for_document(doc.id) == []
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM chunks")) == 0


async def test_embedding_round_trips(
    engine: AsyncEngine, docs: SqlDocumentRepository, chunks: SqlChunkRepository
) -> None:
    doc = Document.from_upload("a.pdf", "hash-a", now=T0)
    await docs.add(doc)
    vector = [i / 1024 - 0.5 for i in range(1024)]
    await chunks.replace(doc.id, [Chunk(0, "a")], [vector])
    async with engine.connect() as conn:
        stored = await conn.scalar(text("SELECT embedding::text FROM chunks"))
    values = [float(v) for v in str(stored).strip("[]").split(",")]
    assert values == pytest.approx(vector, abs=1e-6)


def test_migration_dimension_matches_settings() -> None:
    path = BACKEND / "alembic" / "versions" / "0002_chunks.py"
    spec = importlib.util.spec_from_file_location("migration_0002", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert Settings().embedding_dimension == module.EMBEDDING_DIMENSION
