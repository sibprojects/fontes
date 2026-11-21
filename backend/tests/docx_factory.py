"""Builds minimal Word packages for tests: only what a .docx reader needs."""

import io
import zipfile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/'
    'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)


def make_docx(body_xml: str) -> bytes:
    """A package whose `word/document.xml` holds `body_xml` inside `<w:body>`."""
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>{body_xml}</w:body></w:document>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", _CONTENT_TYPES)
        package.writestr("word/document.xml", document)
    return buffer.getvalue()


def p(text: str, style: str | None = None) -> str:
    """One paragraph with one run; `style` is the paragraph style id, e.g. "Heading1"."""
    props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f'<w:p>{props}<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def table(*rows: tuple[str, ...]) -> str:
    cells = "".join(
        "<w:tr>" + "".join(f"<w:tc>{p(c)}</w:tc>" for c in row) + "</w:tr>" for row in rows
    )
    return f"<w:tbl>{cells}</w:tbl>"
