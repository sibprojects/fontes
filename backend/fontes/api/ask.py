import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from fontes.api import sse
from fontes.api.schemas import AnswerOut, AskIn, CitationOut, ParagraphOut, QuestionSummaryOut
from fontes.application.asking import AskService, TokenEvent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ask"])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _service(request: Request) -> AskService:
    service: AskService = request.app.state.ask
    return service


@router.post(
    "/ask",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "token* → verdict"}},
)
async def ask(body: AskIn, request: Request) -> StreamingResponse:
    question = body.question.strip()
    limit: int = request.app.state.question_max_chars
    if not question:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The question is empty")
    if len(question) > limit:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The question is longer than {limit} characters",
        )
    return StreamingResponse(
        _events(_service(request), question),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


async def _events(service: AskService, question: str) -> AsyncIterator[str]:
    # The response has already started, so a failure can only be reported as an event.
    try:
        async for item in service.ask(question):
            if isinstance(item, TokenEvent):
                yield sse.event("token", {"text": item.text})
            else:
                answer = item.answer
                yield sse.event(
                    "verdict",
                    {
                        "question_id": str(answer.id),
                        "label": answer.label.value,
                        "paragraphs": [
                            ParagraphOut.from_domain(p).model_dump(mode="json")
                            for p in answer.paragraphs
                        ],
                        "citations": [
                            CitationOut.from_domain(c).model_dump(mode="json")
                            for c in answer.citations
                        ],
                    },
                )
    except Exception as exc:
        logger.exception("Answering a question failed")
        yield sse.event("error", {"detail": str(exc) or type(exc).__name__})


@router.get("/questions")
async def list_questions(request: Request) -> list[QuestionSummaryOut]:
    return [QuestionSummaryOut.from_domain(a) for a in await _service(request).history()]


@router.get("/questions/{question_id}")
async def get_question(question_id: UUID, request: Request) -> AnswerOut:
    return AnswerOut.from_domain(await _service(request).get(question_id))
