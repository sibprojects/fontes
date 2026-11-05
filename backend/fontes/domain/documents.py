from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePath
from urllib.parse import urlsplit
from uuid import UUID, uuid4


class DocumentStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class SourceType(StrEnum):
    PDF = "pdf"
    MARKDOWN = "markdown"
    HTML = "html"
    URL = "url"


class DocumentError(Exception):
    """Base class for rule violations a user can fix by changing their input."""


class UnsupportedSourceError(DocumentError):
    pass


class InvalidUrlError(DocumentError):
    pass


_EXTENSIONS = {
    ".pdf": SourceType.PDF,
    ".md": SourceType.MARKDOWN,
    ".markdown": SourceType.MARKDOWN,
    ".html": SourceType.HTML,
    ".htm": SourceType.HTML,
}


def _base_name(filename: str) -> str:
    return PurePath(filename.replace("\\", "/")).name


def source_type_for_filename(filename: str) -> SourceType:
    suffix = PurePath(_base_name(filename)).suffix.lower()
    try:
        return _EXTENSIONS[suffix]
    except KeyError:
        supported = ", ".join(_EXTENSIONS)
        raise UnsupportedSourceError(
            f"Unsupported file type {suffix or '(none)'!r}; supported: {supported}"
        ) from None


def normalize_url(url: str) -> str:
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise InvalidUrlError(f"Not an http(s) URL: {url!r}")
    return url


@dataclass(frozen=True)
class Document:
    id: UUID
    title: str
    source_type: SourceType
    status: DocumentStatus
    created_at: datetime
    storage_key: str | None
    content_hash: str | None
    url: str | None
    error: str | None = None
    attempts: int = 0

    @classmethod
    def from_upload(cls, filename: str, content_hash: str, now: datetime) -> "Document":
        source_type = source_type_for_filename(filename)
        title = _base_name(filename)
        doc_id = uuid4()
        return cls(
            id=doc_id,
            title=title,
            source_type=source_type,
            status=DocumentStatus.QUEUED,
            created_at=now,
            storage_key=f"{doc_id}{PurePath(title).suffix.lower()}",
            content_hash=content_hash,
            url=None,
        )

    @classmethod
    def from_url(cls, url: str, now: datetime) -> "Document":
        normalized = normalize_url(url)
        return cls(
            id=uuid4(),
            title=normalized,
            source_type=SourceType.URL,
            status=DocumentStatus.QUEUED,
            created_at=now,
            storage_key=None,
            content_hash=None,
            url=normalized,
        )
