import asyncio

from fontes.domain.documents import Document


class StubDocumentProcessor:
    """Stands in for parsing and embedding until M4; the delay keeps `processing` visible."""

    def __init__(self, delay_seconds: float) -> None:
        self._delay_seconds = delay_seconds

    async def process(self, doc: Document) -> None:
        await asyncio.sleep(self._delay_seconds)
