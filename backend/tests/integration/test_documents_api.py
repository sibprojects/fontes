import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from fontes.adapters.persistence.documents import SqlDocumentRepository
from fontes.config import Settings
from fontes.container import build_app

pytestmark = pytest.mark.integration


async def test_upload_list_delete_through_real_wiring(
    repo: SqlDocumentRepository, tmp_path: Path
) -> None:
    app = build_app(Settings(storage_dir=tmp_path))
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
    repo: SqlDocumentRepository, tmp_path: Path
) -> None:
    app = build_app(Settings(storage_dir=tmp_path))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        rs = await asyncio.gather(
            *(c.post("/documents", files={"file": (f"{i}.md", b"# same")}) for i in range(5))
        )
    assert sorted(r.status_code for r in rs) == [200, 200, 200, 200, 201]
    assert len({r.json()["id"] for r in rs}) == 1
    assert len(list(tmp_path.iterdir())) == 1
