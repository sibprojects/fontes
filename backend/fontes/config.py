from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://fontes:fontes@localhost:25432/fontes"
    rabbitmq_url: str = "amqp://fontes:fontes@localhost:25672/"
    health_check_timeout: float = 3.0
    storage_dir: Path = Path("./data/uploads")
    max_upload_bytes: int = 20 * 1024 * 1024
    amqp_prefix: str = "fontes"
    ingest_max_attempts: int = 3
    ingest_retry_delay_ms: int = 5000
    worker_prefetch: int = 1
    publish_timeout_seconds: float = 3.0
    # Fixed by migration 0002; a different model dimension needs a new migration.
    embedding_dimension: int = 1024
    ollama_url: str = "http://localhost:11434"
    embedding_model: str = "bge-m3"
    embed_batch_size: int = 16
    ollama_timeout_seconds: float = 120.0
    url_fetch_timeout_seconds: float = 20.0
    chunk_max_chars: int = 1500
    chunk_overlap_chars: int = 200
    chunk_min_chars: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
