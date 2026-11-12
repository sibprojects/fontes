from fontes.application.verification import verify
from fontes.domain.answers import AnswerLabel


def _supported(text: str, sources: int = 2) -> list[bool]:
    return [p.supported for p in verify(text, sources).paragraphs]


def test_all_cited_is_supported() -> None:
    result = verify("A [1].\n\nB [2].", 2)
    assert result.label == AnswerLabel.SUPPORTED
    assert [p.citations for p in result.paragraphs] == [(1,), (2,)]


def test_some_cited_is_partial() -> None:
    result = verify("A [1].\n\nB.", 2)
    assert result.label == AnswerLabel.PARTIALLY_SUPPORTED
    assert [p.supported for p in result.paragraphs] == [True, False]


def test_none_cited_is_unsupported() -> None:
    assert verify("A.\n\nB.", 2).label == AnswerLabel.UNSUPPORTED


def test_empty_answer_is_unsupported() -> None:
    for text in ("", "  \n\n \n"):
        result = verify(text, 2)
        assert result.label == AnswerLabel.UNSUPPORTED
        assert result.paragraphs == ()
        assert result.text == ""


def test_out_of_range_markers_removed() -> None:
    result = verify("A [3].\n\nB [0] and [1].", 2)
    assert [p.text for p in result.paragraphs] == ["A.", "B and [1]."]
    assert [p.supported for p in result.paragraphs] == [False, True]


def test_group_keeps_only_valid_numbers() -> None:
    (paragraph,) = verify("A [1, 7, 1].", 2).paragraphs
    assert paragraph.text == "A [1]."
    assert paragraph.citations == (1,)


def test_group_with_spaces_is_parsed() -> None:
    (paragraph,) = verify("A [ 2 ].", 2).paragraphs
    assert paragraph.text == "A [2]."
    assert paragraph.citations == (2,)


def test_group_of_several_valid_numbers_is_split() -> None:
    (paragraph,) = verify("A [2, 1].", 2).paragraphs
    assert paragraph.text == "A [2][1]."
    assert paragraph.citations == (2, 1)


def test_list_items_are_paragraphs() -> None:
    result = verify("Intro [1]:\n- one [1]\n- two\n1. three [2]", 2)
    assert [p.text for p in result.paragraphs] == [
        "Intro [1]:",
        "- one [1]",
        "- two",
        "1. three [2]",
    ]
    assert [p.supported for p in result.paragraphs] == [True, True, False, True]


def test_continuation_line_joins_its_item() -> None:
    (paragraph,) = verify("- one\n  more [1]", 2).paragraphs
    assert paragraph.text == "- one\n  more [1]"
    assert paragraph.supported


def test_removed_marker_does_not_join_lines() -> None:
    (paragraph,) = verify("- one\n[9] more [1]", 2).paragraphs
    lines = paragraph.text.split("\n")
    assert [line.strip() for line in lines] == ["- one", "more [1]"]


def test_crlf_and_blank_line_with_spaces_split() -> None:
    assert _supported("A [1].\r\n \r\nB [1].") == [True, True]


def test_text_joins_cleaned_paragraphs() -> None:
    result = verify("A [1] [5].\n\n\n- b\n- c [2]", 2)
    assert result.text == "\n\n".join(p.text for p in result.paragraphs)
    assert result.text == "A [1].\n\n- b\n\n- c [2]"


def test_markers_in_order_without_duplicates() -> None:
    (paragraph,) = verify("A [2] b [1] c [2].", 2).paragraphs
    assert paragraph.citations == (2, 1)


def test_no_sources_makes_every_marker_invalid() -> None:
    result = verify("A [1].", 0)
    assert [p.text for p in result.paragraphs] == ["A."]
    assert result.label == AnswerLabel.UNSUPPORTED


def test_paragraph_of_only_invalid_markers_is_dropped() -> None:
    result = verify("A [1].\n\n[7]", 2)
    assert [p.text for p in result.paragraphs] == ["A [1]."]
    assert result.label == AnswerLabel.SUPPORTED


def test_brackets_that_are_not_markers_stay() -> None:
    (paragraph,) = verify("Use x[i] and [note] [1].", 2).paragraphs
    assert paragraph.text == "Use x[i] and [note] [1]."


def test_markers_inside_inline_code_are_untouched() -> None:
    (paragraph,) = verify("Use `arr[0]` and `a[2]` here [1].", 3).paragraphs
    assert paragraph.text == "Use `arr[0]` and `a[2]` here [1]."
    assert paragraph.citations == (1,)


def test_index_after_identifier_is_not_a_marker() -> None:
    result = verify("Set x = a[2] and f(x)[1] to fix.", 3)
    assert result.text == "Set x = a[2] and f(x)[1] to fix."
    assert result.label == AnswerLabel.UNSUPPORTED


def test_markers_inside_fenced_code_are_untouched() -> None:
    text = "Run this [2]:\n```py\nprint(a[1], b[ 9 ])\n```"
    (paragraph,) = verify(text, 3).paragraphs
    assert paragraph.text == text
    assert paragraph.citations == (2,)


def test_adjacent_markers_still_count() -> None:
    (paragraph,) = verify("A [1][2] and B.[3]", 3).paragraphs
    assert paragraph.citations == (1, 2, 3)


def test_fenced_code_with_blank_line_stays_one_paragraph() -> None:
    text = "Run this [1]:\n```py\na = 1\n\nb = 2\n```"
    (paragraph,) = verify(text, 3).paragraphs
    assert paragraph.text == text
    assert paragraph.citations == (1,)


def test_list_lines_inside_fence_are_not_items() -> None:
    text = "Example [1]:\n```\n- a\n- b\n```"
    (paragraph,) = verify(text, 3).paragraphs
    assert paragraph.text == text


def test_text_after_a_fence_splits_again() -> None:
    result = verify("A [1]:\n```\nx\n\ny\n```\n\nB [2].", 3)
    assert [p.citations for p in result.paragraphs] == [(1,), (2,)]


def test_fullwidth_markers_count_and_are_normalized() -> None:
    (paragraph,) = verify("A 【1】 and B［2］ and C [３，1].", 3).paragraphs
    assert paragraph.text == "A [1] and B[2] and C [3][1]."
    assert paragraph.citations == (1, 2, 3)
