from uuid import uuid4

from fontes.application.ports.chunks import SearchHit
from fontes.application.prompting import build_prompt
from fontes.domain.chunks import Chunk


def _hit(title: str, chunk: Chunk, url: str | None = None) -> SearchHit:
    return SearchHit(uuid4(), title, url, chunk, total_chunks=4, score=0.8)


def test_sources_numbered_from_one_in_order() -> None:
    prompt = build_prompt(
        "Q?",
        [
            _hit("a.pdf", Chunk(0, "alpha text", 3, 3)),
            _hit("b.md", Chunk(1, "beta text", section="Install")),
        ],
    )
    first = prompt.user.index("[1] a.pdf — p. 3")
    second = prompt.user.index("[2] b.md — Install")
    assert first < prompt.user.index("alpha text") < second < prompt.user.index("beta text")


def test_url_source_shows_link() -> None:
    url = "https://x.test/page"
    prompt = build_prompt("Q?", [_hit(url, Chunk(0, "t", section="Intro"), url=url)])
    assert f"[1] {url} — Intro ({url})" in prompt.user


def test_position_label_uses_total() -> None:
    prompt = build_prompt("Q?", [_hit("c.html", Chunk(2, "t"))])
    assert "[1] c.html — part 3 of 4" in prompt.user


def test_question_is_last() -> None:
    question = "Как это работает?"
    prompt = build_prompt(question, [_hit("a.pdf", Chunk(0, "t", 1, 1))])
    assert prompt.user.rstrip().endswith(question)


def test_system_demands_markers_per_paragraph() -> None:
    system = build_prompt("Q?", [_hit("a.pdf", Chunk(0, "t", 1, 1))]).system
    assert "[n]" in system
    assert "every paragraph" in system
    assert "language of the question" in system


def test_unclear_language_falls_back_to_the_sources() -> None:
    system = build_prompt("Q", []).system
    assert "Answer in the language of the question." in system
    assert (
        "If the question has no clear language (only names, numbers or codes), "
        "answer in the language of the sources." in system
    )


NO_CHINESE = "Do not write Chinese characters."


def test_no_chinese_when_neither_question_nor_sources_have_any() -> None:
    # qwen2.5 drifts into Chinese on short English questions; when nothing asked for it,
    # the system prompt rules it out.
    prompt = build_prompt("What about 1795045963?", [_hit("a.md", Chunk(0, "Smoke test text."))])
    assert NO_CHINESE in prompt.system


def test_chinese_allowed_when_the_question_is_chinese() -> None:
    prompt = build_prompt("怎么除垢?", [_hit("a.md", Chunk(0, "Descale every 4 weeks."))])
    assert NO_CHINESE not in prompt.system


def test_chinese_allowed_when_a_source_is_chinese() -> None:
    prompt = build_prompt("K2?", [_hit("a.md", Chunk(0, "每四周除垢一次。"))])
    assert NO_CHINESE not in prompt.system
