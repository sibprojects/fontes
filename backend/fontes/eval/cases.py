"""The eval set: questions about the fictional samples, each with what a good answer holds."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LANGUAGES = ("en", "ru")
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASES = REPO_ROOT / "eval" / "cases.toml"
DEFAULT_SAMPLES = REPO_ROOT / "docs" / "samples"


@dataclass(frozen=True)
class Case:
    """One question. `document=None` means off-topic: the right answer is `not_found`.

    Each `expect` entry is a set of alternatives separated by `|`; one of them must appear
    in the answer.
    """

    id: str
    question: str
    document: str | None
    expect: tuple[str, ...]
    language: str


class CaseError(ValueError):
    """The cases file is malformed; the message names the case."""


def load_cases(path: Path, samples_dir: Path) -> list[Case]:
    data: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    samples = {p.name for p in samples_dir.iterdir()}
    cases: list[Case] = []
    seen: set[str] = set()
    for index, raw in enumerate(data.get("case", []), 1):
        case = _case(index, raw)
        _check(case, seen, samples)
        seen.add(case.id)
        cases.append(case)
    return cases


def _case(index: int, raw: dict[str, Any]) -> Case:
    name = f"case {index} ({raw.get('id')!r})"
    for key in ("id", "question", "language"):
        if not isinstance(raw.get(key), str):
            raise CaseError(f"{name}: {key} must be a string")
    document = raw.get("document")
    if document is not None and not isinstance(document, str):
        raise CaseError(f"{name}: document must be a string")
    expect = raw.get("expect", [])
    if not isinstance(expect, list) or not all(isinstance(e, str) for e in expect):
        raise CaseError(f"{name}: expect must be a list of strings")
    return Case(raw["id"], raw["question"], document, tuple(expect), raw["language"])


def _check(case: Case, seen: set[str], samples: set[str]) -> None:
    if case.id in seen:
        raise CaseError(f"case {case.id!r} is defined twice")
    if not case.question.strip():
        raise CaseError(f"case {case.id!r} has a blank question")
    if case.language not in LANGUAGES:
        raise CaseError(f"case {case.id!r}: language {case.language!r} is not one of {LANGUAGES}")
    if case.document is not None and case.document not in samples:
        raise CaseError(f"case {case.id!r}: no sample named {case.document!r}")
    if case.document is not None and not case.expect:
        raise CaseError(f"case {case.id!r} names a document but expects nothing")
    if case.document is None and case.expect:
        raise CaseError(f"case {case.id!r} is off-topic but expects facts")
