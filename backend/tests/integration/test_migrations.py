import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from fontes.adapters.persistence.models import Base
from fontes.config import Settings

pytestmark = pytest.mark.integration


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
