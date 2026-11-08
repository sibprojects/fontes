from collections.abc import Sequence
from typing import Protocol


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, in input order. Any failure is transient."""
        ...
