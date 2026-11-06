"""Composition root: the only place where adapters are wired to ports."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fontes.adapters.messaging.health import RabbitMQHealthCheck
from fontes.adapters.persistence.documents import SqlDocumentRepository
from fontes.adapters.persistence.health import PostgresHealthCheck
from fontes.adapters.storage.local import LocalFileStorage
from fontes.api.app import create_app
from fontes.application.documents import DocumentService
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
    documents = DocumentService(
        SqlDocumentRepository(async_sessionmaker(engine, expire_on_commit=False)),
        LocalFileStorage(settings.storage_dir),
        max_upload_bytes=settings.max_upload_bytes,
    )
    return create_app(
        checks,
        health_timeout=settings.health_check_timeout,
        documents=documents,
        max_upload_bytes=settings.max_upload_bytes,
        lifespan=lifespan,
    )
