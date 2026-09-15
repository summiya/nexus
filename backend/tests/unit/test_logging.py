import asyncio
import json
import logging

from nexus.config.settings import Settings
from nexus.main import create_app


def test_settings_include_log_level_default() -> None:
    settings = Settings()

    assert settings.log_level == "INFO"


def test_configure_logging_sets_level_and_emits_message(capsys) -> None:
    from nexus.config.logging import configure_logging, get_logger

    configure_logging("DEBUG")
    get_logger("nexus").debug("debug_message")

    event = json.loads(capsys.readouterr().out.strip())
    assert event["event"] == "debug_message"
    assert event["level"] == "debug"
    assert logging.getLogger().level == logging.DEBUG


def test_create_app_logs_on_startup(caplog) -> None:
    app = create_app()

    with caplog.at_level(logging.INFO, logger="nexus"):
        asyncio.run(app.router.on_startup[0]())

    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "nexus" and record.getMessage().startswith("{")
    ]
    assert any(event["event"] == "application_started" for event in events)
