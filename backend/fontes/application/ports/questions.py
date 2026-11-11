import builtins
from typing import Protocol
from uuid import UUID

from fontes.domain.answers import Answer


class QuestionRepository(Protocol):
    """History of asked questions and their verified answers."""

    async def add(self, answer: Answer) -> None: ...

    async def get(self, id: UUID) -> Answer | None: ...

    async def list(self, limit: int) -> builtins.list[Answer]:
        """The newest `limit` answers, newest first."""
        ...
