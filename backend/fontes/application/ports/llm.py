from collections.abc import AsyncIterator
from typing import Protocol


class LLMProvider(Protocol):
    """A chat model that streams its answer. Any failure is raised as an exception."""

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    def stream(self, system: str, user: str) -> AsyncIterator[str]:
        """The answer's text, piece by piece, as the model produces it."""
        ...
