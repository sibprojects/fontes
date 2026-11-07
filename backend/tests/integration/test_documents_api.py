import asyncio
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from fontes.adapters.messaging.connection import AmqpConnection
from fontes.adapters.persistence.documents import SqlDocumentRepository
from fontes.config import Settings
from fontes.container import build_app

pytestmark = pytest.mark.integration


async def test_upload_list_delete_through_real_wiring(
    repo: SqlDocumentRepository, settings: Settings, tmp_path: Path
) -> None:
    app = build_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        r = await c.post("/documents", files={"file": ("notes.md", b"# hi", "text/markdown")})
        assert r.status_code == 201
        doc_id = r.json()["id"]
        assert (tmp_path / f"{doc_id}.md").read_bytes() == b"# hi"
        assert (await c.post("/documents", files={"file": ("x.md", b"# hi")})).status_code == 200
        assert [d["id"] for d in (await c.get("/documents")).json()] == [doc_id]
        assert (await c.delete(f"/documents/{doc_id}")).status_code == 204
    assert not (tmp_path / f"{doc_id}.md").exists()
    assert await repo.list() == []


async def test_concurrent_identical_uploads_never_fail(
    repo: SqlDocumentRepository, settings: Settings, tmp_path: Path
) -> None:
    app = build_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        rs = await asyncio.gather(
            *(c.post("/documents", files={"file": (f"{i}.md", b"# same")}) for i in range(5))
        )
    assert sorted(r.status_code for r in rs) == [200, 200, 200, 200, 201]
    assert len({r.json()["id"] for r in rs}) == 1
    assert len(await asyncio.to_thread(lambda: list(tmp_path.iterdir()))) == 1


async def test_new_upload_publishes_one_ingest_message(
    repo: SqlDocumentRepository, settings: Settings
) -> None:
    app = build_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        first = await c.post("/documents", files={"file": ("a.md", b"# a")})
        await c.post("/documents", files={"file": ("b.md", b"# a")})  # duplicate
    connection = AmqpConnection(settings.rabbitmq_url, connect_timeout=3.0)
    try:
        channel = await (await connection.get()).channel()
        queue = await channel.declare_queue(f"{settings.amqp_prefix}.ingest", passive=True)
        message = await queue.get(no_ack=True, fail=False)
        assert message is not None
        assert json.loads(message.body) == {"document_id": first.json()["id"]}
        assert await queue.get(no_ack=True, fail=False) is None
    finally:
        await connection.close()
