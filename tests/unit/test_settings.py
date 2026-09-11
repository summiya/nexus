import importlib

from nexus.config.settings import Settings

settings_module = importlib.import_module("nexus.config.settings")


def test_settings_uses_expected_defaults() -> None:
    settings = Settings()

    assert settings.app_name == "NEXUS"
    assert settings.api_version == "v1"
    assert settings.environment == "development"


def test_settings_reads_environment_variables(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "NEXUS Test")
    monkeypatch.setenv("API_VERSION", "v9")
    monkeypatch.setenv("ENVIRONMENT", "staging")

    reloaded = Settings()

    assert reloaded.app_name == "NEXUS Test"
    assert reloaded.api_version == "v9"
    assert reloaded.environment == "staging"


def test_application_settings_module_exposes_single_configuration(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "NEXUS Config")
    monkeypatch.setenv("API_VERSION", "v2")
    monkeypatch.setenv("ENVIRONMENT", "production")

    importlib.reload(settings_module)

    assert settings_module.settings.app_name == "NEXUS Config"
    assert settings_module.settings.api_version == "v2"
    assert settings_module.settings.environment == "production"

    importlib.reload(settings_module)
