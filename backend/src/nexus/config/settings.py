import base64
import binascii
from pathlib import Path
from uuid import UUID

from pydantic import Field, HttpUrl, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
ROOT_ENV_FILE = REPOSITORY_ROOT / ".env"
_DEVELOPMENT_FILE_UPLOAD_CONTEXT_KEY = b"nexus-development-upload-key-001"


def validate_file_upload_context_key(
    value: SecretStr,
    *,
    app_env: object,
) -> SecretStr:
    """Validate the shared API/worker UploadContext protection key."""
    encoded = value.get_secret_value()
    try:
        padding = "=" * (-len(encoded) % 4)
        decoded = base64.b64decode(
            encoded + padding,
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as exc:
        raise ValueError("File upload context key is invalid") from exc
    if len(decoded) != 32:
        raise ValueError("File upload context key is invalid")
    if app_env == "production" and decoded == _DEVELOPMENT_FILE_UPLOAD_CONTEXT_KEY:
        raise ValueError("Production File upload context key must be overridden.")
    return value


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
    file_upload_max_size_bytes: int = Field(default=536_870_912, gt=0)
    file_upload_grant_ttl_seconds: int = Field(default=600, gt=0, le=3600)
    file_upload_context_key: SecretStr
    storage_provider: str = Field(default="azure_blob", min_length=1)
    azure_storage_container: str | None = None
    azure_storage_connection_string: SecretStr | None = None
    azure_storage_account_url: HttpUrl | None = None
    azure_storage_account_name: str | None = None
    azure_storage_managed_identity_client_id: UUID | None = None

    @field_validator("file_upload_context_key")
    @classmethod
    def validate_file_upload_context_key(
        cls,
        value: SecretStr,
        info: ValidationInfo,
    ) -> SecretStr:
        return validate_file_upload_context_key(
            value,
            app_env=info.data.get("app_env"),
        )

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )


def load_settings(*, env_file: Path | None = ROOT_ENV_FILE) -> Settings:
    """Load one explicit settings instance for an application or CLI entrypoint."""

    return Settings(_env_file=env_file)  # type: ignore[call-arg]
