from uuid import UUID

from fastapi import APIRouter, Request, Response, UploadFile, status

from fontes.api.schemas import DocumentOut, UrlIn
from fontes.application.documents import AddResult, DocumentService, FileTooLargeError

router = APIRouter(prefix="/documents", tags=["documents"])


def _service(request: Request) -> DocumentService:
    service: DocumentService = request.app.state.documents
    return service


def _added(result: AddResult, response: Response) -> DocumentOut:
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return DocumentOut.from_domain(result.document)


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
    return _added(result, response)


@router.post(
    "/url",
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "The URL was already added"}},
)
async def add_url(body: UrlIn, request: Request, response: Response) -> DocumentOut:
    return _added(await _service(request).add_url(body.url), response)


@router.get("")
async def list_documents(request: Request) -> list[DocumentOut]:
    return [DocumentOut.from_domain(d) for d in await _service(request).list()]


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(document_id: UUID, request: Request) -> None:
    await _service(request).delete(document_id)
