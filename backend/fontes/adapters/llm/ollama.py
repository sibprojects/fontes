import json
from collections.abc import AsyncIterator
from typing import Any

import httpx


class OllamaLLM:
    """Streams a chat answer from Ollama's `/api/chat` (NDJSON, one message piece per line)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        num_ctx: int,
        temperature: float,
        max_tokens: int,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        # Ollama's default context window is small; the sources would be cut off silently.
        # num_predict: a model stuck in a loop would otherwise stream for ever; the httpx
        # timeout is per read and never trips while tokens keep coming.
        self._options = {"num_ctx": num_ctx, "temperature": temperature, "num_predict": max_tokens}
        self._max_tokens = max_tokens
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)

    @property
    def provider(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self._model

    async def aclose(self) -> None:
        await self._client.aclose()

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        request = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": True,
            "options": self._options,
        }
        try:
            async with self._client.stream("POST", "/api/chat", json=request) as response:
                if response.is_error:
                    await response.aread()
                    raise self._http_error(response)
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    data: Any = json.loads(line)
                    if "error" in data:
                        raise RuntimeError(f"Ollama: {data['error']}")
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if data.get("done"):
                        if data.get("done_reason") == "length":
                            raise RuntimeError(
                                f"The answer was cut off at {self._max_tokens} tokens "
                                "(LLM_MAX_TOKENS); try a narrower question"
                            )
                        return
        except httpx.TimeoutException as exc:
            raise TimeoutError(
                f"Ollama at {self._client.base_url} did not answer in time ({exc!r})"
            ) from exc
        except httpx.TransportError as exc:
            raise ConnectionError(f"Cannot reach Ollama at {self._client.base_url}: {exc}") from exc

    def _http_error(self, response: httpx.Response) -> RuntimeError:
        error = _error(response)
        if response.status_code == 404 and "not found" in error:
            return RuntimeError(
                f"Chat model {self._model!r} is not available in Ollama; "
                f"run `ollama pull {self._model}`"
            )
        return RuntimeError(f"Ollama returned HTTP {response.status_code}: {error}")


def _error(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return response.text
    return str(body.get("error", "")) if isinstance(body, dict) else response.text
