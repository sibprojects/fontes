import asyncio
from pathlib import Path


class LocalFileStorage:
    """Stores each file flat under `root`; keys are plain file names, never paths."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        if not key or key in (".", "..") or any(c in key for c in "/\\") or ".." in key:
            raise ValueError(f"Invalid storage key: {key!r}")
        return self._root / key

    async def save(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def write() -> None:
            self._root.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(write)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        await asyncio.to_thread(path.unlink, missing_ok=True)
