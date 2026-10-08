"""Application configuration.

Every value is overridable through environment variables so the same image can be
deployed to development and production (specification section 17.2).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    # --- Service -----------------------------------------------------------
    environment: Literal["development", "production"] = "development"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]

    # --- Persistence -------------------------------------------------------
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "ai_analysis_team"

    # --- Object storage (originals, recordings, exports) -------------------
    s3_endpoint: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "ai-analysis-team"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_secure: bool = False
    # When object storage is unavailable the service falls back to a local
    # company controlled volume. Never to a third party location.
    storage_fallback_dir: str = "./var/storage"

    # --- Identity ----------------------------------------------------------
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 12 * 60
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None

    # --- Limits (section 6.2) ---------------------------------------------
    max_document_bytes: int = 100 * 1024 * 1024
    max_recording_bytes: int = 2 * 1024 * 1024 * 1024
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024

    # --- AI gateway (section 8.3) -----------------------------------------
    default_local_model: str = "local/analysis-7b"
    local_inference_url: str | None = None
    cloud_provider: Literal["none", "anthropic", "openai"] = "none"
    cloud_api_key: str | None = None
    cloud_model: str = "claude-sonnet-5"
    # Global kill switch. A project may be stricter, never looser.
    cloud_enabled_globally: bool = False
    ai_monthly_budget_eur: float = 0.0

    # --- Delivery defaults (section 11) ------------------------------------
    default_hours_per_person_day: float = 8.0
    default_currency: str = "EUR"
    default_timezone: str = "Europe/Athens"
    calibration_min_cohort: int = 30
    max_correction_cycles: int = 3

    # --- Workers -----------------------------------------------------------
    worker_poll_seconds: float = 1.0
    worker_concurrency: int = 2

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
