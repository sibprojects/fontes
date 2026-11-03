import pytest

from fontes.config import Settings


def test_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://u:p@mq:5672/")
    s = Settings()
    assert s.database_url == "postgresql+asyncpg://u:p@db:5432/x"
    assert s.rabbitmq_url == "amqp://u:p@mq:5672/"
    assert s.health_check_timeout == 3.0
