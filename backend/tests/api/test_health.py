import asyncio
import time

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from fontes.api.app import create_app
from fontes.application.documents import DocumentService
from fontes.application.ports.health import HealthCheck
from tests.fakes import (
    FakePublisher,
    InMemoryChunkRepository,
    InMemoryDocumentRepository,
    InMemoryFileStorage,
    fake_ask_service,
)


class OkCheck:
    def __init__(self, name: str) -> None:
        self.name = name

    async def check(self) -> None:
        return None


class FailCheck:
    def __init__(self, name: str, msg: str) -> None:
        self.name = name
        self.msg = msg

    async def check(self) -> None:
        raise RuntimeError(self.msg)


class SlowCheck:
    def __init__(self, name: str) -> None:
        self.name = name

    async def check(self) -> None:
        await asyncio.sleep(10)


def health_app(checks: list[HealthCheck], health_timeout: float) -> FastAPI:
    repo = InMemoryDocumentRepository()
    service = DocumentService(
        repo, InMemoryFileStorage(), InMemoryChunkRepository(repo), FakePublisher(), 100
    )
    return create_app(
        checks,
        health_timeout,
        documents=service,
        max_upload_bytes=100,
        ask=fake_ask_service(repo),
        question_max_chars=2000,
    )


def client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_health_ok() -> None:
    app = health_app([OkCheck("database"), OkCheck("rabbitmq")], health_timeout=1.0)
    async with client(app) as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "checks": {"database": "ok", "rabbitmq": "ok"}}


async def test_health_reports_failing_check() -> None:
    app = health_app(
        [OkCheck("database"), FailCheck("rabbitmq", "connection refused")], health_timeout=1.0
    )
    async with client(app) as c:
        r = await c.get("/health")
    assert r.status_code == 503
    assert r.json() == {
        "status": "fail",
        "checks": {"database": "ok", "rabbitmq": "connection refused"},
    }


async def test_health_times_out_slow_check() -> None:
    app = health_app([SlowCheck("database")], health_timeout=0.1)
    started = time.monotonic()
    async with client(app) as c:
        r = await c.get("/health")
    assert time.monotonic() - started < 1.0
    assert r.status_code == 503
    assert r.json()["checks"]["database"] == "timeout"
