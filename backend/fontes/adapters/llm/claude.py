"""Streams a chat answer from the Claude API through the official `anthropic` SDK.

No `temperature` is sent: the API version this SDK speaks (2026-10-21) rejects it. No
`thinking` either: Opus 5.5 always thinks, and `effort` is the one control. Its thinking
blocks are not part of the answer; only text is yielded.

A refused question falls back server-side to another Claude model (`fallbacks: "default"`,
beta `server-side-fallback-2026-07-01`), so a rare false refusal still gets an answer.
"""

from collections.abc import AsyncIterator
from typing import Any, Literal

import anthropic
import httpx2
from anthropic.types.beta import BetaOutputConfigParam

FALLBACK_BETA = "server-side-fallback-2026-07-01"

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class ClaudeLLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        effort: Effort,
        max_tokens: int,
        timeout: float,
        max_retries: int = 2,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._model = model
        self._output_config: BetaOutputConfigParam = {"effort": effort}
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
            http_client=http_client,
        )

    @property
    def provider(self) -> str:
        return "claude"

    @property
    def model(self) -> str:
        return self._model

    async def aclose(self) -> None:
        await self._client.close()

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        try:
            async with self._client.beta.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config=self._output_config,
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
        except anthropic.APITimeoutError as exc:
            raise TimeoutError(
                f"The Claude API did not answer in time ({self._timeout:g} s)"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ConnectionError(f"Cannot reach the Claude API: {exc}") from exc
        except anthropic.AuthenticationError as exc:
            raise RuntimeError(
                f"The Claude API rejected ANTHROPIC_API_KEY (HTTP 401): {_message(exc)}"
            ) from exc
        except anthropic.APIStatusError as exc:
            raise RuntimeError(
                f"The Claude API returned HTTP {exc.status_code}: {_message(exc)}"
            ) from exc
        except anthropic.APIError as exc:
            # An `error` event inside a 200 stream (say, overloaded mid-answer).
            raise RuntimeError(f"The Claude API failed mid-answer: {_message(exc)}") from exc

        if final.stop_reason == "refusal":
            category = final.stop_details.category if final.stop_details else None
            suffix = f" ({category})" if category else ""
            raise RuntimeError(f"Claude declined to answer this question{suffix}")
        if final.stop_reason == "max_tokens":
            raise RuntimeError(
                f"The answer was cut off at {self._max_tokens} tokens (CLAUDE_MAX_TOKENS); "
                "try a narrower question"
            )


def _message(exc: anthropic.APIError) -> str:
    body: Any = exc.body
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return str(error["message"])
    return exc.message
