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
    amqp_prefix: str = "fontes"
    ingest_max_attempts: int = 3
    ingest_retry_delay_ms: int = 5000
    worker_prefetch: int = 1
    stub_processing_seconds: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
