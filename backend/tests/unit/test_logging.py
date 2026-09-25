import json
import logging
from unittest.mock import Mock

from fastapi.testclient import TestClient

from nexus.config.settings import Settings
from nexus.files.ports import ObjectStorage
from nexus.main import create_app


def build_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=["http://localhost:5173"],
        otp_hmac_secret="test-secret-value-with-enough-length",
        auth_token_secret="test-auth-token-secret-with-enough-length",
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
        file_upload_context_key=("bmV4dXMtZGV2ZWxvcG1lbnQtdXBsb2FkLWtleS0wMDE"),
    )


def test_settings_include_log_level_default() -> None:
    settings = build_settings()

    assert settings.log_level == "INFO"


def test_configure_logging_sets_level_and_emits_message(capsys) -> None:
    from nexus.config.logging import configure_logging, get_logger

    configure_logging("DEBUG")
    get_logger("nexus").debug("debug_message")

    event = json.loads(capsys.readouterr().out.strip())
    assert event["event"] == "debug_message"
    assert event["level"] == "debug"
    assert logging.getLogger().level == logging.DEBUG


def test_create_app_logs_startup_and_shutdown(capsys) -> None:
    app = create_app(
        build_settings(),
        object_storage=Mock(spec=ObjectStorage),
    )

    with TestClient(app):
        pass

    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    assert any(event["event"] == "application_started" for event in events)
    assert any(event["event"] == "application_stopped" for event in events)
