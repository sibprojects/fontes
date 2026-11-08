import pytest

from fontes.adapters.loaders.markdown import parse_markdown
from fontes.application.ports.ingestion import PermanentIngestionError


def _pairs(data: bytes) -> list[tuple[str, str | None]]:
    return [(s.text, s.section) for s in parse_markdown(data)]


def test_sections_follow_atx_headings() -> None:
    assert _pairs(b"intro\n# A\ntext a\n## B ##\ntext b") == [
        ("intro", None),
        ("A\ntext a", "A"),
        ("B\ntext b", "B"),
    ]


def test_heading_inside_fenced_code_is_ignored() -> None:
    segments = parse_markdown(b"# A\n```\n# not a heading\n```")
    assert [s.section for s in segments] == ["A"]
    assert "# not a heading" in segments[0].text


def test_tilde_fence_is_also_code() -> None:
    assert [s.section for s in parse_markdown(b"# A\n~~~\n# no\n~~~\n# B\nb")] == ["A", "B"]


def test_hash_without_space_is_not_a_heading() -> None:
    assert [s.section for s in parse_markdown(b"# A\n#hashtag\n")] == ["A"]


def test_front_matter_is_dropped() -> None:
    segments = parse_markdown(b"---\ntitle: x\n---\n# A\nbody")
    assert all("title: x" not in s.text for s in segments)
    assert [(s.text, s.section) for s in segments] == [("A\nbody", "A")]


def test_bom_and_cyrillic() -> None:
    segments = parse_markdown("﻿# Глава\nтекст".encode())
    assert [(s.text, s.section) for s in segments] == [("Глава\nтекст", "Глава")]


def test_non_utf8_is_permanent() -> None:
    with pytest.raises(PermanentIngestionError, match="UTF-8"):
        parse_markdown("Глава".encode("cp1251"))
