from datetime import UTC, datetime

import pytest

from fontes.domain.documents import (
    Document,
    DocumentStatus,
    InvalidUrlError,
    SourceType,
    UnsupportedSourceError,
    normalize_url,
    source_type_for_filename,
)

T0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.pdf", SourceType.PDF),
        ("a.md", SourceType.MARKDOWN),
        ("a.markdown", SourceType.MARKDOWN),
        ("a.html", SourceType.HTML),
        ("a.htm", SourceType.HTML),
    ],
)
def test_source_type_for_filename(name: str, expected: SourceType) -> None:
    assert source_type_for_filename(name) == expected


def test_source_type_is_case_insensitive() -> None:
    assert source_type_for_filename("отчёт 2026.PDF") == SourceType.PDF


@pytest.mark.parametrize("name", ["a.docx", "a", "pdf", "a.pdf.exe", ""])
def test_unsupported_source(name: str) -> None:
    with pytest.raises(UnsupportedSourceError):
        source_type_for_filename(name)


def test_url_validation() -> None:
    assert normalize_url("  https://example.com/a  ") == "https://example.com/a"
    assert normalize_url("http://example.com") == "http://example.com"
    for bad in [
        "ftp://x.com/a",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "not a url",
        "https://",
    ]:
        with pytest.raises(InvalidUrlError):
            normalize_url(bad)


def test_from_upload() -> None:
    d = Document.from_upload("Report.PDF", "abc", now=T0)
    assert (d.status, d.source_type, d.title, d.content_hash, d.created_at) == (
        DocumentStatus.QUEUED,
        SourceType.PDF,
        "Report.PDF",
        "abc",
        T0,
    )
    assert d.storage_key == f"{d.id}.pdf"
    assert (d.url, d.error, d.attempts) == (None, None, 0)


def test_title_strips_directories() -> None:
    assert Document.from_upload("../../etc/passwd.pdf", "h", now=T0).title == "passwd.pdf"
    assert Document.from_upload(r"C:\docs\a.md", "h", now=T0).title == "a.md"


def test_from_url() -> None:
    d = Document.from_url(" https://example.com/x ", now=T0)
    assert (d.source_type, d.url, d.title, d.storage_key, d.content_hash) == (
        SourceType.URL,
        "https://example.com/x",
        "https://example.com/x",
        None,
        None,
    )
    assert d.status == DocumentStatus.QUEUED
