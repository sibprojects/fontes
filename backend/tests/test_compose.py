"""Settings the README tells users to tune must actually reach the api container."""

import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"

TUNABLE = [
    "CHAT_MODEL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_NUM_CTX",
    "LLM_TEMPERATURE",
    "LLM_MAX_TOKENS",
    "ASK_TOP_K",
    "ASK_MIN_SCORE",
    "QUESTION_MAX_CHARS",
]


def _service(name: str) -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    match = re.search(rf"^  {name}:\n(.*?)(?=^  \S|^\S|\Z)", text, re.M | re.S)
    assert match, name
    return match.group(1)


def test_api_forwards_every_ask_setting() -> None:
    api = _service("api")
    missing = [n for n in TUNABLE if not re.search(rf"^\s+{n}: \${{{n}(:-[^}}]*)?}}", api, re.M)]
    assert missing == []
