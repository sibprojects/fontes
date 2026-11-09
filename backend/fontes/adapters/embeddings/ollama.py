from collections.abc import Sequence
from typing import Any

import httpx


class OllamaEmbedder:
    """Embeds text with Ollama's `/api/embed`; every failure is transient and so retried."""

    def __init__(
        self,
        base_url: str,
        model: str,
        dimension: int,
        batch_size: int,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        self._dimension = dimension
        self._batch_size = batch_size
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            vectors.extend(await self._embed_batch(texts[start : start + self._batch_size]))
        return vectors

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = await self._client.post(
                "/api/embed", json={"model": self._model, "input": list(texts)}
            )
        except httpx.TimeoutException as exc:
            raise TimeoutError(
                f"Ollama at {self._client.base_url} did not answer in time ({exc!r})"
            ) from exc
        except httpx.TransportError as exc:
            # The stored error should say which service is down, not just "connection failed".
            raise ConnectionError(f"Cannot reach Ollama at {self._client.base_url}: {exc}") from exc
        if response.status_code == 404 and "not found" in _error(response):
            raise RuntimeError(
                f"Embedding model {self._model!r} is not available in Ollama; "
                f"run `ollama pull {self._model}`"
            )
        response.raise_for_status()
        vectors: list[list[float]] = response.json()["embeddings"]
        if len(vectors) != len(texts):
            raise RuntimeError(f"Ollama returned {len(vectors)} vectors for {len(texts)} texts")
        bad = next((len(v) for v in vectors if len(v) != self._dimension), None)
        if bad is not None:
            raise RuntimeError(
                f"Model {self._model!r} returned vectors of dimension {bad}, "
                f"expected {self._dimension}; a different model needs a new migration"
            )
        return vectors


def _error(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return response.text
    return str(body.get("error", "")) if isinstance(body, dict) else ""
