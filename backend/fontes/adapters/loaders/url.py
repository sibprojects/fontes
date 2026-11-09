import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable

import httpx

from fontes.adapters.loaders.html import parse_html
from fontes.application.ports.ingestion import PermanentIngestionError
from fontes.domain.chunks import Segment
from fontes.domain.documents import Document

MAX_REDIRECTS = 5
_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_RETRYABLE = {408, 429}


async def _getaddrinfo(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


class UrlLoader:
    """Fetches an HTML page, refusing any hop whose host is not a public address.

    Redirects are followed by hand so that every hop is checked before it is requested.
    Known gap: DNS can change between our check and httpx's own lookup (rebinding).
    """

    def __init__(
        self,
        max_bytes: int,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
        resolve: Callable[[str], Awaitable[list[str]]] | None = None,
    ) -> None:
        self._max_bytes = max_bytes
        self._timeout = timeout
        self._transport = transport
        self._resolve = resolve or _getaddrinfo

    async def load(self, doc: Document) -> list[Segment]:
        if doc.url is None:
            raise PermanentIngestionError("The document has no URL")
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, follow_redirects=False
        ) as client:
            body = await self._fetch(client, httpx.URL(doc.url))
        return await asyncio.to_thread(parse_html, body)

    async def _fetch(self, client: httpx.AsyncClient, url: httpx.URL) -> bytes:
        for _ in range(MAX_REDIRECTS + 1):
            await self._check_address(url)
            async with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = url.join(response.headers["location"])
                    continue
                _check_status(response.status_code, url)
                _check_content_type(response.headers.get("content-type", ""))
                return await self._read_limited(response)
        raise PermanentIngestionError(f"Too many redirects (more than {MAX_REDIRECTS})")

    async def _check_address(self, url: httpx.URL) -> None:
        if url.scheme not in ("http", "https"):
            raise PermanentIngestionError(
                f"Only http and https can be fetched, not scheme {url.scheme!r}"
            )
        host = url.host
        addresses = [host] if _is_ip_literal(host) else await self._resolve(host)
        if not addresses:
            raise OSError(f"Could not resolve {host}")
        if not all(_is_public(a) for a in addresses):
            raise PermanentIngestionError(f"Refusing to fetch a private or local address: {host}")

    async def _read_limited(self, response: httpx.Response) -> bytes:
        too_large = PermanentIngestionError(f"The page is larger than {self._max_bytes} bytes")
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self._max_bytes:
            raise too_large
        body = bytearray()
        async for part in response.aiter_bytes():
            body += part
            if len(body) > self._max_bytes:
                raise too_large
        return bytes(body)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])  # drop an IPv6 zone id
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global


def _check_status(status: int, url: httpx.URL) -> None:
    if 200 <= status < 300:
        return
    message = f"HTTP {status} from {url}"
    if status in _RETRYABLE or status >= 500:
        raise RuntimeError(message)
    raise PermanentIngestionError(message)


def _check_content_type(header: str) -> None:
    content_type = header.split(";", 1)[0].strip().lower()
    if content_type not in _HTML_TYPES:
        raise PermanentIngestionError(
            f"Unsupported content type {content_type or '(none)'!r}; only HTML pages can be fetched"
        )
