from uuid import UUID

from fastapi import APIRouter, Request, Response, UploadFile, status

from fontes.api.schemas import ChunkOut, DocumentOut, UrlIn
from fontes.application.documents import AddResult, DocumentService, FileTooLargeError
from fontes.domain.documents import Document

router = APIRouter(prefix="/documents", tags=["documents"])


def _service(request: Request) -> DocumentService:
    service: DocumentService = request.app.state.documents
    return service


def _out(doc: Document, request: Request) -> DocumentOut:
    max_attempts: int = request.app.state.max_attempts
    return DocumentOut.from_domain(doc, max_attempts)


def _added(result: AddResult, request: Request, response: Response) -> DocumentOut:
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return _out(result.document, request)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Same content was already uploaded"}},
)
async def upload(file: UploadFile, request: Request, response: Response) -> DocumentOut:
    limit: int = request.app.state.max_upload_bytes
    # Never hold more than limit + 1 bytes in memory, whatever the client sent.
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise FileTooLargeError(f"The file exceeds the {limit}-byte limit")
    result = await _service(request).upload(file.filename or "", data)
    return _added(result, request, response)


@router.post(
    "/url",
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "The URL was already added"}},
)
async def add_url(body: UrlIn, request: Request, response: Response) -> DocumentOut:
    return _added(await _service(request).add_url(body.url), request, response)


@router.get("")
async def list_documents(request: Request) -> list[DocumentOut]:
    return [_out(d, request) for d in await _service(request).list()]


@router.get("/{document_id}/chunks")
async def list_chunks(document_id: UUID, request: Request) -> list[ChunkOut]:
    chunks = await _service(request).list_chunks(document_id)
    return [ChunkOut.from_domain(c, len(chunks)) for c in chunks]


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(document_id: UUID, request: Request) -> None:
    await _service(request).delete(document_id)
