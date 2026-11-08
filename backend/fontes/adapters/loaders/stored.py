import asyncio
from collections.abc import Callable

from fontes.application.ports.documents import FileStorage
from fontes.application.ports.ingestion import PermanentIngestionError
from fontes.domain.chunks import Segment
from fontes.domain.documents import Document


class StoredFileLoader:
    """Loads an uploaded file from storage and parses it off the event loop."""

    def __init__(self, storage: FileStorage, parse: Callable[[bytes], list[Segment]]) -> None:
        self._storage = storage
        self._parse = parse

    async def load(self, doc: Document) -> list[Segment]:
        if doc.storage_key is None:
            raise PermanentIngestionError("The document has no stored file")
        try:
            data = await self._storage.read(doc.storage_key)
        except FileNotFoundError as exc:
            raise PermanentIngestionError("The uploaded file is missing from storage") from exc
        return await asyncio.to_thread(self._parse, data)
