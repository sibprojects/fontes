from bs4 import BeautifulSoup
from bs4.element import NavigableString, PageElement, PreformattedString, Tag

from fontes.application.ports.ingestion import PermanentIngestionError
from fontes.domain.chunks import Segment

_REMOVED = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
)
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCKS = {
    *_HEADINGS,
    "address", "article", "blockquote", "body", "br", "caption", "dd", "details", "div", "dl",
    "dt", "figcaption", "figure", "hr", "li", "main", "ol", "p", "pre", "section", "summary",
    "table", "td", "th", "tr", "ul",
}  # fmt: skip


class _Segmenter:
    def __init__(self) -> None:
        self.segments: list[Segment] = []
        self._section: str | None = None
        self._lines: list[str] = []
        self._words: list[str] = []

    def text(self, s: str) -> None:
        self._words.append(s)

    def end_line(self) -> None:
        line = " ".join("".join(self._words).split())
        self._words = []
        if line:
            self._lines.append(line)

    def heading(self, title: str) -> None:
        self.end_line()
        self.end_segment()
        self._section = title or None
        self._lines = [title] if title else []

    def end_segment(self) -> None:
        self.end_line()
        if self._lines:
            self.segments.append(Segment("\n".join(self._lines), section=self._section))
        self._lines = []


def parse_html(data: bytes) -> list[Segment]:
    """Visible text of the main content; h1–h6 start sections, block elements start lines."""
    try:
        soup = BeautifulSoup(data, "html.parser")  # decodes bytes, honouring <meta charset>
    except Exception as exc:  # html.parser is lenient; this is a corrupt or binary file
        raise PermanentIngestionError(f"Could not parse HTML: {exc}") from exc
    for tag in soup.find_all(_REMOVED):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup

    out = _Segmenter()
    # An explicit stack, not recursion: deeply nested markup must not hit the recursion limit.
    stack: list[PageElement | None] = [root]
    while stack:
        node = stack.pop()
        if node is None:  # marks the end of a block element
            out.end_line()
        elif isinstance(node, Tag):
            if node.name in _HEADINGS:
                out.heading(" ".join(node.get_text(" ").split()))
            elif node.name in _BLOCKS:
                out.end_line()
                stack.append(None)
                stack.extend(reversed(node.contents))
            else:
                stack.extend(reversed(node.contents))
        elif isinstance(node, NavigableString) and not isinstance(node, PreformattedString):
            out.text(str(node))
    out.end_segment()
    return out.segments
