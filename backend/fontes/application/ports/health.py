from typing import Protocol


class HealthCheck(Protocol):
    """A dependency the app needs. `check` raises on failure."""

    name: str

    async def check(self) -> None: ...
