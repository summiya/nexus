import importlib
import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pydantic_settings import SettingsError

from nexus.config.settings import ROOT_ENV_FILE, Settings

settings_module = importlib.import_module("nexus.config.settings")
main_module = importlib.import_module("nexus.main")

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
]


@pytest.fixture
def clean_environment(monkeypatch):
    for key in SETTINGS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def build_settings(**overrides: object) -> Settings:
    values = {
        "database_url": "postgresql://test:test@localhost:5432/test",
        "redis_url": "redis://localhost:6379/15",
        "cors_allowed_origins": ["http://localhost:5173"],
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


def test_database_url_is_required(clean_environment) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, redis_url="redis://localhost:6379/15")


def test_redis_url_is_required(clean_environment) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql://test:test@localhost:5432/test",
            cors_allowed_origins=["http://localhost:5173"],
        )


def test_cors_allowed_origins_is_required(clean_environment) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/15",
        )


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


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("true", True),
        ("false", False),
    ],
)
def test_debug_boolean_values(
    monkeypatch, clean_environment, raw_value: str, expected: bool
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/15")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["http://localhost:5173"]')
    monkeypatch.setenv("APP_DEBUG", raw_value)

    settings = Settings(_env_file=None)

    assert settings.debug is expected


def test_invalid_debug_boolean_fails_validation(monkeypatch, clean_environment) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/15")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["http://localhost:5173"]')
    monkeypatch.setenv("APP_DEBUG", "definitely")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_valid_cors_list_parses(monkeypatch, clean_environment) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/15")
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
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/15")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "not-json")

    with pytest.raises(SettingsError):
        Settings(_env_file=None)


def test_settings_loads_root_env_file_deterministically() -> None:
    assert Settings.model_config["env_file"] == ROOT_ENV_FILE


def test_application_settings_module_exposes_single_configuration(
    monkeypatch, clean_environment
) -> None:
    monkeypatch.setenv("APP_NAME", "NEXUS Config")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_DEBUG", "false")
    monkeypatch.setenv("API_VERSION", "v2")
    monkeypatch.setenv("API_PREFIX", "/api/v2")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/15")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["http://localhost:5173"]')

    importlib.reload(settings_module)

    assert settings_module.settings.app_name == "NEXUS Config"
    assert settings_module.settings.app_env == "production"
    assert settings_module.settings.debug is False
    assert settings_module.settings.api_version == "v2"
    assert settings_module.settings.api_prefix == "/api/v2"

    importlib.reload(settings_module)


def test_create_app_uses_debug_and_api_prefix(monkeypatch, clean_environment) -> None:
    monkeypatch.setenv("APP_DEBUG", "true")
    monkeypatch.setenv("API_PREFIX", "/api/test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/15")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["http://localhost:5173"]')
    importlib.reload(settings_module)
    reloaded_main = importlib.reload(main_module)

    app = reloaded_main.create_app()
    response = TestClient(app).get("/api/test/health")

    assert app.debug is True
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    importlib.reload(settings_module)
    importlib.reload(main_module)


def test_sensitive_configuration_is_not_logged(caplog) -> None:
    secret_database_url = "postgresql://user:password@localhost:5432/secret"
    secret_redis_url = "redis://:password@localhost:6379/0"

    with caplog.at_level(logging.INFO, logger="nexus"):
        logging.getLogger("nexus").info("NEXUS application startup complete")

    assert secret_database_url not in caplog.text
    assert secret_redis_url not in caplog.text
