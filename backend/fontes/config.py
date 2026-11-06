from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://fontes:fontes@localhost:5432/fontes"
    rabbitmq_url: str = "amqp://fontes:fontes@localhost:5672/"
    health_check_timeout: float = 3.0
    storage_dir: Path = Path("./data/uploads")
    max_upload_bytes: int = 20 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
