import builtins
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fontes.adapters.persistence.models import QuestionRow
from fontes.domain.answers import Answer, AnswerLabel, Citation, Paragraph


def _to_row(answer: Answer) -> QuestionRow:
    return QuestionRow(
        id=answer.id,
        question=answer.question,
        answer=answer.text,
        label=answer.label.value,
        paragraphs=[{"text": p.text, "citations": list(p.citations)} for p in answer.paragraphs],
        citations=[
            {
                "n": c.n,
                "document_id": str(c.document_id),
                "document_title": c.document_title,
                "location": c.location,
                "url": c.url,
                "excerpt": c.excerpt,
            }
            for c in answer.citations
        ],
        provider=answer.provider,
        model=answer.model,
        duration_ms=answer.duration_ms,
        created_at=answer.created_at,
    )


def _citation(data: dict[str, Any]) -> Citation:
    return Citation(
        n=data["n"],
        document_id=UUID(data["document_id"]),
        document_title=data["document_title"],
        location=data["location"],
        url=data["url"],
        excerpt=data["excerpt"],
    )


def _to_domain(row: QuestionRow) -> Answer:
    return Answer(
        id=row.id,
        question=row.question,
        text=row.answer,
        paragraphs=tuple(Paragraph(p["text"], tuple(p["citations"])) for p in row.paragraphs),
        label=AnswerLabel(row.label),
        citations=tuple(_citation(c) for c in row.citations),
        provider=row.provider,
        model=row.model,
        duration_ms=row.duration_ms,
        created_at=row.created_at,
    )


class SqlQuestionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def add(self, answer: Answer) -> None:
        async with self._sessions.begin() as session:
            session.add(_to_row(answer))

    async def get(self, id: UUID) -> Answer | None:
        async with self._sessions() as session:
            row = await session.get(QuestionRow, id)
            return None if row is None else _to_domain(row)

    async def list(self, limit: int) -> builtins.list[Answer]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(QuestionRow).order_by(QuestionRow.created_at.desc()).limit(limit)
            )
            return [_to_domain(r) for r in rows]
