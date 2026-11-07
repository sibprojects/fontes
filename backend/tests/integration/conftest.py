import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fontes.adapters.messaging.connection import AmqpConnection
from fontes.adapters.messaging.topology import Topology
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


@pytest.fixture
async def settings(tmp_path: Path) -> AsyncIterator[Settings]:
    """Real wiring, with its own queues so tests never touch the dev `fontes.ingest`."""
    settings = Settings(storage_dir=tmp_path, amqp_prefix=f"test-{uuid4().hex[:8]}")
    yield settings
    connection = AmqpConnection(settings.rabbitmq_url, connect_timeout=3.0)
    channel = await (await connection.get()).channel()
    topology = Topology(settings.amqp_prefix, settings.ingest_retry_delay_ms)
    for name in (topology.main, topology.retry, topology.dlq):
        await channel.queue_delete(name)
    await connection.close()
