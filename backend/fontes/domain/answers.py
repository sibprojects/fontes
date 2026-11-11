from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class AnswerLabel(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    # Nothing relevant was retrieved, so no answer was generated at all.
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class Paragraph:
    """One paragraph or list item of an answer, with the valid source numbers it cites."""

    text: str
    citations: tuple[int, ...]

    @property
    def supported(self) -> bool:
        return bool(self.citations)


@dataclass(frozen=True)
class Citation:
    """A snapshot of a cited source, so history survives the document being deleted."""

    n: int
    document_id: UUID
    document_title: str
    location: str
    url: str | None
    excerpt: str


@dataclass(frozen=True)
class Answer:
    """A question and its verified answer, as stored in history."""

    id: UUID
    question: str
    text: str
    paragraphs: tuple[Paragraph, ...]
    label: AnswerLabel
    citations: tuple[Citation, ...]
    provider: str | None
    model: str | None
    duration_ms: int
    created_at: datetime
