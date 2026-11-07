import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from fontes.adapters.messaging.connection import AmqpConnection
from fontes.adapters.messaging.health import RabbitMQHealthCheck
from fontes.adapters.persistence.health import PostgresHealthCheck
from fontes.config import Settings
from fontes.container import build_app

pytestmark = pytest.mark.integration


async def test_postgres_check_ok() -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        await PostgresHealthCheck(engine).check()
    finally:
        await engine.dispose()


async def test_rabbitmq_check_ok() -> None:
    connection = AmqpConnection(Settings().rabbitmq_url, connect_timeout=3.0)
    try:
        await RabbitMQHealthCheck(connection).check()
    finally:
        await connection.close()


async def test_postgres_check_error_hides_password() -> None:
    engine = create_async_engine("postgresql+asyncpg://fontes:s3cret@localhost:5999/fontes")
    try:
        with pytest.raises(Exception) as exc:
            await PostgresHealthCheck(engine).check()
        assert "s3cret" not in str(exc.value)
    finally:
        await engine.dispose()


async def test_rabbitmq_check_error_hides_password() -> None:
    with pytest.raises(Exception) as exc:
        await RabbitMQHealthCheck(
            AmqpConnection("amqp://fontes:s3cret@localhost:5999/", connect_timeout=3.0)
        ).check()
    assert "s3cret" not in str(exc.value)


async def test_rabbitmq_timeout_message_is_clear() -> None:
    # 10.255.255.1 is non-routable: the connect hangs until our timeout fires.
    connection = AmqpConnection("amqp://fontes:fontes@10.255.255.1:5672/", connect_timeout=0.3)
    with pytest.raises(RuntimeError, match="timed out"):
        await RabbitMQHealthCheck(connection).check()


async def test_build_app_health_ok() -> None:
    app = build_app(Settings())
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
