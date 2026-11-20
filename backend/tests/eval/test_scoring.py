import pytest

from fontes.eval.cases import Case
from fontes.eval.scoring import (
    CaseResult,
    Outcome,
    Summary,
    detect_language,
    render,
    score,
    summarize,
)

KETTLE = Case("kettle-oolong", "Oolong?", "lumen-kettle.md", ("90",), "en")
FEE = Case("garden-fee", "Взнос?", "sad-pravila.md", ("4800",), "ru")
OFF = Case("off-capital", "Capital of France?", None, (), "en")


def _outcome(answer: str, label: str = "supported", documents: tuple[str, ...] = ()) -> Outcome:
    return Outcome(answer, label, documents, None, 2.0)


def test_detect_language() -> None:
    assert detect_language("Ответ: 90 °C [1].") == "ru"
    assert detect_language("Use 90 °C [1].") == "en"
    assert detect_language("答案是 90 度") == "zh"
    assert detect_language("90 [1]") == "unknown"


@pytest.mark.parametrize("amount", ["4 800", "4 800", "4 800", "4800"])
def test_numbers_with_spaces_match(amount: str) -> None:
    result = score(FEE, _outcome(f"Взнос — {amount} рублей [1].", documents=("sad-pravila.md",)))
    assert result.checks["facts"] is True


def test_alternatives() -> None:
    case = Case("keep-warm", "How long?", "lumen-kettle.md", ("2 hours|two hours",), "en")
    assert score(case, _outcome("It holds it for two hours [1].")).checks["facts"] is True
    assert score(case, _outcome("It holds it for a while [1].")).checks["facts"] is False


def test_answerable_checks() -> None:
    outcome = _outcome(
        "Use 90 °C for oolong [1].", "partially_supported", ("lumen-kettle.md", "x.md")
    )
    result = score(KETTLE, outcome)
    assert result.checks == {
        "found": True,
        "cited": True,
        "supported": False,
        "facts": True,
        "language": True,
    }
    assert result.passed is False


def test_off_topic() -> None:
    nothing = score(OFF, _outcome("I could not find anything.", "not_found"))
    assert nothing.checks == {"not_found": True}
    assert nothing.passed is True
    assert score(OFF, _outcome("Paris [1].")).passed is False


def test_error_fails_every_check() -> None:
    result = score(KETTLE, Outcome("", None, (), "Cannot reach Ollama", 1.0))
    assert set(result.checks) == {"found", "cited", "supported", "facts", "language"}
    assert not any(result.checks.values())
    assert result.passed is False
    assert score(OFF, Outcome("", None, (), "boom", 1.0)).checks == {"not_found": False}


def test_summarize_and_render() -> None:
    results: list[CaseResult] = [
        score(KETTLE, _outcome("Use 90 °C [1].", documents=("lumen-kettle.md",))),
        score(FEE, Outcome("Взнос не указан [1].", "supported", ("sad-pravila.md",), None, 4.0)),
        score(OFF, Outcome("", None, (), "Cannot reach Ollama", 6.0)),
    ]
    summary = summarize(results)
    assert summary == Summary(
        cases=3,
        passed=1,
        errors=1,
        checks={
            "found": (2, 2),
            "cited": (2, 2),
            "supported": (2, 2),
            "facts": (1, 2),
            "language": (2, 2),
            "not_found": (0, 1),
        },
        median_seconds=4.0,
    )
    text = render(summary, results, "ollama", "qwen2.5:7b")
    assert "qwen2.5:7b" in text
    assert "| facts | 1/2 |" in text
    assert "garden-fee" in text
    assert "off-capital" in text
    assert "Cannot reach Ollama" in text
    assert "kettle-oolong" not in text
    assert "unknown" in render(summary, results, None, None)
