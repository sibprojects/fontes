import re

import pytest

from fontes.application.chunking import Chunker
from fontes.domain.chunks import Segment


def _chunker() -> Chunker:
    return Chunker(1500, 200, 300)


def _text(n: int, letter: str = "a") -> str:
    """n characters of words, so no cut can fall mid-word by accident."""
    words = (letter * 9 + " ") * (n // 10 + 1)
    return words[:n].strip()


def test_short_segments_on_one_page_merge() -> None:
    chunks = _chunker().split([Segment(_text(400), page=1), Segment(_text(400, "b"), page=1)])
    assert len(chunks) == 1
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 1)


def test_page_boundary_starts_new_chunk() -> None:
    chunks = _chunker().split([Segment(_text(400), page=1), Segment(_text(400, "b"), page=2)])
    assert [(c.page_start, c.page_end) for c in chunks] == [(1, 1), (2, 2)]


def test_short_page_tail_joins_next_page() -> None:
    chunks = _chunker().split([Segment(_text(50), page=1), Segment(_text(400, "b"), page=2)])
    assert len(chunks) == 1
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 2)


def test_section_change_starts_new_chunk() -> None:
    chunks = _chunker().split(
        [Segment(_text(400), section="A"), Segment(_text(400, "b"), section="B")]
    )
    assert [c.section for c in chunks] == ["A", "B"]


def test_long_text_splits_with_overlap() -> None:
    sentences = [f"Sentence {n}." for n in range(500)]
    text = " ".join(sentences)[:5000]
    chunks = _chunker().split([Segment(text)])
    assert len(chunks) > 1
    assert all(len(c.text) <= 1500 for c in chunks)
    assert chunks[1].text[:40] in chunks[0].text
    complete = re.findall(r"Sentence \d+\.", text)
    assert all(any(s in c.text for c in chunks) for s in complete)


def test_split_prefers_paragraph_break() -> None:
    first, second = _text(1000), _text(1000, "b")
    chunks = _chunker().split([Segment(f"{first}\n\n{second}")])
    assert chunks[0].text == first


def test_never_starts_or_ends_mid_word() -> None:
    words = [f"w{n:06d}" for n in range(1000)]
    chunks = _chunker().split([Segment(" ".join(words))])
    assert len(chunks) > 1
    vocabulary = set(words)
    for c in chunks:
        parts = c.text.split(" ")
        assert parts[0] in vocabulary and parts[-1] in vocabulary


def test_word_longer_than_max_is_hard_cut() -> None:
    chunks = Chunker(100, 10, 50).split([Segment("x" * 350)])
    assert len(chunks) == 4
    assert all(len(c.text) <= 100 for c in chunks)


def test_nul_and_control_characters_removed() -> None:
    chunks = _chunker().split([Segment("a\x00b\x07c\r\nd")])
    assert [c.text for c in chunks] == ["abc\nd"]


def test_whitespace_is_normalized() -> None:
    chunks = _chunker().split([Segment("  a \t  b\n\n\n\nc\rd\x0ce  ")])
    assert [c.text for c in chunks] == ["a b\n\nc\nd\ne"]


def test_blank_segments_give_no_chunks() -> None:
    assert _chunker().split([Segment("  \n "), Segment("")]) == []


def test_ordinals_are_sequential() -> None:
    chunks = _chunker().split(
        [Segment(_text(4000), page=1), Segment(_text(400), page=2), Segment(_text(3000), page=3)]
    )
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert len(chunks) > 3


def test_split_piece_pages_cover_only_overlapped_segments() -> None:
    # A short p.1 joins p.2; the later pieces of that long group lie entirely on p.2.
    chunks = _chunker().split([Segment(_text(100), page=1), Segment(_text(4000, "b"), page=2)])
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 2)
    assert (chunks[-1].page_start, chunks[-1].page_end) == (2, 2)


def test_invalid_sizes_raise() -> None:
    with pytest.raises(ValueError):
        Chunker(100, 60, 50)
    with pytest.raises(ValueError):
        Chunker(100, 10, 0)


def test_piece_inside_a_later_section_cites_that_section() -> None:
    # A short title section absorbs the next one; pieces lying wholly under "Install" must
    # still cite "Install", the nearest preceding heading.
    segments = [
        Segment("Title\nshort tagline", section="Title"),
        Segment("Install\n" + _text(4000), section="Install"),
    ]
    sections = [c.section for c in _chunker().split(segments)]
    assert sections[0] == "Title"
    assert len(sections) > 2 and set(sections[1:]) == {"Install"}


def test_section_title_is_normalized_to_one_line() -> None:
    chunks = _chunker().split([Segment("body", section=" A\x00B\n\n  C\t D ")])
    assert chunks[0].section == "AB C D"


def test_section_title_is_capped() -> None:
    chunks = _chunker().split([Segment("body", section="word " * 1000)])
    assert chunks[0].section is not None and len(chunks[0].section) <= 200


def test_blank_section_title_becomes_none() -> None:
    chunks = _chunker().split([Segment("body", section=" \x00 ")])
    assert chunks[0].section is None
