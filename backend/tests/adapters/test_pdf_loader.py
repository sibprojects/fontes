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
