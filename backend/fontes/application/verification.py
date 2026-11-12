"""Citation verification: is every paragraph of an answer backed by a real source?"""

import re
from dataclasses import dataclass

from fontes.domain.answers import AnswerLabel, Paragraph

_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
# The whitespace before a marker is matched too, so that a removed marker leaves no gap.
# Only spaces and tabs: a marker at the start of a line must not join it to the line above.
# A `[` right after a word character or `)` is an index (`a[2]`, `f(x)[1]`), not a marker;
# `]` is allowed, so `[1][2]` still counts. Fullwidth brackets (`【1】`, `［1］`), which some
# models write, are never indexes; `\d` also matches fullwidth digits, and `int()` reads them.
_MARKER = re.compile(r"([ \t]*)(?:(?<![\w)])\[|[［【])\s*(\d+(?:\s*[,，]\s*\d+)*)\s*[\]］】]")
_SEPARATOR = re.compile(r"\s*[,，]\s*")
_FENCE = "```"
# Code is quoted, never cited: fenced blocks (an unclosed fence runs to the end) and inline spans.
_CODE = re.compile(r"```.*?(?:```|\Z)|`[^`\n]*`", re.S)


@dataclass(frozen=True)
class Verification:
    text: str
    paragraphs: tuple[Paragraph, ...]
    label: AnswerLabel


def verify(text: str, source_count: int) -> Verification:
    """Check each paragraph for `[n]` markers that name one of the `source_count` sources.

    Invalid markers are removed from the text. A paragraph is supported if it keeps at least
    one valid marker. An answer with no paragraphs at all is unsupported. Brackets inside code
    (inline or fenced) and indexes such as `a[2]` are left alone: they are not markers.
    Fullwidth markers such as `【1】` count too and are rewritten as `[1]`.
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
    """Blocks are separated by blank lines; inside a block, each list item stands alone.

    A fenced code block belongs to the paragraph it starts in: blank lines and list-like
    lines inside it split nothing.
    """
    paragraphs: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if line.strip().startswith(_FENCE):
            in_fence = not in_fence
        elif not in_fence:
            if not line.strip():
                if current:
                    paragraphs.append("\n".join(current))
                    current = []
                continue
            if _LIST_ITEM.match(line) and current:
                paragraphs.append("\n".join(current))
                current = []
        current.append(line)
    if current:
        paragraphs.append("\n".join(current))
    return paragraphs


def _clean(raw: str, source_count: int) -> Paragraph:
    cited: list[int] = []

    def rewrite(match: re.Match[str]) -> str:
        numbers = [int(n) for n in _SEPARATOR.split(match.group(2))]
        valid = list(dict.fromkeys(n for n in numbers if 1 <= n <= source_count))
        if not valid:
            return ""
        cited.extend(n for n in valid if n not in cited)
        return match.group(1) + "".join(f"[{n}]" for n in valid)

    pieces: list[str] = []
    start = 0
    for code in _CODE.finditer(raw):
        pieces.append(_MARKER.sub(rewrite, raw[start : code.start()]))
        pieces.append(code.group())
        start = code.end()
    pieces.append(_MARKER.sub(rewrite, raw[start:]))
    return Paragraph("".join(pieces).strip(), tuple(cited))
