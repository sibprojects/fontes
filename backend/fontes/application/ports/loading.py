from typing import Protocol

from fontes.domain.chunks import Segment
from fontes.domain.documents import Document


class DocumentLoader(Protocol):
    async def load(self, doc: Document) -> list[Segment]:
        """The document's text, with locations; PermanentIngestionError for unreadable input."""
        ...
