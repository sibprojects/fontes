import pytest

from fontes.adapters.loaders.html import parse_html
from fontes.application.ports.ingestion import PermanentIngestionError
from fontes.domain.chunks import Segment


def _text(segments: list[Segment]) -> str:
    return "\n".join(s.text for s in segments)


def test_scripts_styles_and_navigation_removed() -> None:
    html = b"""<html><head><style>.x{color:red}</style><script>var secret=1</script></head>
    <body><nav>Menu</nav><header>Logo</header><p>Content</p><aside>Ad</aside>
    <form>Login</form><footer>Copyright</footer><noscript>Enable JS</noscript></body></html>"""
    text = _text(parse_html(html))
    assert "Content" in text
    for gone in ("color:red", "secret", "Menu", "Logo", "Ad", "Login", "Copyright", "Enable JS"):
        assert gone not in text


def test_sections_follow_headings() -> None:
    segments = parse_html(b"<body><h1>A</h1><p>x</p><h2>B</h2><p>y</p></body>")
    assert [s.section for s in segments] == ["A", "B"]
    assert [s.text for s in segments] == ["A\nx", "B\ny"]


def test_text_before_first_heading_has_no_section() -> None:
    segments = parse_html(b"<body><p>lead</p><h1>A</h1><p>x</p></body>")
    assert [(s.text, s.section) for s in segments] == [("lead", None), ("A\nx", "A")]


def test_text_in_plain_divs_is_kept() -> None:
    assert "bare text" in _text(parse_html(b"<body><div>bare text</div></body>"))


def test_main_is_preferred_over_body() -> None:
    text = _text(parse_html(b"<body><div>outside</div><main><p>inside</p></main></body>"))
    assert "inside" in text and "outside" not in text


def test_meta_charset_is_honoured() -> None:
    html = '<html><head><meta charset="windows-1251"></head><body><p>Привет</p></body></html>'
    assert "Привет" in _text(parse_html(html.encode("cp1251")))


def test_list_items_are_separate_lines() -> None:
    assert "a\nb" in _text(parse_html(b"<body><ul><li>a</li><li>b</li></ul></body>"))


def test_inline_elements_stay_on_one_line() -> None:
    assert "a bold word" in _text(parse_html(b"<body><p>a <b>bold</b> word</p></body>"))


def test_deeply_nested_markup_does_not_hit_recursion_limit() -> None:
    html = b"<body>" + b"<div>" * 5000 + b"deep" + b"</div>" * 5000 + b"</body>"
    assert _text(parse_html(html)) == "deep"


def test_article_header_is_kept_but_page_header_removed() -> None:
    html = b"""<body><header>Site logo</header><article><header><h1>Post title</h1></header>
    <p>Post body</p><footer>Posted by Ann</footer></article><footer>Copyright</footer></body>"""
    segments = parse_html(html)
    assert segments[0].section == "Post title"
    text = _text(segments)
    assert "Post body" in text and "Posted by Ann" in text
    assert "Site logo" not in text and "Copyright" not in text


def test_encoding_from_http_header_is_used() -> None:
    html = "<body><h1>Привет мир</h1><p>Текст</p></body>".encode("cp1251")
    assert parse_html(html, encoding="windows-1251") == [
        Segment("Привет мир\nТекст", section="Привет мир")
    ]


def test_unexpected_parser_error_is_permanent(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RecursionError("too deep")

    # The walk, not the parser: BeautifulSoup itself was already guarded.
    monkeypatch.setattr("fontes.adapters.loaders.html._Segmenter", explode)
    with pytest.raises(PermanentIngestionError, match="Could not parse HTML"):
        parse_html(b"<p>x</p>")
