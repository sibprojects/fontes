"""Composition root: the only place where adapters are wired to ports."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fontes.adapters.embeddings.ollama import OllamaEmbedder
from fontes.adapters.llm.ollama import OllamaLLM
from fontes.adapters.loaders.html import parse_html
from fontes.adapters.loaders.markdown import parse_markdown
from fontes.adapters.loaders.pdf import parse_pdf
from fontes.adapters.loaders.stored import StoredFileLoader
from fontes.adapters.loaders.url import UrlLoader
from fontes.adapters.messaging.connection import AmqpConnection
from fontes.adapters.messaging.consumer import IngestConsumer
from fontes.adapters.messaging.health import RabbitMQHealthCheck
from fontes.adapters.messaging.publisher import AmqpPublisher
from fontes.adapters.messaging.topology import Topology
from fontes.adapters.persistence.chunks import SqlChunkRepository
from fontes.adapters.persistence.documents import SqlDocumentRepository
from fontes.adapters.persistence.health import PostgresHealthCheck
from fontes.adapters.persistence.questions import SqlQuestionRepository
from fontes.adapters.storage.local import LocalFileStorage
from fontes.api.app import create_app
from fontes.application.asking import AskService
from fontes.application.chunking import Chunker
from fontes.application.documents import DocumentService
from fontes.application.ingestion import IngestionService
from fontes.application.pipeline import IngestionPipeline
from fontes.application.ports.embeddings import Embedder
from fontes.application.ports.health import HealthCheck
from fontes.application.ports.ingestion import DocumentProcessor
from fontes.application.ports.llm import LLMProvider
from fontes.application.ports.loading import DocumentLoader
from fontes.config import Settings
from fontes.domain.documents import SourceType
from fontes.worker import Worker, logged


def build_app(
    settings: Settings,
    embedder: Embedder | None = None,
    llm: LLMProvider | None = None,
) -> FastAPI:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    # Half the health budget, so a hung broker reports "connect timed out", not a bare timeout.
    amqp = AmqpConnection(settings.rabbitmq_url, connect_timeout=settings.health_check_timeout / 2)
    # Only clients built here are ours to close; passed-in ones belong to the caller.
    own_embedder: OllamaEmbedder | None = None
    own_llm: OllamaLLM | None = None
    if embedder is None:
        embedder = own_embedder = _embedder(settings)
    if llm is None:
        llm = own_llm = OllamaLLM(
            settings.ollama_url,
            settings.chat_model,
            num_ctx=settings.llm_num_ctx,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_seconds,
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await amqp.close()
        if own_embedder is not None:
            await own_embedder.aclose()
        if own_llm is not None:
            await own_llm.aclose()
        await engine.dispose()

    checks: list[HealthCheck] = [
        PostgresHealthCheck(engine),
        RabbitMQHealthCheck(amqp),
    ]
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    documents = DocumentService(
        SqlDocumentRepository(sessions),
        LocalFileStorage(settings.storage_dir),
        SqlChunkRepository(sessions),
        AmqpPublisher(amqp, Topology(settings.amqp_prefix, settings.ingest_retry_delay_ms)),
        max_upload_bytes=settings.max_upload_bytes,
        publish_timeout=settings.publish_timeout_seconds,
    )
    ask = AskService(
        embedder,
        SqlChunkRepository(sessions),
        llm,
        SqlQuestionRepository(sessions),
        top_k=settings.ask_top_k,
        min_score=settings.ask_min_score,
    )
    return create_app(
        checks,
        health_timeout=settings.health_check_timeout,
        documents=documents,
        max_upload_bytes=settings.max_upload_bytes,
        ask=ask,
        question_max_chars=settings.question_max_chars,
        lifespan=lifespan,
    )


def build_worker(
    settings: Settings,
    processor: DocumentProcessor | None = None,
    embedder: Embedder | None = None,
) -> Worker:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    amqp = AmqpConnection(settings.rabbitmq_url, connect_timeout=settings.health_check_timeout)
    topology = Topology(settings.amqp_prefix, settings.ingest_retry_delay_ms)
    # Only an embedder built here is ours to close; a passed-in one belongs to the caller.
    own_embedder: OllamaEmbedder | None = None
    if processor is None:
        if embedder is None:
            embedder = own_embedder = _embedder(settings)
        processor = _pipeline(settings, sessions, embedder)
    service = IngestionService(
        SqlDocumentRepository(sessions),
        processor,
        AmqpPublisher(amqp, topology),
        max_attempts=settings.ingest_max_attempts,
    )
    consumer = IngestConsumer(
        amqp,
        topology,
        logged(service.handle),
        max_crashes=settings.ingest_max_attempts,
        prefetch=settings.worker_prefetch,
    )

    async def close() -> None:
        await amqp.close()
        if own_embedder is not None:
            await own_embedder.aclose()
        await engine.dispose()

    return Worker(service, consumer, close)


def _pipeline(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    embedder: Embedder,
) -> IngestionPipeline:
    storage = LocalFileStorage(settings.storage_dir)
    loaders: dict[SourceType, DocumentLoader] = {
        SourceType.PDF: StoredFileLoader(storage, parse_pdf),
        SourceType.MARKDOWN: StoredFileLoader(storage, parse_markdown),
        SourceType.HTML: StoredFileLoader(storage, parse_html),
        SourceType.URL: UrlLoader(
            max_bytes=settings.max_upload_bytes,
            timeout=settings.url_fetch_timeout_seconds,
            deadline=settings.url_fetch_deadline_seconds,
        ),
    }
    chunker = Chunker(
        max_chars=settings.chunk_max_chars,
        overlap_chars=settings.chunk_overlap_chars,
        min_chars=settings.chunk_min_chars,
    )
    return IngestionPipeline(loaders, chunker, embedder, SqlChunkRepository(sessions))


def _embedder(settings: Settings) -> OllamaEmbedder:
    return OllamaEmbedder(
        settings.ollama_url,
        settings.embedding_model,
        dimension=settings.embedding_dimension,
        batch_size=settings.embed_batch_size,
        timeout=settings.ollama_timeout_seconds,
    )
