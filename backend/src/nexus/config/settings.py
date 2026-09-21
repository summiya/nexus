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
    llm_gateway: str = Field(default="litellm", min_length=1)
    llm_allowed_models: list[str] = Field(default_factory=lambda: ["gpt-4o-mini"])
    otp_hmac_secret: str = Field(min_length=32)
    signup_otp_ttl_seconds: int = Field(default=600, gt=0)
    signup_otp_max_attempts: int = Field(default=5, gt=0)
    signup_otp_length: int = Field(default=6, ge=6, le=10)
    signup_otp_rate_limit_window_seconds: int = Field(default=900, gt=0)
    signup_otp_rate_limit_max_requests: int = Field(default=5, gt=0)
    email_provider: str = "disabled"
    email_from_address: str = "no-reply@nexus.local"
    resend_api_key: str | None = None
    auth_token_secret: str = Field(min_length=32)
    refresh_token_secret: str = Field(min_length=32)
    access_token_expires_seconds: int = Field(default=900, gt=0)
    refresh_token_expires_seconds: int = Field(default=2_592_000, gt=0)
    auth_token_issuer: str | None = None
    conversation_history_limit: int = Field(default=50, ge=1, le=200)
    conversation_history_max_chars: int = Field(default=120_000, ge=1, le=1_000_000)
    conversation_message_max_length: int = Field(default=32_000, ge=1, le=100_000)

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )


def load_settings(*, env_file: Path | None = ROOT_ENV_FILE) -> Settings:
    """Load one explicit settings instance for an application or CLI entrypoint."""

    return Settings(_env_file=env_file)  # type: ignore[call-arg]


# Transitional compatibility while runtime modules move to explicit composition.
settings = load_settings()
