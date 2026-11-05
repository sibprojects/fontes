"""The real composition root must start and answer /health even when dependencies are down."""

import time

from httpx import ASGITransport, AsyncClient

from fontes.config import Settings
from fontes.container import build_app

# 10.255.255.1 is a non-routable address: packets are silently dropped, so connects hang.
BLACK_HOLE = Settings(
    database_url="postgresql+asyncpg://fontes:fontes@10.255.255.1:5432/fontes",
    rabbitmq_url="amqp://fontes:fontes@10.255.255.1:5672/",
    health_check_timeout=0.5,
)


async def test_app_starts_and_reports_hung_dependencies() -> None:
    app = build_app(BLACK_HOLE)
    started = time.monotonic()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        r = await c.get("/health")
    assert time.monotonic() - started < 2.0
    assert r.status_code == 503
    checks = r.json()["checks"]
    assert set(checks) == {"database", "rabbitmq"}
    assert checks["database"] != "ok"
    assert checks["rabbitmq"] != "ok"
