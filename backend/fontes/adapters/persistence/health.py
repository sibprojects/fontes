from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from fontes.adapters.errors import scrub


class PostgresHealthCheck:
    name = "database"

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def check(self) -> None:
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            detail = scrub(str(exc), self._engine.url.password)
            raise RuntimeError(f"database unavailable: {type(exc).__name__}: {detail}") from None
