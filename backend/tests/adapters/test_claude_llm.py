import json
from collections.abc import Callable

import httpx2
import pytest

from fontes.adapters.llm.claude import ClaudeLLM
from fontes.application.ports.llm import LLMProvider

Event = dict[str, object]


def _sse(*events: Event) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def _start() -> Event:
    return {
        "type": "message_start",
        "message": {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 0},
        },
    }


def _text_block(index: int, *pieces: str) -> list[Event]:
    return [
        {
            "type": "content_block_start",
            "index": index,
            "content_block": {"type": "text", "text": ""},
        },
        *(
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {"type": "text_delta", "text": p},
            }
            for p in pieces
        ),
        {"type": "content_block_stop", "index": index},
    ]


def _end(stop_reason: str, stop_details: Event | None = None) -> list[Event]:
    delta: Event = {"stop_reason": stop_reason, "stop_sequence": None}
    if stop_details is not None:
        delta["stop_details"] = stop_details
    return [
        {"type": "message_delta", "delta": delta, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ]


def _message(
    *pieces: str, stop_reason: str = "end_turn", stop_details: Event | None = None
) -> bytes:
    return _sse(_start(), *_text_block(0, *pieces), *_end(stop_reason, stop_details))


def _ok(body: bytes) -> Callable[[httpx2.Request], httpx2.Response]:
    return lambda _: httpx2.Response(
        200, headers={"content-type": "text/event-stream"}, content=body
    )


def _error(status: int, kind: str, message: str) -> Callable[[httpx2.Request], httpx2.Response]:
    body = {"type": "error", "error": {"type": kind, "message": message}}
    return lambda _: httpx2.Response(status, json=body)


def _llm(handle: Callable[[httpx2.Request], httpx2.Response], max_tokens: int = 8000) -> ClaudeLLM:
    return ClaudeLLM(
        "k",
        "claude-opus-5-5",
        "low",
        max_tokens,
        5.0,
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    )


async def _collect(llm: ClaudeLLM) -> list[str]:
    try:
        return [piece async for piece in llm.stream("sys", "user")]
    finally:
        await llm.aclose()


async def test_streams_text_and_sends_the_request() -> None:
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return _ok(_message("Hel", "lo [1]."))(request)

    llm = _llm(handle)
    provider: LLMProvider = llm
    assert provider.provider == "claude"
    assert provider.model == "claude-opus-5-5"
    assert await _collect(llm) == ["Hel", "lo [1]."]

    (request,) = seen
    body = json.loads(request.content)
    assert body["system"] == "sys"
    assert body["messages"] == [{"role": "user", "content": "user"}]
    assert body["output_config"] == {"effort": "low"}
    assert body["fallbacks"] == "default"
    assert body["max_tokens"] == 8000
    assert "temperature" not in body
    assert "thinking" not in body
    assert "server-side-fallback-2026-07-01" in request.headers["anthropic-beta"]


async def test_thinking_is_not_part_of_the_answer() -> None:
    thinking: list[Event] = [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": "", "signature": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "Let me look at source 1."},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "signature_delta", "signature": "s"},
        },
        {"type": "content_block_stop", "index": 0},
    ]
    body = _sse(_start(), *thinking, *_text_block(1, "Answer [1]."), *_end("end_turn"))
    assert await _collect(_llm(_ok(body))) == ["Answer [1]."]


async def test_401_names_the_key() -> None:
    llm = _llm(_error(401, "authentication_error", "invalid x-api-key"))
    with pytest.raises(RuntimeError, match=r"ANTHROPIC_API_KEY.*401.*invalid x-api-key"):
        await _collect(llm)


async def test_status_error_carries_status_and_message() -> None:
    llm = _llm(_error(529, "overloaded_error", "Overloaded"))
    with pytest.raises(RuntimeError, match="HTTP 529: Overloaded"):
        await _collect(llm)


async def test_error_event_mid_stream() -> None:
    error: Event = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
    body = _sse(_start(), *_text_block(0, "Partial")[:2], error)
    with pytest.raises(RuntimeError, match="Overloaded"):
        await _collect(_llm(_ok(body)))


async def test_refusal_is_an_error() -> None:
    details: Event = {"type": "refusal", "category": "cyber", "explanation": "x"}
    body = _message("I", stop_reason="refusal", stop_details=details)
    with pytest.raises(RuntimeError, match=r"declined.*cyber"):
        await _collect(_llm(_ok(body)))


async def test_max_tokens_is_an_error() -> None:
    body = _message("A long", stop_reason="max_tokens")
    with pytest.raises(RuntimeError, match=r"cut off at 50 tokens.*CLAUDE_MAX_TOKENS"):
        await _collect(_llm(_ok(body), max_tokens=50))


async def test_unreachable_api_is_a_connection_error() -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(ConnectionError, match="Cannot reach the Claude API"):
        await _collect(_llm(handle))


async def test_timeout_is_a_timeout_error() -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    with pytest.raises(TimeoutError, match="did not answer in time"):
        await _collect(_llm(handle))
