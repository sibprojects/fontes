import io
import zipfile

import pytest

from fontes.adapters.loaders import docx
from fontes.adapters.loaders.docx import parse_docx
from fontes.application.ports.ingestion import PermanentIngestionError
from fontes.domain.chunks import Segment
from tests.docx_factory import make_docx, p, table


def test_headings_start_sections() -> None:
    data = make_docx(
        p("Setup", "Heading1")
        + p("Fill it.")
        + p("Pair it.")
        + p("Care", "Heading2")
        + p("Descale monthly.")
    )
    assert parse_docx(data) == [
        Segment("Setup\nFill it.\nPair it.", section="Setup"),
        Segment("Care\nDescale monthly.", section="Care"),
    ]


def test_text_before_any_heading_has_no_section() -> None:
    segments = parse_docx(make_docx(p("Intro.") + p("Guide", "Title") + p("Body.")))
    assert segments[0] == Segment("Intro.", section=None)
    assert segments[1] == Segment("Guide\nBody.", section="Guide")


def test_runs_tabs_and_breaks_join() -> None:
    body = "<w:p><w:r><w:t>Hel</w:t></w:r><w:r><w:t>lo</w:t><w:tab/><w:t>x</w:t><w:br/></w:r></w:p>"
    assert parse_docx(make_docx(body)) == [Segment("Hello\tx", section=None)]


def test_table_rows_become_lines() -> None:
    data = make_docx(p("Prices", "Heading1") + table(("a", "b"), ("c", "d")))
    assert parse_docx(data) == [Segment("Prices\na | b\nc | d", section="Prices")]


@pytest.mark.parametrize("style", ["heading3", "Заголовок1", "berschrift1"])
def test_localised_heading_styles(style: str) -> None:
    expected = style != "berschrift1"
    segments = parse_docx(make_docx(p("Intro.") + p("Part", style) + p("Text.")))
    assert (segments[-1].section == "Part") is expected


def test_not_a_zip() -> None:
    with pytest.raises(PermanentIngestionError, match="not a Word .docx file"):
        parse_docx(b"plain text")


def test_zip_without_document() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("other.xml", "<a/>")
    with pytest.raises(PermanentIngestionError, match="not a Word .docx file"):
        parse_docx(buffer.getvalue())


def test_xml_over_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docx, "DOCX_MAX_XML_BYTES", 10)
    with pytest.raises(PermanentIngestionError, match="too large"):
        parse_docx(make_docx(p("Hello")))


def test_bad_xml() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("word/document.xml", "<w:document><unclosed>")
    with pytest.raises(PermanentIngestionError, match="Could not read the DOCX"):
        parse_docx(buffer.getvalue())


def test_empty_document() -> None:
    assert parse_docx(make_docx(p("  "))) == []
