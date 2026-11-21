"""Asks the eval set through a running stack's HTTP API, the way a user's browser does."""

import asyncio
import json
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import httpx

from fontes.eval.cases import Case
from fontes.eval.scoring import CaseResult, Outcome, score

NO_VERDICT = "the stream ended without a verdict"

# What one /ask stream gave: answer, label, cited titles, error, and the stored question id.
type _Streamed = tuple[str, str | None, tuple[str, ...], str | None, str | None]


class StackError(RuntimeError):
    """The stack cannot be evaluated as it is; the message says why and is shown as is."""


class EvalClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        ready_timeout: float = 300.0,
        ask_timeout: float = 600.0,
        poll_seconds: float = 1.0,
    ) -> None:
        self._base_url = base_url
        self._ready_timeout = ready_timeout
        self._ask_timeout = ask_timeout
        self._poll_seconds = poll_seconds
        self._http = httpx.AsyncClient(base_url=base_url, timeout=30.0, transport=transport)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._http.aclose()

    async def prepare(self, samples_dir: Path) -> None:
        """Check the stack holds only the samples, upload the missing ones, wait until ready."""
        samples = await asyncio.to_thread(_read_samples, samples_dir)
        names = set(samples)
        try:
            docs = await self._documents()
            foreign = sorted(d["title"] for d in docs if d["title"] not in names)
            if foreign:
                raise StackError(
                    f"the eval needs a stack holding only the samples in {samples_dir}; "
                    f"it also holds: {', '.join(foreign)}. "
                    "Delete them, or point --base-url at a fresh stack"
                )
            present = {d["title"] for d in docs}
            for name, data in samples.items():
                if name not in present:
                    await self._upload(name, data)
            await self._wait_ready(names)
        except httpx.TransportError as exc:
            raise StackError(f"cannot reach the API at {self._base_url}: {exc}") from exc

    async def ask(self, question: str) -> tuple[Outcome, str | None, str | None]:
        """One question through `POST /ask`, plus the provider and model it was stored with."""
        started = time.monotonic()
        qid: str | None = None
        try:
            answer, label, titles, error, qid = await self._stream(question)
        except httpx.HTTPError as exc:
            answer, label, titles, error = "", None, (), f"{type(exc).__name__}: {exc}"
        except (ValueError, KeyError, TypeError) as exc:
            answer, label, titles, error = "", None, (), f"malformed event: {exc!r}"
        outcome = Outcome(answer, label, titles, error, time.monotonic() - started)
        provider, model = await self._stored(qid) if qid else (None, None)
        return outcome, provider, model

    async def _documents(self) -> list[dict[str, Any]]:
        response = await self._http.get("/documents")
        not_api = f"{self._base_url} does not look like the Fontes API"
        if response.is_error:
            raise StackError(f"{not_api}: {_detail(response)}")
        try:
            docs = response.json()
        except ValueError:
            raise StackError(f"{not_api}: GET /documents did not return JSON") from None
        if not isinstance(docs, list) or not all(
            isinstance(d, dict) and {"title", "status"} <= d.keys() for d in docs
        ):
            raise StackError(f"{not_api}: GET /documents did not return a list of documents")
        return docs

    async def _upload(self, name: str, data: bytes) -> None:
        files = {"file": (name, data, "text/markdown")}
        response = await self._http.post("/documents", files=files)
        if response.is_error:
            raise StackError(f"uploading {name} failed: {_detail(response)}")

    async def _wait_ready(self, names: set[str]) -> None:
        deadline = time.monotonic() + self._ready_timeout
        while True:
            samples = [d for d in await self._documents() if d["title"] in names]
            for doc in samples:
                if doc["status"] == "failed":
                    raise StackError(
                        f"{doc['title']} failed: {doc['error']}; delete it and run again"
                    )
            waiting = sorted(d["title"] for d in samples if d["status"] != "ready")
            if not waiting:
                return
            if time.monotonic() >= deadline:
                raise StackError(
                    f"not ready after {self._ready_timeout:.0f} s: {', '.join(waiting)}"
                )
            await asyncio.sleep(self._poll_seconds)

    async def _stream(self, question: str) -> _Streamed:
        """Reads the SSE answer up to its verdict or error event."""
        async with self._http.stream(
            "POST", "/ask", json={"question": question}, timeout=self._ask_timeout
        ) as response:
            if response.is_error:
                await response.aread()
                return "", None, (), _detail(response), None
            event, data = "message", ""
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                elif not line and data:
                    if streamed := _event(event, json.loads(data)):
                        return streamed
                    event, data = "message", ""
        return "", None, (), NO_VERDICT, None

    async def _stored(self, question_id: str) -> tuple[str | None, str | None]:
        """Best effort: the answer counts even when its history lookup fails."""
        try:
            response = await self._http.get(f"/questions/{question_id}")
            body = response.json() if not response.is_error else {}
        except (httpx.HTTPError, ValueError):
            return None, None
        if not isinstance(body, dict):
            return None, None
        return body.get("provider"), body.get("model")


async def run(
    cases: list[Case], client: EvalClient
) -> tuple[list[CaseResult], str | None, str | None]:
    """Asks the cases one at a time, in file order. Provider and model: the first pair seen."""
    results: list[CaseResult] = []
    provider: str | None = None
    model: str | None = None
    for case in cases:
        outcome, p, m = await client.ask(case.question)
        if provider is None and p is not None:
            provider, model = p, m
        results.append(score(case, outcome))
    return results, provider, model


def _read_samples(samples_dir: Path) -> dict[str, bytes]:
    """The sample Markdown files by name, in name order."""
    return {p.name: p.read_bytes() for p in sorted(samples_dir.glob("*.md"))}


def _event(event: str, data: dict[str, Any]) -> _Streamed | None:
    if event == "verdict":
        answer = "\n\n".join(p["text"] for p in data["paragraphs"])
        titles = tuple(dict.fromkeys(c["document_title"] for c in data["citations"]))
        return answer, data["label"], titles, None, data["question_id"]
    if event == "error":
        return "", None, (), str(data["detail"]), None
    return None


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    return f"HTTP {response.status_code}: {detail if detail is not None else response.text}"
