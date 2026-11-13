from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from fontes.domain.answers import Answer, Citation, Paragraph
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
    # How many attempts ingestion makes before it gives up, for "retry 2/3".
    max_attempts: int
    created_at: datetime

    @classmethod
    def from_domain(cls, doc: Document, max_attempts: int) -> "DocumentOut":
        return cls(
            id=doc.id,
            title=doc.title,
            source_type=doc.source_type.value,
            status=doc.status.value,
            url=doc.url,
            error=doc.error,
            attempts=doc.attempts,
            max_attempts=max_attempts,
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


class AskIn(BaseModel):
    question: str


class ParagraphOut(BaseModel):
    text: str
    supported: bool
    citations: list[int]

    @classmethod
    def from_domain(cls, paragraph: Paragraph) -> "ParagraphOut":
        return cls(
            text=paragraph.text,
            supported=paragraph.supported,
            citations=list(paragraph.citations),
        )


class CitationOut(BaseModel):
    n: int
    document_id: UUID
    document_title: str
    location: str
    url: str | None
    excerpt: str

    @classmethod
    def from_domain(cls, citation: Citation) -> "CitationOut":
        return cls(
            n=citation.n,
            document_id=citation.document_id,
            document_title=citation.document_title,
            location=citation.location,
            url=citation.url,
            excerpt=citation.excerpt,
        )


class AnswerOut(BaseModel):
    id: UUID
    question: str
    answer: str
    label: str
    paragraphs: list[ParagraphOut]
    citations: list[CitationOut]
    provider: str | None
    model: str | None
    duration_ms: int
    created_at: datetime

    @classmethod
    def from_domain(cls, answer: Answer) -> "AnswerOut":
        return cls(
            id=answer.id,
            question=answer.question,
            answer=answer.text,
            label=answer.label.value,
            paragraphs=[ParagraphOut.from_domain(p) for p in answer.paragraphs],
            citations=[CitationOut.from_domain(c) for c in answer.citations],
            provider=answer.provider,
            model=answer.model,
            duration_ms=answer.duration_ms,
            created_at=answer.created_at,
        )


class QuestionSummaryOut(BaseModel):
    id: UUID
    question: str
    label: str
    created_at: datetime

    @classmethod
    def from_domain(cls, answer: Answer) -> "QuestionSummaryOut":
        return cls(
            id=answer.id,
            question=answer.question,
            label=answer.label.value,
            created_at=answer.created_at,
        )
