import json

import httpx
import pytest

from fontes.adapters.embeddings.ollama import OllamaEmbedder
from fontes.application.ports.ingestion import PermanentIngestionError


def _embedder(
    handler: httpx.MockTransport, batch_size: int = 16, dimension: int = 3
) -> OllamaEmbedder:
    return OllamaEmbedder(
        "http://ollama.test",
        "bge-m3",
        dimension=dimension,
        batch_size=batch_size,
        timeout=5.0,
        transport=handler,
    )


async def test_embeds_in_batches_preserving_order() -> None:
    bodies: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.url.path == "/api/embed"
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, json={"embeddings": [[float(t), 0, 0] for t in body["input"]]})

    embedder = _embedder(httpx.MockTransport(handle), batch_size=2)
    result = await embedder.embed(["1", "2", "3", "4", "5"])
    await embedder.aclose()
    assert [b["input"] for b in bodies] == [["1", "2"], ["3", "4"], ["5"]]
    assert all(b["model"] == "bge-m3" for b in bodies)
    assert [v[0] for v in result] == [1.0, 2.0, 3.0, 4.0, 5.0]


async def test_empty_input_makes_no_request() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    assert await _embedder(httpx.MockTransport(handle)).embed([]) == []


async def test_model_missing_raises_clear_error() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": 'model "bge-m3" not found, try pulling it first'})

    with pytest.raises(RuntimeError, match="ollama pull bge-m3"):
        await _embedder(httpx.MockTransport(handle)).embed(["a"])


async def test_wrong_dimension_raises() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]})

    with pytest.raises(RuntimeError, match="dimension"):
        await _embedder(httpx.MockTransport(handle), dimension=1024).embed(["a"])


async def test_wrong_vector_count_raises() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]})

    with pytest.raises(RuntimeError, match="2 texts"):
        await _embedder(httpx.MockTransport(handle)).embed(["a", "b"])


async def test_connection_error_is_transient_and_names_ollama() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("All connection attempts failed", request=request)

    with pytest.raises(
        ConnectionError, match=r"Cannot reach Ollama at http://ollama\.test"
    ) as info:
        await _embedder(httpx.MockTransport(handle)).embed(["a"])
    assert not isinstance(info.value, PermanentIngestionError)
    assert isinstance(info.value.__cause__, httpx.ConnectError)


async def test_server_error_is_not_permanent() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(Exception) as info:
        await _embedder(httpx.MockTransport(handle)).embed(["a"])
    assert not isinstance(info.value, PermanentIngestionError)


async def test_timeout_is_transient_and_names_ollama() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(TimeoutError, match="Ollama at http://ollama.test"):
        await _embedder(httpx.MockTransport(handle)).embed(["a"])
