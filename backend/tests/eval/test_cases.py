from pathlib import Path

import pytest

from fontes.eval.cases import DEFAULT_CASES, DEFAULT_SAMPLES, CaseError, load_cases


def test_the_eval_set_loads() -> None:
    cases = load_cases(DEFAULT_CASES, DEFAULT_SAMPLES)
    assert len(cases) == 24
    assert len({c.id for c in cases}) == 24
    assert sum(c.document is None for c in cases) == 4
    assert {c.document for c in cases if c.document} == {"lumen-kettle.md", "sad-pravila.md"}


GOOD = 'id = "y"\nquestion = "Q?"\ndocument = "a.md"\nexpect = ["1"]\nlanguage = "en"\n'


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        (
            '[[case]]\nid = "x"\nquestion = "Q?"\nlanguage = "en"\n'
            '[[case]]\nid = "x"\nquestion = "R?"\nlanguage = "en"\n',
            "x",
        ),
        ('[[case]]\nid = "x"\nquestion = "  "\nlanguage = "en"\n', "x"),
        ('[[case]]\nid = "x"\nquestion = "Q?"\nlanguage = "de"\n', "de"),
        (
            '[[case]]\nid = "x"\nquestion = "Q?"\ndocument = "b.md"\nexpect = ["1"]\n'
            'language = "en"\n',
            "b.md",
        ),
        ('[[case]]\nid = "x"\nquestion = "Q?"\ndocument = "a.md"\nlanguage = "en"\n', "x"),
        ('[[case]]\nid = "x"\nquestion = "Q?"\nexpect = ["1"]\nlanguage = "en"\n', "x"),
    ],
    ids=[
        "repeated-id",
        "blank-question",
        "language",
        "unknown-document",
        "no-expect",
        "off-topic-expect",
    ],
)
def test_bad_cases_are_refused(tmp_path: Path, toml: str, message: str) -> None:
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "a.md").write_text("# A\n", encoding="utf-8")
    cases = tmp_path / "cases.toml"
    cases.write_text(f"[[case]]\n{GOOD}{toml}", encoding="utf-8")
    with pytest.raises(CaseError, match=message):
        load_cases(cases, samples)


def test_a_good_file_loads(tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "a.md").write_text("# A\n", encoding="utf-8")
    cases = tmp_path / "cases.toml"
    cases.write_text(
        f'[[case]]\n{GOOD}[[case]]\nid = "z"\nquestion = "Off?"\nlanguage = "ru"\n',
        encoding="utf-8",
    )
    first, second = load_cases(cases, samples)
    assert (first.id, first.document, first.expect, first.language) == ("y", "a.md", ("1",), "en")
    assert (second.id, second.document, second.expect) == ("z", None, ())


def test_a_missing_key_names_the_case(tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "a.md").write_text("# A\n", encoding="utf-8")
    cases = tmp_path / "cases.toml"
    cases.write_text(f'[[case]]\n{GOOD}[[case]]\nid = "z"\nlanguage = "en"\n', encoding="utf-8")
    with pytest.raises(CaseError, match=r"case 2 \('z'\).*question"):
        load_cases(cases, samples)


def test_a_document_must_be_a_string(tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    samples.mkdir()
    cases = tmp_path / "cases.toml"
    cases.write_text(
        '[[case]]\nid = "x"\nquestion = "Q?"\ndocument = ["a.md"]\n'
        'expect = ["1"]\nlanguage = "en"\n',
        encoding="utf-8",
    )
    with pytest.raises(CaseError, match="x"):
        load_cases(cases, samples)
