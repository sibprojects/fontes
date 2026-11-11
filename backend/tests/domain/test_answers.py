from fontes.domain.answers import AnswerLabel, Paragraph


def test_paragraph_supported_iff_citations() -> None:
    assert Paragraph("a", (1,)).supported
    assert not Paragraph("a", ()).supported


def test_label_values() -> None:
    assert [label.value for label in AnswerLabel] == [
        "supported",
        "partially_supported",
        "unsupported",
        "not_found",
    ]
