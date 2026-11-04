"""Composition root: the only place where adapters are wired to ports."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from fontes.adapters.messaging.health import RabbitMQHealthCheck
from fontes.adapters.persistence.health import PostgresHealthCheck
from fontes.api.app import create_app
from fontes.application.ports.health import HealthCheck
from fontes.config import Settings


def build_app(settings: Settings) -> FastAPI:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    checks: list[HealthCheck] = [
        PostgresHealthCheck(engine),
        RabbitMQHealthCheck(settings.rabbitmq_url, connect_timeout=settings.health_check_timeout),
    ]
    return create_app(checks, health_timeout=settings.health_check_timeout, lifespan=lifespan)
