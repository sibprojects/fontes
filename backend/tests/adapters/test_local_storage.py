from pathlib import Path

import pytest

from fontes.adapters.storage.local import LocalFileStorage


async def test_save_and_delete(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    await storage.save("k.pdf", b"data")
    assert (tmp_path / "k.pdf").read_bytes() == b"data"
    await storage.delete("k.pdf")
    assert not (tmp_path / "k.pdf").exists()


async def test_delete_missing_is_noop(tmp_path: Path) -> None:
    await LocalFileStorage(tmp_path).delete("nope.pdf")


@pytest.mark.parametrize("key", ["../x", "a/b", r"a\b", "..", ""])
async def test_rejects_path_traversal_keys(tmp_path: Path, key: str) -> None:
    storage = LocalFileStorage(tmp_path / "root")
    with pytest.raises(ValueError):
        await storage.save(key, b"x")
    with pytest.raises(ValueError):
        await storage.delete(key)
    assert not (tmp_path / "x").exists()


async def test_creates_root_lazily(tmp_path: Path) -> None:
    root = tmp_path / "nested"
    storage = LocalFileStorage(root)
    assert not root.exists()
    await storage.save("k.md", b"# hi")
    assert (root / "k.md").read_bytes() == b"# hi"


async def test_read_returns_saved_bytes(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    await storage.save("k.md", b"# hi")
    assert await storage.read("k.md") == b"# hi"


async def test_read_missing_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        await LocalFileStorage(tmp_path).read("nope.md")
