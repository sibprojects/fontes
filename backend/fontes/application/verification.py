"""Citation verification: is every paragraph of an answer backed by a real source?"""

import re
from dataclasses import dataclass

from fontes.domain.answers import AnswerLabel, Paragraph

_BLOCK_BREAK = re.compile(r"\n[ \t]*\n")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
# The whitespace before a marker is matched too, so that a removed marker leaves no gap.
# Only spaces and tabs: a marker at the start of a line must not join it to the line above.
_MARKER = re.compile(r"([ \t]*)\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]")


@dataclass(frozen=True)
class Verification:
    text: str
    paragraphs: tuple[Paragraph, ...]
    label: AnswerLabel


def verify(text: str, source_count: int) -> Verification:
    """Check each paragraph for `[n]` markers that name one of the `source_count` sources.

    Invalid markers are removed from the text. A paragraph is supported if it keeps at least
    one valid marker. An answer with no paragraphs at all is unsupported.
    """
    paragraphs = tuple(
        paragraph
        for raw in _split(text.replace("\r\n", "\n"))
        if (paragraph := _clean(raw, source_count)).text
    )
    supported = [p.supported for p in paragraphs]
    if supported and all(supported):
        label = AnswerLabel.SUPPORTED
    elif any(supported):
        label = AnswerLabel.PARTIALLY_SUPPORTED
    else:
        label = AnswerLabel.UNSUPPORTED
    return Verification("\n\n".join(p.text for p in paragraphs), paragraphs, label)


def _split(text: str) -> list[str]:
    """Blocks are separated by blank lines; inside a block, each list item stands alone."""
    paragraphs: list[str] = []
    for block in _BLOCK_BREAK.split(text):
        current: list[str] = []
        for line in block.split("\n"):
            if _LIST_ITEM.match(line) and current:
                paragraphs.append("\n".join(current))
                current = []
            current.append(line)
        paragraphs.append("\n".join(current))
    return paragraphs


def _clean(raw: str, source_count: int) -> Paragraph:
    cited: list[int] = []

    def rewrite(match: re.Match[str]) -> str:
        numbers = [int(n) for n in re.split(r"\s*,\s*", match.group(2))]
        valid = list(dict.fromkeys(n for n in numbers if 1 <= n <= source_count))
        if not valid:
            return ""
        cited.extend(n for n in valid if n not in cited)
        return match.group(1) + "".join(f"[{n}]" for n in valid)

    text = _MARKER.sub(rewrite, raw).strip()
    return Paragraph(text, tuple(cited))
