"""Composition root: the only place where adapters are wired to ports."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fontes.adapters.messaging.connection import AmqpConnection
from fontes.adapters.messaging.health import RabbitMQHealthCheck
from fontes.adapters.messaging.publisher import AmqpPublisher
from fontes.adapters.messaging.topology import Topology
from fontes.adapters.persistence.documents import SqlDocumentRepository
from fontes.adapters.persistence.health import PostgresHealthCheck
from fontes.adapters.storage.local import LocalFileStorage
from fontes.api.app import create_app
from fontes.application.documents import DocumentService
from fontes.application.ports.health import HealthCheck
from fontes.config import Settings


def build_app(settings: Settings) -> FastAPI:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    # Half the health budget, so a hung broker reports "connect timed out", not a bare timeout.
    amqp = AmqpConnection(settings.rabbitmq_url, connect_timeout=settings.health_check_timeout / 2)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await amqp.close()
        await engine.dispose()

    checks: list[HealthCheck] = [
        PostgresHealthCheck(engine),
        RabbitMQHealthCheck(amqp),
    ]
    documents = DocumentService(
        SqlDocumentRepository(async_sessionmaker(engine, expire_on_commit=False)),
        LocalFileStorage(settings.storage_dir),
        AmqpPublisher(amqp, Topology(settings.amqp_prefix, settings.ingest_retry_delay_ms)),
        max_upload_bytes=settings.max_upload_bytes,
    )
    return create_app(
        checks,
        health_timeout=settings.health_check_timeout,
        documents=documents,
        max_upload_bytes=settings.max_upload_bytes,
        lifespan=lifespan,
    )
