import pytest
from pydantic import ValidationError

from fontes.config import Settings


def test_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://u:p@mq:5672/")
    s = Settings()
    assert s.database_url == "postgresql+asyncpg://u:p@db:5432/x"
    assert s.rabbitmq_url == "amqp://u:p@mq:5672/"
    assert s.health_check_timeout == 3.0


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_PROVIDER", "ANTHROPIC_API_KEY", "CLAUDE_MODEL", "CLAUDE_EFFORT"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("clean_env")
def test_provider_defaults_to_ollama() -> None:
    s = Settings(_env_file=None)
    assert s.llm_provider == "ollama"
    assert s.claude_model == "claude-opus-5-5"
    assert s.claude_effort == "low"
    assert s.claude_max_tokens == 8000


@pytest.mark.usefixtures("clean_env")
@pytest.mark.parametrize("key", [None, "  "])
def test_claude_needs_a_key(key: str | None) -> None:
    with pytest.raises(ValidationError, match="LLM_PROVIDER=claude needs ANTHROPIC_API_KEY"):
        Settings(_env_file=None, llm_provider="claude", anthropic_api_key=key)


@pytest.mark.usefixtures("clean_env")
def test_claude_with_a_key() -> None:
    s = Settings(_env_file=None, llm_provider="claude", anthropic_api_key="k")
    assert s.anthropic_api_key is not None
    assert s.anthropic_api_key.get_secret_value() == "k"
    assert "'k'" not in repr(s)
