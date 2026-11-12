import json
from collections.abc import Callable

import httpx
import pytest

from fontes.adapters.llm.ollama import OllamaLLM
from fontes.application.ports.llm import LLMProvider
from fontes.config import Settings


def _ndjson(*lines: object) -> bytes:
    return "\n".join(json.dumps(x) for x in lines).encode()


def _llm(handle: Callable[[httpx.Request], httpx.Response]) -> OllamaLLM:
    return OllamaLLM(
        "http://ollama.test",
        "qwen2.5:7b",
        num_ctx=8192,
        temperature=0.1,
        timeout=5.0,
        transport=httpx.MockTransport(handle),
    )


async def _collect(llm: OllamaLLM) -> list[str]:
    try:
        return [piece async for piece in llm.stream("sys", "user")]
    finally:
        await llm.aclose()


async def test_streams_message_content_until_done() -> None:
    body = _ndjson({"message": {"content": "Hel"}}, {"message": {"content": "lo"}}, {"done": True})
    llm = _llm(lambda _: httpx.Response(200, content=body))
    provider: LLMProvider = llm
    assert provider.provider == "ollama"
    assert provider.model == "qwen2.5:7b"
    assert await _collect(llm) == ["Hel", "lo"]


async def test_request_sends_num_ctx_and_temperature() -> None:
    seen: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.url.path == "/api/chat"
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=_ndjson({"done": True}))

    await _collect(_llm(handle))
    (body,) = seen
    assert body["model"] == "qwen2.5:7b"
    assert body["options"] == {"num_ctx": 8192, "temperature": 0.1}
    assert body["stream"] is True
    messages = body["messages"]
    assert isinstance(messages, list)
    assert [m["role"] for m in messages] == ["system", "user"]
    assert [m["content"] for m in messages] == ["sys", "user"]


async def test_empty_content_is_skipped() -> None:
    body = _ndjson({"message": {"content": ""}}, {"done": True})
    assert await _collect(_llm(lambda _: httpx.Response(200, content=body))) == []


async def test_blank_lines_are_skipped() -> None:
    body = b"\n" + _ndjson({"message": {"content": "a"}}) + b"\n\n" + _ndjson({"done": True})
    assert await _collect(_llm(lambda _: httpx.Response(200, content=body))) == ["a"]


async def test_model_missing_raises_clear_error() -> None:
    error = {"error": 'model "qwen2.5:7b" not found, try pulling it first'}
    llm = _llm(lambda _: httpx.Response(404, json=error))
    with pytest.raises(RuntimeError, match="ollama pull qwen2.5:7b"):
        await _collect(llm)


async def test_other_http_error_names_status() -> None:
    llm = _llm(lambda _: httpx.Response(500, json={"error": "boom"}))
    with pytest.raises(RuntimeError, match="Ollama returned HTTP 500: boom"):
        await _collect(llm)


async def test_error_line_mid_stream_raises() -> None:
    body = _ndjson({"message": {"content": "a"}}, {"error": "out of memory"})
    llm = _llm(lambda _: httpx.Response(200, content=body))
    pieces: list[str] = []
    with pytest.raises(RuntimeError, match="^Ollama: out of memory$"):
        async for piece in llm.stream("sys", "user"):
            pieces.append(piece)
    await llm.aclose()
    assert pieces == ["a"]


async def test_connection_error_names_ollama() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ConnectionError, match="Cannot reach Ollama at http://ollama.test"):
        await _collect(_llm(handle))


async def test_timeout_names_ollama() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(TimeoutError, match="Ollama at http://ollama.test"):
        await _collect(_llm(handle))


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.chat_model == "qwen2.5:7b"
    assert settings.llm_timeout_seconds == 300.0
    assert settings.llm_num_ctx == 8192
    assert settings.llm_temperature == 0.1
    assert settings.ask_top_k == 6
    assert settings.ask_min_score == 0.45
    assert settings.question_max_chars == 2000
