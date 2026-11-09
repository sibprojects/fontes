from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx
import pytest

from fontes.adapters.loaders.url import UrlLoader
from fontes.application.ports.ingestion import PermanentIngestionError
from fontes.domain.chunks import Segment
from fontes.domain.documents import Document

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
PUBLIC = "93.184.215.14"
HTML = {"content-type": "text/html; charset=utf-8"}


def _resolver(*addresses: str) -> Callable[[str], Awaitable[list[str]]]:
    async def resolve(host: str) -> list[str]:
        return list(addresses or (PUBLIC,))

    return resolve


class Recorder:
    """A MockTransport handler that serves canned responses in order and records requests."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _loader(handler: Recorder, *addresses: str, max_bytes: int = 100_000) -> UrlLoader:
    return UrlLoader(
        max_bytes=max_bytes,
        timeout=5.0,
        transport=httpx.MockTransport(handler),
        resolve=_resolver(*addresses),
    )


async def _load(loader: UrlLoader, url: str = "https://example.com/page") -> list[Segment]:
    return await loader.load(Document.from_url(url, now=NOW))


async def test_fetches_and_parses_html() -> None:
    handler = Recorder(httpx.Response(200, headers=HTML, text="<h1>Title</h1><p>Body</p>"))
    assert await _load(_loader(handler)) == [Segment("Title\nBody", section="Title")]
    assert str(handler.requests[0].url) == "https://example.com/page"


async def test_private_address_rejected_before_any_request() -> None:
    handler = Recorder()
    with pytest.raises(PermanentIngestionError, match="private or local"):
        await _load(_loader(handler, "10.0.0.5"))
    assert handler.requests == []


async def test_host_with_any_private_address_rejected() -> None:
    handler = Recorder()
    with pytest.raises(PermanentIngestionError, match="private or local"):
        await _load(_loader(handler, PUBLIC, "192.168.1.1"))
    assert handler.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
    ],
)
async def test_literal_local_addresses_rejected(url: str) -> None:
    handler = Recorder()
    with pytest.raises(PermanentIngestionError, match="private or local"):
        await _load(_loader(handler), url)
    assert handler.requests == []


async def test_redirect_to_private_address_is_refused() -> None:
    handler = Recorder(httpx.Response(302, headers={"location": "http://127.0.0.1/admin"}))
    with pytest.raises(PermanentIngestionError, match="private or local"):
        await _load(_loader(handler))
    assert len(handler.requests) == 1


async def test_redirect_to_other_scheme_is_refused() -> None:
    handler = Recorder(httpx.Response(302, headers={"location": "file:///etc/passwd"}))
    with pytest.raises(PermanentIngestionError, match="scheme"):
        await _load(_loader(handler))
    assert len(handler.requests) == 1


async def test_follows_public_redirect() -> None:
    handler = Recorder(
        httpx.Response(301, headers={"location": "https://www.example.com/new"}),
        httpx.Response(200, headers=HTML, text="<p>Moved</p>"),
    )
    assert await _load(_loader(handler)) == [Segment("Moved")]
    assert str(handler.requests[1].url) == "https://www.example.com/new"


async def test_relative_redirect_is_resolved_against_current_url() -> None:
    handler = Recorder(
        httpx.Response(302, headers={"location": "/other"}),
        httpx.Response(200, headers=HTML, text="<p>Here</p>"),
    )
    await _load(_loader(handler))
    assert str(handler.requests[1].url) == "https://example.com/other"


async def test_too_many_redirects_is_permanent() -> None:
    handler = Recorder(
        *(httpx.Response(302, headers={"location": f"/r{i}"}) for i in range(6)),
    )
    with pytest.raises(PermanentIngestionError, match="redirects"):
        await _load(_loader(handler))
    assert len(handler.requests) == 6


async def test_http_404_is_permanent() -> None:
    handler = Recorder(httpx.Response(404, text="nope"))
    with pytest.raises(PermanentIngestionError, match="HTTP 404"):
        await _load(_loader(handler))


@pytest.mark.parametrize("status", [408, 429, 503])
async def test_retryable_status_is_transient(status: int) -> None:
    handler = Recorder(httpx.Response(status, text="later"))
    with pytest.raises(Exception, match=f"HTTP {status}") as info:
        await _load(_loader(handler))
    assert not isinstance(info.value, PermanentIngestionError)


async def test_non_html_content_type_is_permanent() -> None:
    handler = Recorder(
        httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")
    )
    with pytest.raises(PermanentIngestionError, match="content type"):
        await _load(_loader(handler))


async def test_xhtml_is_accepted() -> None:
    headers = {"content-type": "application/xhtml+xml"}
    handler = Recorder(httpx.Response(200, headers=headers, text="<body><p>x</p></body>"))
    assert await _load(_loader(handler)) == [Segment("x")]


async def test_oversized_page_is_permanent() -> None:
    handler = Recorder(httpx.Response(200, headers=HTML, content=b"a" * 5000))
    with pytest.raises(PermanentIngestionError, match="larger than"):
        await _load(_loader(handler, max_bytes=1000))


async def test_network_error_is_transient() -> None:
    handler = Recorder(httpx.ConnectError("refused"))
    with pytest.raises(httpx.ConnectError):
        await _load(_loader(handler))


async def test_default_resolver_rejects_localhost() -> None:
    handler = Recorder()
    loader = UrlLoader(max_bytes=1000, timeout=5.0, transport=httpx.MockTransport(handler))
    with pytest.raises(PermanentIngestionError, match="private or local"):
        await _load(loader, "http://localhost:8000/health")
    assert handler.requests == []
