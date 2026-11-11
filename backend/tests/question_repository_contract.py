"""Cases every QuestionRepository must pass.

Imported by tests/test_fakes.py (in-memory fake) and by the integration tests (Postgres);
each module provides its own `questions` fixture.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fontes.application.ports.questions import QuestionRepository
from fontes.domain.answers import Answer, AnswerLabel, Citation, Paragraph

T0 = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def make_answer(created_at: datetime = T0, citations: tuple[Citation, ...] | None = None) -> Answer:
    citation = Citation(
        n=1,
        document_id=uuid4(),
        document_title="отчёт.pdf",
        location="pp. 4–5",
        url=None,
        excerpt="Выручка выросла на 12 % «в целом».",
    )
    return Answer(
        id=uuid4(),
        question="Насколько выросла выручка?",
        text="Выручка выросла на 12 % [1].\n\n- Прочее",
        paragraphs=(
            Paragraph("Выручка выросла на 12 % [1].", (1,)),
            Paragraph("- Прочее", ()),
        ),
        label=AnswerLabel.PARTIALLY_SUPPORTED,
        citations=(citation,) if citations is None else citations,
        provider="ollama",
        model="qwen2.5:7b",
        duration_ms=1234,
        created_at=created_at,
    )


async def test_add_then_get_round_trips(questions: QuestionRepository) -> None:
    answer = make_answer()
    await questions.add(answer)
    assert await questions.get(answer.id) == answer


async def test_get_unknown_is_none(questions: QuestionRepository) -> None:
    assert await questions.get(uuid4()) is None


async def test_list_newest_first_with_limit(questions: QuestionRepository) -> None:
    first, second, third = (make_answer(T0 + timedelta(seconds=i)) for i in range(3))
    for answer in (second, third, first):
        await questions.add(answer)
    assert await questions.list(2) == [third, second]


async def test_not_found_answer_round_trips(questions: QuestionRepository) -> None:
    answer = Answer(
        id=uuid4(),
        question="What is the capital of Peru?",
        text="I could not find anything about this in your documents.",
        paragraphs=(),
        label=AnswerLabel.NOT_FOUND,
        citations=(),
        provider=None,
        model=None,
        duration_ms=5,
        created_at=T0,
    )
    await questions.add(answer)
    assert await questions.get(answer.id) == answer
