import re
from collections.abc import Sequence
from dataclasses import dataclass

from fontes.domain.chunks import Chunk, Segment

_PAGE_BREAKS = re.compile(r"\r\n|[\r\v\f]")
_CONTROLS = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]")
_SPACES = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_SENTENCE_ENDS = (". ", "! ", "? ")
_SEPARATOR = "\n\n"
MAX_SECTION_CHARS = 200


def _normalize(text: str) -> str:
    text = _PAGE_BREAKS.sub("\n", text)
    text = _CONTROLS.sub("", text)  # Postgres rejects NUL in text columns
    text = _SPACES.sub(" ", text)
    return _BLANK_LINES.sub(_SEPARATOR, text).strip()


def _normalize_section(section: str | None) -> str | None:
    """One line, bounded: a heading is a citation label, not content."""
    if section is None:
        return None
    title = " ".join(_normalize(section).split())
    if len(title) > MAX_SECTION_CHARS:
        title = title[: MAX_SECTION_CHARS - 1].rstrip() + "…"
    return title or None


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    page: int | None
    section: str | None


# text, page_start, page_end, section
_Piece = tuple[str, int | None, int | None, str | None]


class Chunker:
    """Splits loaded segments into chunks that never cross a location unless one is too short."""

    def __init__(self, max_chars: int, overlap_chars: int, min_chars: int) -> None:
        if not 0 <= overlap_chars < max_chars // 2:
            raise ValueError("overlap_chars must be at least 0 and under half of max_chars")
        if not 0 < min_chars <= max_chars:
            raise ValueError("min_chars must be positive and at most max_chars")
        self._max = max_chars
        self._overlap = overlap_chars
        self._min = min_chars

    def split(self, segments: Sequence[Segment]) -> list[Chunk]:
        chunks: list[Chunk] = []
        for group in self._group(segments):
            for text, page_start, page_end, section in self._pieces(group):
                chunks.append(Chunk(len(chunks), text, page_start, page_end, section))
        return chunks

    def _group(self, segments: Sequence[Segment]) -> list[list[Segment]]:
        groups: list[list[Segment]] = []
        size = 0
        for segment in segments:
            text = _normalize(segment.text)
            if not text:
                continue
            segment = Segment(text, segment.page, _normalize_section(segment.section))
            current = groups[-1] if groups else None
            key = (segment.page, segment.section)
            if current is not None and (
                key == (current[-1].page, current[-1].section) or size < self._min
            ):
                current.append(segment)
                size += len(_SEPARATOR) + len(text)
            else:
                groups.append([segment])
                size = len(text)
        return groups

    def _pieces(self, group: list[Segment]) -> list[_Piece]:
        spans: list[_Span] = []
        offset = 0
        for segment in group:
            spans.append(_Span(offset, offset + len(segment.text), segment.page, segment.section))
            offset += len(segment.text) + len(_SEPARATOR)
        text = _SEPARATOR.join(segment.text for segment in group)

        pieces: list[_Piece] = []
        start = 0
        while start < len(text):
            cut = len(text) if len(text) - start <= self._max else self._cut(text, start)
            overlapped = [s for s in spans if s.start < cut and s.end > start]
            pages = [s.page for s in overlapped if s.page is not None]
            piece = text[start:cut].strip()
            if piece:
                # Cite the section the piece starts in: its nearest preceding heading.
                section = overlapped[0].section if overlapped else group[0].section
                pieces.append((piece, min(pages, default=None), max(pages, default=None), section))
            if cut == len(text):
                break
            start = self._next_start(text, start, cut)
        return pieces

    def _cut(self, text: str, start: int) -> int:
        window = text[start : start + self._max]
        paragraph = window.rfind(_SEPARATOR)
        if paragraph > self._max // 2:
            return start + paragraph
        sentence = max(window.rfind(end) for end in _SENTENCE_ENDS)
        if sentence > self._max // 2:
            return start + sentence + 1
        space = max(window.rfind(" "), window.rfind("\n"), window.rfind("\t"))
        if space > self._max // 2:
            return start + space
        return start + self._max

    def _next_start(self, text: str, start: int, cut: int) -> int:
        nxt = cut - self._overlap
        if nxt > 0 and not text[nxt - 1].isspace():
            # Move forward to the next word boundary, so no piece starts mid-word.
            while nxt < cut and not text[nxt].isspace():
                nxt += 1
        if nxt <= start:
            nxt = cut
        while nxt < len(text) and text[nxt].isspace():
            nxt += 1
        return nxt
