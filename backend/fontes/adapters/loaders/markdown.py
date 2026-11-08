import re

from fontes.application.ports.ingestion import PermanentIngestionError
from fontes.domain.chunks import Segment

_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_FRONT_MATTER_END = ("---", "...")


def parse_markdown(data: bytes) -> list[Segment]:
    """Split on ATX headings; each heading's title starts its section's text."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PermanentIngestionError("Markdown files must be UTF-8 text") from exc
    lines = _drop_front_matter(text.splitlines())

    segments: list[Segment] = []
    section: str | None = None
    body: list[str] = []
    fence: str | None = None

    def flush() -> None:
        content = "\n".join(body).strip()
        if content:
            segments.append(Segment(content, section=section))

    for line in lines:
        opening = _FENCE.match(line)
        if fence is not None:
            if opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence):
                fence = None
        elif opening:
            fence = opening.group(1)
        elif heading := _HEADING.match(line):
            flush()
            section = (heading.group(2) or "").strip() or None
            body = [section] if section else []
            continue
        body.append(line)
    flush()
    return segments


def _drop_front_matter(lines: list[str]) -> list[str]:
    if not lines or lines[0].strip() != "---":
        return lines
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() in _FRONT_MATTER_END:
            return lines[i + 1 :]
    return lines  # never closed, so it was not front matter
