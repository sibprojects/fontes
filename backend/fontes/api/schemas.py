from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

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
