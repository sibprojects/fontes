"""Scores answers without a judge: facts are matched as text, the language by script."""

import re
import statistics
from dataclasses import dataclass

from fontes.eval.cases import Case

ANSWERABLE_CHECKS = ("found", "cited", "supported", "facts", "language")
OFF_TOPIC_CHECKS = ("not_found",)
CHECK_ORDER = (*ANSWERABLE_CHECKS, *OFF_TOPIC_CHECKS)

_SCRIPTS = {
    "ru": re.compile(r"[Ѐ-ӿ]"),
    "zh": re.compile(r"[一-鿿]"),
    "en": re.compile(r"[A-Za-z]"),
}
# No-break, thin and narrow no-break spaces: models write "4 800" with any of them.
_ODD_SPACES = str.maketrans({" ": " ", " ": " ", " ": " "})
_SPACE_IN_NUMBER = re.compile(r"(?<=\d) (?=\d)")
_WHITESPACE = re.compile(r"\s+")
_ANSWER_PREVIEW_CHARS = 120
# Citation markers, so `[5]` is not read as the fact "5".
_MARKER = re.compile(r"[\[［【]\s*\d+(?:\s*[,，]\s*\d+)*\s*[\]］】]")


@dataclass(frozen=True)
class Outcome:
    """What one question got. `label` is None when the stream failed; `documents` holds the
    titles of the cited sources."""

    answer: str
    label: str | None
    documents: tuple[str, ...]
    error: str | None
    seconds: float


@dataclass(frozen=True)
class CaseResult:
    case: Case
    outcome: Outcome
    checks: dict[str, bool]

    @property
    def passed(self) -> bool:
        return self.outcome.error is None and all(self.checks.values())


@dataclass(frozen=True)
class Summary:
    cases: int
    passed: int
    errors: int
    # check name -> (passed, applicable)
    checks: dict[str, tuple[int, int]]
    median_seconds: float


def detect_language(text: str) -> str:
    """The script most of the letters are in; "unknown" when there are no letters."""
    counts = {lang: len(pattern.findall(text)) for lang, pattern in _SCRIPTS.items()}
    lang, count = max(counts.items(), key=lambda item: item[1])
    return lang if count else "unknown"


def normalize(text: str) -> str:
    text = text.lower().translate(_ODD_SPACES)
    text = _WHITESPACE.sub(" ", text)
    return _SPACE_IN_NUMBER.sub("", text)


def _contains(answer: str, fact: str) -> bool:
    """Substring match, but a number only matches whole: "90" is not in "190" or "900"."""
    before = r"(?<!\d)" if fact[:1].isdigit() else ""
    after = r"(?!\d)" if fact[-1:].isdigit() else ""
    return re.search(before + re.escape(fact) + after, answer) is not None


def score(case: Case, outcome: Outcome) -> CaseResult:
    names: tuple[str, ...]
    if case.document is None:
        names = OFF_TOPIC_CHECKS
        checks = {"not_found": outcome.label == "not_found"}
    else:
        names = ANSWERABLE_CHECKS
        answer = normalize(_MARKER.sub(" ", outcome.answer))
        checks = {
            "found": outcome.label != "not_found",
            "cited": case.document in outcome.documents,
            "supported": outcome.label == "supported",
            "facts": all(
                any(_contains(answer, normalize(alt)) for alt in entry.split("|"))
                for entry in case.expect
            ),
            "language": detect_language(outcome.answer) == case.language,
        }
    if outcome.error is not None:
        checks = dict.fromkeys(names, False)
    return CaseResult(case, outcome, checks)


def summarize(results: list[CaseResult]) -> Summary:
    checks: dict[str, tuple[int, int]] = {}
    for name in CHECK_ORDER:
        applicable = [r.checks[name] for r in results if name in r.checks]
        if applicable:
            checks[name] = (sum(applicable), len(applicable))
    return Summary(
        cases=len(results),
        passed=sum(r.passed for r in results),
        errors=sum(r.outcome.error is not None for r in results),
        checks=checks,
        median_seconds=statistics.median(r.outcome.seconds for r in results) if results else 0.0,
    )


def render(
    summary: Summary, results: list[CaseResult], provider: str | None, model: str | None
) -> str:
    lines = [
        f"## Eval: {provider or 'unknown'} / {model or 'unknown'}",
        "",
        "| check | passed |",
        "|---|---|",
        *(f"| {name} | {ok}/{total} |" for name, (ok, total) in summary.checks.items()),
        "",
        f"{summary.passed}/{summary.cases} cases passed, {summary.errors} errors, "
        f"median {summary.median_seconds:.1f} s per question",
    ]
    failed = [r for r in results if not r.passed]
    if failed:
        lines += ["", "Failed:"]
        for r in failed:
            missed = ", ".join(name for name, ok in r.checks.items() if not ok)
            detail = (
                r.outcome.error or _WHITESPACE.sub(" ", r.outcome.answer)[:_ANSWER_PREVIEW_CHARS]
            )
            lines.append(f"- {r.case.id} ({missed}): {detail}")
    return "\n".join(lines) + "\n"
