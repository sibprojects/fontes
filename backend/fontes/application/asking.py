"""Ask: retrieve the closest chunks, let the model answer from them, verify, store."""

import builtins
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fontes.application.ports.chunks import ChunkRepository, SearchHit
from fontes.application.ports.embeddings import Embedder
from fontes.application.ports.llm import LLMProvider
from fontes.application.ports.questions import QuestionRepository
from fontes.application.prompting import build_prompt
from fontes.application.verification import verify
from fontes.domain.answers import Answer, AnswerLabel, Citation, Paragraph

NOT_FOUND_TEXT = "I could not find anything about this in your documents."


class QuestionNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class TokenEvent:
    """Provisional answer text, not verified yet."""

    text: str


@dataclass(frozen=True)
class VerdictEvent:
    """The verified, stored answer."""

    answer: Answer


AskEvent = TokenEvent | VerdictEvent


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AskService:
    def __init__(
        self,
        embedder: Embedder,
        chunks: ChunkRepository,
        llm: LLMProvider,
        questions: QuestionRepository,
        top_k: int,
        min_score: float,
        clock: Callable[[], datetime] = _utc_now,
        timer: Callable[[], float] = time.monotonic,
    ) -> None:
        self._embedder = embedder
        self._chunks = chunks
        self._llm = llm
        self._questions = questions
        self._top_k = top_k
        self._min_score = min_score
        self._clock = clock
        self._timer = timer

    async def ask(self, question: str) -> AsyncIterator[AskEvent]:
        """Stream the answer, then its verdict. Nothing is stored if any step fails."""
        started = self._timer()
        question = question.strip()
        (vector,) = await self._embedder.embed([question])
        hits = [
            h for h in await self._chunks.search(vector, self._top_k) if h.score >= self._min_score
        ]
        if not hits:
            # Nothing relevant: say so, and never let the model answer without sources.
            yield TokenEvent(NOT_FOUND_TEXT)
            answer = self._answer(question, NOT_FOUND_TEXT, AnswerLabel.NOT_FOUND, started)
        else:
            prompt = build_prompt(question, hits)
            pieces: list[str] = []
            async for piece in self._llm.stream(prompt.system, prompt.user):
                pieces.append(piece)
                yield TokenEvent(piece)
            verification = verify("".join(pieces), len(hits))
            cited = sorted({n for p in verification.paragraphs for n in p.citations})
            answer = self._answer(
                question,
                verification.text,
                verification.label,
                started,
                paragraphs=verification.paragraphs,
                citations=tuple(_citation(n, hits[n - 1]) for n in cited),
                generated=True,
            )
        await self._questions.add(answer)
        yield VerdictEvent(answer)

    async def history(self, limit: int = 50) -> builtins.list[Answer]:
        return await self._questions.list(limit)

    async def get(self, id: UUID) -> Answer:
        answer = await self._questions.get(id)
        if answer is None:
            raise QuestionNotFoundError(f"Question {id} not found")
        return answer

    def _answer(
        self,
        question: str,
        text: str,
        label: AnswerLabel,
        started: float,
        paragraphs: tuple[Paragraph, ...] = (),
        citations: tuple[Citation, ...] = (),
        generated: bool = False,
    ) -> Answer:
        return Answer(
            id=uuid4(),
            question=question,
            text=text,
            paragraphs=paragraphs,
            label=label,
            citations=citations,
            provider=self._llm.provider if generated else None,
            model=self._llm.model if generated else None,
            duration_ms=round((self._timer() - started) * 1000),
            created_at=self._clock(),
        )


def _citation(n: int, hit: SearchHit) -> Citation:
    return Citation(
        n=n,
        document_id=hit.document_id,
        document_title=hit.document_title,
        location=hit.chunk.location_label(hit.total_chunks),
        url=hit.document_url,
        excerpt=hit.chunk.text,
    )
