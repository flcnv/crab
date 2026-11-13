from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # Postgres
    postgres_user: str = "crab"
    postgres_password: SecretStr = SecretStr("crab")
    postgres_db: str = "crab"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # Redis / arq
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_user: str | None = None  # None -> Redis "default" user
    redis_password: SecretStr | None = None

    # Storage
    storage_dir: Path = Path("storage")

    # Uploads
    max_upload_bytes: int = 500 * 1024 * 1024  # total per job
    max_images_per_job: int = 50

    # Claude
    anthropic_api_key: SecretStr | None = None
    claude_model: str = "claude-sonnet-5-5"
    claude_model_cheap: str = "claude-haiku-5-5"
    prompt_version: str = "v1"
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    claude_max_retries: int = 3  # SDK retries on 429 / 5xx / connection errors
    claude_timeout_s: float = 120.0
    claude_refusal_fallback: bool = True  # server-side fallback model on a policy refusal
    llm_concurrency: int = 4

    # Frame extraction
    sample_fps: float = 1.0
    max_frames: int = 12
    max_image_edge_px: int = 1500
    min_frame_sharpness: float = 60.0  # variance of Laplacian on a 640 px wide copy
    min_frame_hash_distance: int = 6  # dHash bits; closer frames count as duplicates

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
