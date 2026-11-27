import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import create_async_engine

from fontes.adapters.persistence.models import Base
from fontes.config import Settings

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).resolve().parents[2]


def _diff(conn: Connection) -> list[object]:
    context = MigrationContext.configure(conn, opts={"compare_type": False})
    return list(compare_metadata(context, Base.metadata))


async def test_models_match_migrations(migrated: None) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as conn:
            assert await conn.run_sync(_diff) == []
    finally:
        await engine.dispose()


async def test_follow_ups_migration_downgrades_and_upgrades(migrated: None) -> None:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))

    def columns(conn: Connection) -> set[str]:
        return {c["name"] for c in inspect(conn).get_columns("questions")}

    engine = create_async_engine(Settings().database_url)
    try:
        await asyncio.to_thread(command.downgrade, cfg, "0003_questions")
        async with engine.connect() as conn:
            assert "follow_up_of" not in await conn.run_sync(columns)
        await asyncio.to_thread(command.upgrade, cfg, "head")
        async with engine.connect() as conn:
            assert "follow_up_of" in await conn.run_sync(columns)
    finally:
        await engine.dispose()
