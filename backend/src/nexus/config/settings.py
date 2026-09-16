from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
ROOT_ENV_FILE = REPOSITORY_ROOT / ".env"


class Settings(BaseSettings):
    app_name: str = "NEXUS"
    app_env: str = "development"
    debug: bool = Field(default=False, validation_alias="APP_DEBUG")
    api_version: str = "v1"
    api_prefix: str = "/api/v1"
    database_url: str = Field(min_length=1)
    redis_url: str = Field(min_length=1)
    cors_allowed_origins: list[str]
    log_level: str = "INFO"
    otp_hmac_secret: str = Field(min_length=32)
    signup_otp_ttl_seconds: int = Field(default=600, gt=0)
    signup_otp_max_attempts: int = Field(default=5, gt=0)
    signup_otp_length: int = Field(default=6, ge=6, le=10)
    signup_otp_rate_limit_window_seconds: int = Field(default=900, gt=0)
    signup_otp_rate_limit_max_requests: int = Field(default=5, gt=0)
    email_provider: str = "disabled"
    email_from_address: str = "no-reply@nexus.local"

    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]
