from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(REPO_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"

    # --- data stores ---
    database_url: str = "postgresql+asyncpg://complaint:complaint_dev_pw@localhost:15432/complaints"
    database_pool_size: int = 10
    redis_url: str = "redis://localhost:16379/0"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:15173"])

    # --- AI ---
    llm_provider: Literal["mock", "openai"] = "mock"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = ""  # optional: proxy / Azure-compatible endpoint
    openai_timeout_seconds: float = 30.0
    openai_max_retries: int = 1  # SDK retries 429/5xx/connection errors with backoff
    # Used only to show an estimated cost per call (USD per 1M tokens; gpt-4o-mini list price).
    openai_input_usd_per_1m: float = 0.15
    openai_output_usd_per_1m: float = 0.60
    sentiment_model: str = "nlptown/bert-base-multilingual-uncased-sentiment"
    # Load the Hugging Face model. Tests switch this off and use a tiny lexicon fallback.
    enable_transformers: bool = True
    hf_home: Path = REPO_DIR / "ml" / ".hf_cache"
    artifacts_dir: Path = REPO_DIR / "ml" / "artifacts"
    # Category predictions below this confidence are flagged for human review.
    review_threshold: float = 0.45

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
