import io

import pytest
from pypdf import PdfReader, PdfWriter

from fontes.adapters.loaders.pdf import parse_pdf
from fontes.application.ports.ingestion import PermanentIngestionError
from tests.pdf_factory import make_pdf


def test_factory_makes_a_readable_pdf() -> None:
    reader = PdfReader(io.BytesIO(make_pdf(["Alpha (1)", ""])))
    assert len(reader.pages) == 2
    assert reader.pages[0].extract_text() == "Alpha (1)"


def test_one_segment_per_page_with_page_numbers() -> None:
    segments = parse_pdf(make_pdf(["Alpha text", "", "Gamma text"]))
    assert [(s.text, s.page) for s in segments] == [("Alpha text", 1), ("Gamma text", 3)]


def test_corrupt_pdf_is_permanent() -> None:
    with pytest.raises(PermanentIngestionError, match="PDF"):
        parse_pdf(b"%PDF-1.4 garbage")


def test_not_a_pdf_at_all_is_permanent() -> None:
    with pytest.raises(PermanentIngestionError, match="PDF"):
        parse_pdf(b"\x89PNG\r\n\x1a\n")


def test_password_protected_pdf_is_permanent() -> None:
    writer = PdfWriter(clone_from=io.BytesIO(make_pdf(["secret"])))
    writer.encrypt(user_password="pw", owner_password="owner")
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(PermanentIngestionError, match="password"):
        parse_pdf(buffer.getvalue())


def test_pdf_without_text_returns_no_segments() -> None:
    assert parse_pdf(make_pdf(["", ""])) == []


def _encrypted(user_password: str) -> bytes:
    writer = PdfWriter(clone_from=io.BytesIO(make_pdf(["Owner only"])))
    writer.encrypt(user_password=user_password, owner_password="owner", algorithm="AES-256")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_aes_pdf_with_owner_password_only_is_read() -> None:
    assert [s.text for s in parse_pdf(_encrypted(""))] == ["Owner only"]


def test_aes_pdf_with_user_password_is_permanent() -> None:
    with pytest.raises(PermanentIngestionError, match="password"):
        parse_pdf(_encrypted("pw"))


def test_unexpected_parser_error_is_permanent(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("pypdf bug")

    monkeypatch.setattr("fontes.adapters.loaders.pdf.PdfReader", explode)
    with pytest.raises(PermanentIngestionError, match="Could not read the PDF"):
        parse_pdf(make_pdf(["x"]))
