import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fontes.adapters.persistence.documents import SqlDocumentRepository
from fontes.config import Settings

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def migrated() -> None:
    # env.py drives its own event loop, so run it outside the test loop.
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    asyncio.run(asyncio.to_thread(command.upgrade, cfg, "head"))


@pytest.fixture
async def repo(migrated: None) -> AsyncIterator[SqlDocumentRepository]:
    engine = create_async_engine(Settings().database_url)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE documents"))
    yield SqlDocumentRepository(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()
