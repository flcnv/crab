from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    postgres_user: str = "crab"
    postgres_password: SecretStr = SecretStr("crab")
    postgres_db: str = "crab"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_user: str | None = None
    redis_password: SecretStr | None = None

    storage_dir: Path = Path("storage")

    max_upload_bytes: int = 500 * 1024 * 1024
    max_images_per_job: int = 50

    anthropic_api_key: SecretStr | None = None
    claude_model: str = "claude-sonnet-5-5"
    prompt_version: str = "v1"
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    agent_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    agent_max_turns: int = 10
    agent_max_image_views: int = 6
    claude_max_retries: int = 3
    claude_timeout_s: float = 120.0
    claude_refusal_fallback: bool = True
    llm_concurrency: int = 4
    job_timeout_s: int = 30 * 60

    verify_min_confidence: float = 0.6
    verify_size_tolerance: float = 0.15

    sample_fps: float = 1.0
    max_video_duration_s: int = 10 * 60
    max_frames: int = 12
    max_image_edge_px: int = 1500
    min_frame_sharpness: float = 60.0
    min_frame_hash_distance: int = 6

    @property
    def database_url(self) -> str:
        pw = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        auth = ""
        if self.redis_password:
            auth = f"{self.redis_user or ''}:{self.redis_password.get_secret_value()}@"
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
