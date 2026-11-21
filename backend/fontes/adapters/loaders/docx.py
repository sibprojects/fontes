"""Word .docx files: the main document part only, with headings as sections.

The standard library is enough. A .docx is a zip holding `word/document.xml`; its uncompressed
size is checked before reading (a zip bomb guard), and expat refuses entity expansion attacks.
Text boxes, footnotes, headers, footers and comments live elsewhere and are not read.
"""

import io
import re
import xml.etree.ElementTree as ET
import zipfile

from fontes.application.ports.ingestion import PermanentIngestionError
from fontes.domain.chunks import Segment

DOCX_MAX_XML_BYTES = 50 * 1024 * 1024

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DOCUMENT = "word/document.xml"
# "Title", "Heading1".."Heading9", and localised ids such as "Заголовок1".
_HEADING_STYLE = re.compile(r"^(?:title|(?:heading|заголовок)\s*[1-9])$", re.IGNORECASE)


def parse_docx(data: bytes) -> list[Segment]:
    """One segment per heading section; text before the first heading has no section."""
    body = _body(_document_xml(data))
    segments: list[Segment] = []
    section: str | None = None
    lines: list[str] = []

    def flush() -> None:
        content = "\n".join(lines).strip()
        if content:
            segments.append(Segment(content, section=section))

    for element in body:
        if element.tag == f"{_W}p":
            text = _paragraph_text(element)
            if _is_heading(element) and text.strip():
                flush()
                section = text.strip()
                lines = [section]
            elif text.strip():
                lines.append(text.rstrip())
        elif element.tag == f"{_W}tbl":
            lines.extend(_table_lines(element))
    flush()
    return segments


def _document_xml(data: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            info = package.getinfo(_DOCUMENT)
            if info.file_size > DOCX_MAX_XML_BYTES:
                raise PermanentIngestionError(
                    f"The DOCX text is too large ({info.file_size} bytes uncompressed; "
                    f"the limit is {DOCX_MAX_XML_BYTES})"
                )
            return package.read(info)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise PermanentIngestionError("The file is not a Word .docx file") from exc


def _body(xml: bytes) -> ET.Element:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise PermanentIngestionError(f"Could not read the DOCX: {exc}") from exc
    body = root.find(f"{_W}body")
    return body if body is not None else ET.Element("body")


def _is_heading(paragraph: ET.Element) -> bool:
    style = paragraph.find(f"{_W}pPr/{_W}pStyle")
    return style is not None and bool(_HEADING_STYLE.match(style.get(f"{_W}val", "")))


def _paragraph_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t":
            parts.append(node.text or "")
        elif node.tag == f"{_W}tab":
            parts.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
    return "".join(parts)


def _table_lines(table: ET.Element) -> list[str]:
    lines: list[str] = []
    for row in table.iter(f"{_W}tr"):
        cells = [
            " ".join(_paragraph_text(p).strip() for p in cell.iter(f"{_W}p")).strip()
            for cell in row.iter(f"{_W}tc")
        ]
        if any(cells):
            lines.append(" | ".join(cells))
    return lines
