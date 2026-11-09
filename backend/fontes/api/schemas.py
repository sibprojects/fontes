from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from fontes.domain.chunks import Chunk
from fontes.domain.documents import Document


class DocumentOut(BaseModel):
    id: UUID
    title: str
    source_type: str
    status: str
    url: str | None
    error: str | None
    attempts: int
    created_at: datetime

    @classmethod
    def from_domain(cls, doc: Document) -> "DocumentOut":
        return cls(
            id=doc.id,
            title=doc.title,
            source_type=doc.source_type.value,
            status=doc.status.value,
            url=doc.url,
            error=doc.error,
            attempts=doc.attempts,
            created_at=doc.created_at,
        )


class UrlIn(BaseModel):
    url: str


class ChunkOut(BaseModel):
    ordinal: int
    location: str
    text: str

    @classmethod
    def from_domain(cls, chunk: Chunk, total: int) -> "ChunkOut":
        return cls(ordinal=chunk.ordinal, location=chunk.location_label(total), text=chunk.text)
