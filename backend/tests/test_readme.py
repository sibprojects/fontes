"""The README is the portfolio's front page: its links must resolve and its diagram must exist."""

import re
from pathlib import Path

README = Path(__file__).resolve().parents[2] / "README.md"


def test_readme_links_point_at_files() -> None:
    text = README.read_text(encoding="utf-8")
    targets = re.findall(r"\]\(((?!https?://|#)[^)\s]+)\)", text)
    assert any(t.startswith("docs/screenshots/") for t in targets)
    missing = [t for t in targets if not (README.parent / t).exists()]
    assert missing == []


def test_readme_has_the_architecture_diagram() -> None:
    text = README.read_text(encoding="utf-8")
    assert "```mermaid" in text
    diagram = text.split("```mermaid", 1)[1].split("```", 1)[0]
    for node in ("nginx", "api", "worker", "RabbitMQ", "Postgres", "Ollama", "Claude"):
        assert node in diagram, node
    assert "Work in progress" not in text


def test_claude_section_says_where_the_startup_error_is() -> None:
    # Without a key the api restarts in a loop and the UI only sees 502s.
    text = README.read_text(encoding="utf-8")
    section = text.split("## Switch to Claude", 1)[1].split("\n## ", 1)[0]
    assert "docker compose logs api" in section
    assert "is not downloaded" in section
