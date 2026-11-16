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


def test_frontend_proxies_api_without_buffering() -> None:
    frontend = _service("frontend")
    assert "build: ./frontend" in frontend
    assert '"28080:80"' in frontend
    conf = (COMPOSE.parent / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    # The api's address is looked up per request through Docker's DNS, so a recreated api
    # container (new IP) is found again; the /api prefix is stripped, as the Vite proxy does.
    assert "resolver 127.0.0.11" in conf
    assert "set $api http://api:8000;" in conf
    assert "rewrite ^/api/(.*)$ /$1 break;" in conf
    assert "proxy_pass $api;" in conf
    # SSE tokens must reach the browser as they are written.
    assert "proxy_buffering off;" in conf
    # Above the 20 MiB upload limit, so a too-large file gets the API's JSON 413.
    body = re.search(r"client_max_body_size\s+(\d+)m;", conf)
    assert body
    assert int(body[1]) > 20


def test_frontend_index_is_revalidated() -> None:
    conf = (COMPOSE.parent / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    # index.html names the hashed assets of one build; a cached copy after a rebuild points
    # at files that no longer exist and the page is blank. Hashed assets may be cached.
    index = re.search(r"location = /index\.html \{(.*?)\}", conf, re.S)
    assert index
    assert 'add_header Cache-Control "no-cache";' in index[1]
