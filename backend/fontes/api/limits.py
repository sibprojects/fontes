"""Cap the request body of uploads before Starlette spools it to a temp file."""

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MULTIPART_OVERHEAD_BYTES = 64 * 1024
"""Slack for multipart boundaries and part headers on top of the file-size limit."""


class BodySizeLimit:
    """Answer 413 as soon as a POST to `path` declares or streams more than `max_bytes`."""

    def __init__(self, app: ASGIApp, path: str, max_bytes: int) -> None:
        self._app = app
        self._path = path
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != self._path:
            await self._app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self._max_bytes:
            await self._reject(send)
            return

        received = 0
        started = False
        rejected = False

        async def limited_receive() -> Message:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes and not started:
                    # Answer now and tell the app the client is gone, so it stops reading.
                    # (FastAPI turns any exception raised while parsing a form into a 400.)
                    rejected = True
                    await self._reject(send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self._app(scope, limited_receive, guarded_send)
        except Exception:
            if not rejected:
                raise

    async def _reject(self, send: Send) -> None:
        body = json.dumps({"detail": f"The request exceeds the {self._max_bytes}-byte limit"})
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body.encode()})
