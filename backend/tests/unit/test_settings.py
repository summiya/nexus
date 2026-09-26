import importlib
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pydantic_settings import SettingsError

from nexus.config.settings import ROOT_ENV_FILE, Settings, load_settings
from nexus.files.ports import ObjectStorage
from nexus.main import create_app

settings_module = importlib.import_module("nexus.config.settings")

DEVELOPMENT_FILE_UPLOAD_CONTEXT_KEY = "bmV4dXMtZGV2ZWxvcG1lbnQtdXBsb2FkLWtleS0wMDE"
PRODUCTION_FILE_UPLOAD_CONTEXT_KEY = "ZW52LWZpbGUtdXBsb2FkLWNvbnRleHQta2V5LTAwMDE"

SETTINGS_ENV_KEYS = [
    "APP_NAME",
    "APP_ENV",
    "APP_DEBUG",
    "API_VERSION",
    "API_PREFIX",
    "DATABASE_URL",
    "REDIS_URL",
    "CORS_ALLOWED_ORIGINS",
    "LOG_LEVEL",
    "LLM_GATEWAY",
    "LLM_ALLOWED_MODELS",
    "OTP_HMAC_SECRET",
    "SIGNUP_OTP_TTL_SECONDS",
    "SIGNUP_OTP_MAX_ATTEMPTS",
    "SIGNUP_OTP_LENGTH",
    "SIGNUP_OTP_RATE_LIMIT_WINDOW_SECONDS",
    "SIGNUP_OTP_RATE_LIMIT_MAX_REQUESTS",
    "EMAIL_PROVIDER",
    "EMAIL_FROM_ADDRESS",
    "RESEND_API_KEY",
    "AUTH_TOKEN_SECRET",
    "REFRESH_TOKEN_SECRET",
    "ACCESS_TOKEN_EXPIRES_SECONDS",
    "REFRESH_TOKEN_EXPIRES_SECONDS",
    "AUTH_TOKEN_ISSUER",
    "CONVERSATION_HISTORY_LIMIT",
    "CONVERSATION_HISTORY_MAX_CHARS",
    "CONVERSATION_MESSAGE_MAX_LENGTH",
    "FILE_UPLOAD_MAX_SIZE_BYTES",
    "FILE_UPLOAD_GRANT_TTL_SECONDS",
    "FILE_DOWNLOAD_GRANT_TTL_SECONDS",
    "FILE_UPLOAD_CONTEXT_KEY",
    "STORAGE_PROVIDER",
    "AZURE_STORAGE_CONTAINER",
    "AZURE_STORAGE_CONNECTION_STRING",
    "AZURE_STORAGE_ACCOUNT_URL",
    "AZURE_STORAGE_ACCOUNT_NAME",
    "AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID",
]


@pytest.fixture
def clean_environment(monkeypatch):
    for key in SETTINGS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def set_required_settings_env(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/15")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["http://localhost:5173"]')
    monkeypatch.setenv("OTP_HMAC_SECRET", "test-secret-value-with-enough-length")
    monkeypatch.setenv(
        "AUTH_TOKEN_SECRET",
        "test-auth-token-secret-with-enough-length",
    )
    monkeypatch.setenv(
        "REFRESH_TOKEN_SECRET",
        "test-refresh-token-secret-with-enough-length",
    )
    monkeypatch.setenv(
        "FILE_UPLOAD_CONTEXT_KEY",
        DEVELOPMENT_FILE_UPLOAD_CONTEXT_KEY,
    )


def build_settings(**overrides: object) -> Settings:
    values = {
        "database_url": "postgresql://test:test@localhost:5432/test",
        "redis_url": "redis://localhost:6379/15",
        "cors_allowed_origins": ["http://localhost:5173"],
        "otp_hmac_secret": "test-secret-value-with-enough-length",
        "auth_token_secret": "test-auth-token-secret-with-enough-length",
        "refresh_token_secret": "test-refresh-token-secret-with-enough-length",
        "file_upload_context_key": DEVELOPMENT_FILE_UPLOAD_CONTEXT_KEY,
        **overrides,
    }
    return Settings(_env_file=None, **values)


def test_settings_uses_expected_safe_defaults(clean_environment) -> None:
    settings = build_settings()

    assert settings.app_name == "NEXUS"
    assert settings.app_env == "development"
    assert settings.debug is False
    assert settings.api_version == "v1"
    assert settings.api_prefix == "/api/v1"
    assert settings.cors_allowed_origins == ["http://localhost:5173"]
    assert settings.log_level == "INFO"
    assert settings.llm_gateway == "litellm"
    assert settings.llm_allowed_models == ["gpt-4o-mini"]
    assert settings.signup_otp_ttl_seconds == 600
    assert settings.signup_otp_max_attempts == 5
    assert settings.signup_otp_length == 6
    assert settings.signup_otp_rate_limit_window_seconds == 900
    assert settings.signup_otp_rate_limit_max_requests == 5
    assert settings.email_provider == "disabled"
    assert settings.resend_api_key is None
    assert settings.access_token_expires_seconds == 900
    assert settings.refresh_token_expires_seconds == 2_592_000
    assert settings.auth_token_issuer is None
    assert settings.conversation_history_limit == 50
    assert settings.conversation_history_max_chars == 120_000
    assert settings.conversation_message_max_length == 32_000
    assert settings.file_upload_max_size_bytes == 536_870_912
    assert settings.file_upload_grant_ttl_seconds == 600
    assert settings.file_download_grant_ttl_seconds == 300
    assert (
        settings.file_upload_context_key.get_secret_value()
        == DEVELOPMENT_FILE_UPLOAD_CONTEXT_KEY
    )
    assert settings.storage_provider == "azure_blob"
    assert settings.azure_storage_container is None
    assert settings.azure_storage_connection_string is None
    assert settings.azure_storage_account_url is None
    assert settings.azure_storage_account_name is None
    assert settings.azure_storage_managed_identity_client_id is None


def test_database_url_is_required(clean_environment) -> None:
    values = build_settings().model_dump()
    values.pop("database_url")

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_redis_url_is_required(clean_environment) -> None:
    values = build_settings().model_dump()
    values.pop("redis_url")

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_cors_allowed_origins_is_required(clean_environment) -> None:
    values = build_settings().model_dump()
    values.pop("cors_allowed_origins")

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_file_upload_context_key_is_required(clean_environment) -> None:
    values = build_settings().model_dump()
    values.pop("file_upload_context_key")

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_settings_reads_environment_variables(monkeypatch, clean_environment) -> None:
    monkeypatch.setenv("APP_NAME", "NEXUS Test")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("APP_DEBUG", "true")
    monkeypatch.setenv("API_VERSION", "v9")
    monkeypatch.setenv("API_PREFIX", "/custom")
    monkeypatch.setenv("DATABASE_URL", "postgresql://env:env@localhost:5432/env")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/9")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["http://localhost:5173"]')
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LLM_GATEWAY", "litellm")
    monkeypatch.setenv("LLM_ALLOWED_MODELS", '["gpt-test","claude-test"]')
    monkeypatch.setenv("OTP_HMAC_SECRET", "env-secret-value-with-enough-length")
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("EMAIL_FROM_ADDRESS", "no-reply@example.com")
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "env-auth-token-secret-with-enough-length")
    monkeypatch.setenv(
        "REFRESH_TOKEN_SECRET", "env-refresh-token-secret-with-enough-length"
    )
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRES_SECONDS", "123")
    monkeypatch.setenv("REFRESH_TOKEN_EXPIRES_SECONDS", "456")
    monkeypatch.setenv("AUTH_TOKEN_ISSUER", "nexus-test")
    monkeypatch.setenv("FILE_UPLOAD_MAX_SIZE_BYTES", "104857600")
    monkeypatch.setenv("FILE_UPLOAD_GRANT_TTL_SECONDS", "900")
    monkeypatch.setenv(
        "FILE_UPLOAD_CONTEXT_KEY",
        "ZW52LWZpbGUtdXBsb2FkLWNvbnRleHQta2V5LTAwMDE",
    )
    monkeypatch.setenv("STORAGE_PROVIDER", "azure_blob")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "nexus-test-files")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_NAME", "nexustest")
    monkeypatch.setenv(
        "AZURE_STORAGE_CONNECTION_STRING",
        "UseDevelopmentStorage=true",
    )

    reloaded = Settings(_env_file=None)

    assert reloaded.app_name == "NEXUS Test"
    assert reloaded.app_env == "staging"
    assert reloaded.debug is True
    assert reloaded.api_version == "v9"
    assert reloaded.api_prefix == "/custom"
    assert reloaded.database_url == "postgresql://env:env@localhost:5432/env"
    assert reloaded.redis_url == "redis://localhost:6379/9"
    assert reloaded.cors_allowed_origins == ["http://localhost:5173"]
    assert reloaded.log_level == "DEBUG"
    assert reloaded.llm_gateway == "litellm"
    assert reloaded.llm_allowed_models == ["gpt-test", "claude-test"]
    assert reloaded.otp_hmac_secret == "env-secret-value-with-enough-length"
    assert reloaded.email_provider == "resend"
    assert reloaded.email_from_address == "no-reply@example.com"
    assert reloaded.resend_api_key == "test-resend-key"
    assert reloaded.auth_token_secret == "env-auth-token-secret-with-enough-length"
    assert (
        reloaded.refresh_token_secret == "env-refresh-token-secret-with-enough-length"
    )
    assert reloaded.access_token_expires_seconds == 123
    assert reloaded.refresh_token_expires_seconds == 456
    assert reloaded.auth_token_issuer == "nexus-test"
    assert reloaded.file_upload_max_size_bytes == 104_857_600
    assert reloaded.file_upload_grant_ttl_seconds == 900
    assert (
        reloaded.file_upload_context_key.get_secret_value()
        == "ZW52LWZpbGUtdXBsb2FkLWNvbnRleHQta2V5LTAwMDE"
    )
    assert reloaded.storage_provider == "azure_blob"
    assert reloaded.azure_storage_container == "nexus-test-files"
    assert reloaded.azure_storage_account_name == "nexustest"
    assert reloaded.azure_storage_connection_string is not None
    assert (
        reloaded.azure_storage_connection_string.get_secret_value()
        == "UseDevelopmentStorage=true"
    )


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [("true", True), ("false", False)],
)
def test_debug_boolean_values(
    monkeypatch, clean_environment, raw_value: str, expected: bool
) -> None:
    set_required_settings_env(monkeypatch)
    monkeypatch.setenv("APP_DEBUG", raw_value)

    settings = Settings(_env_file=None)

    assert settings.debug is expected


def test_invalid_debug_boolean_fails_validation(monkeypatch, clean_environment) -> None:
    set_required_settings_env(monkeypatch)
    monkeypatch.setenv("APP_DEBUG", "definitely")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_blank_llm_gateway_fails_validation(clean_environment) -> None:
    with pytest.raises(ValidationError):
        build_settings(llm_gateway="")


@pytest.mark.parametrize("value", [0, -1])
def test_non_positive_file_upload_max_size_fails_validation(
    clean_environment,
    value: int,
) -> None:
    with pytest.raises(ValidationError):
        build_settings(file_upload_max_size_bytes=value)


@pytest.mark.parametrize("value", [0, -1, 3601])
def test_invalid_file_upload_grant_ttl_fails_validation(
    clean_environment,
    value: int,
) -> None:
    with pytest.raises(ValidationError):
        build_settings(file_upload_grant_ttl_seconds=value)


@pytest.mark.parametrize(
    "value",
    ["", "not-base64!", "dG9vLXNob3J0"],
)
def test_invalid_file_upload_context_key_fails_validation(
    clean_environment,
    value: str,
) -> None:
    with pytest.raises(ValidationError):
        build_settings(file_upload_context_key=value)


def test_development_environment_allows_development_upload_context_key(
    clean_environment,
) -> None:
    settings = build_settings(
        app_env="development",
        file_upload_context_key=DEVELOPMENT_FILE_UPLOAD_CONTEXT_KEY,
    )

    assert settings.file_upload_context_key.get_secret_value() == (
        DEVELOPMENT_FILE_UPLOAD_CONTEXT_KEY
    )


def test_production_environment_rejects_development_upload_context_key(
    clean_environment,
) -> None:
    with pytest.raises(ValidationError) as captured:
        build_settings(
            app_env="production",
            file_upload_context_key=DEVELOPMENT_FILE_UPLOAD_CONTEXT_KEY,
        )

    error = str(captured.value)
    assert "Production File upload context key must be overridden." in error
    assert DEVELOPMENT_FILE_UPLOAD_CONTEXT_KEY not in error


def test_production_environment_allows_distinct_upload_context_key(
    clean_environment,
) -> None:
    settings = build_settings(
        app_env="production",
        file_upload_context_key=PRODUCTION_FILE_UPLOAD_CONTEXT_KEY,
    )

    assert settings.file_upload_context_key.get_secret_value() == (
        PRODUCTION_FILE_UPLOAD_CONTEXT_KEY
    )


def test_valid_cors_list_parses(monkeypatch, clean_environment) -> None:
    set_required_settings_env(monkeypatch)
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        '["http://localhost:5173","https://nexus.example"]',
    )

    settings = Settings(_env_file=None)

    assert settings.cors_allowed_origins == [
        "http://localhost:5173",
        "https://nexus.example",
    ]


def test_malformed_cors_configuration_fails(monkeypatch, clean_environment) -> None:
    set_required_settings_env(monkeypatch)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "not-json")

    with pytest.raises(SettingsError):
        Settings(_env_file=None)


def test_load_settings_uses_explicit_env_file(
    tmp_path: Path,
    clean_environment,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_NAME=NEXUS Explicit\n"
        "DATABASE_URL=postgresql://file:file@localhost:5432/file\n"
        "REDIS_URL=redis://localhost:6379/8\n"
        'CORS_ALLOWED_ORIGINS=["http://localhost:5173"]\n'
        "OTP_HMAC_SECRET=file-secret-value-with-enough-length\n"
        "AUTH_TOKEN_SECRET=file-auth-token-secret-with-enough-length\n"
        "REFRESH_TOKEN_SECRET=file-refresh-token-secret-with-enough-length\n"
        "FILE_UPLOAD_CONTEXT_KEY="
        "ZmlsZS11cGxvYWQtY29udGV4dC1rZXktMDAwMDAwMDA",
        encoding="utf-8",
    )

    loaded = load_settings(env_file=env_file)

    assert loaded.app_name == "NEXUS Explicit"
    assert loaded.database_url.endswith("/file")
    assert Settings.model_config.get("env_file") is None
    assert ROOT_ENV_FILE.name == ".env"


def test_settings_module_has_no_eager_global_configuration() -> None:
    assert "settings" not in vars(settings_module)


def test_create_app_uses_explicit_settings() -> None:
    app_settings = build_settings(APP_DEBUG=True, api_prefix="/api/test")
    app = create_app(
        app_settings,
        object_storage=Mock(spec=ObjectStorage),
    )

    with TestClient(app) as client:
        response = client.get("/api/test/health")

    assert app.state.container.settings is app_settings
    assert app.debug is True
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_sensitive_configuration_is_not_logged(caplog) -> None:
    secret_database_url = "postgresql://user:password@localhost:5432/secret"
    secret_redis_url = "redis://:password@localhost:6379/0"

    with caplog.at_level(logging.INFO, logger="nexus"):
        logging.getLogger("nexus").info("NEXUS application startup complete")

    assert secret_database_url not in caplog.text
    assert secret_redis_url not in caplog.text


def test_storage_connection_string_is_redacted_from_settings_representation() -> None:
    connection_string = "AccountName=nexus;AccountKey=top-secret-value"

    settings = build_settings(azure_storage_connection_string=connection_string)

    assert connection_string not in repr(settings)
    assert connection_string not in str(settings)


def test_file_upload_context_key_is_redacted_from_settings_representation() -> None:
    key = DEVELOPMENT_FILE_UPLOAD_CONTEXT_KEY

    settings = build_settings(file_upload_context_key=key)

    assert key not in repr(settings)
    assert key not in str(settings)


@pytest.mark.parametrize("ttl", [0, -1, 901])
def test_file_download_grant_ttl_must_remain_short(ttl: int) -> None:
    with pytest.raises(ValidationError):
        build_settings(file_download_grant_ttl_seconds=ttl)
