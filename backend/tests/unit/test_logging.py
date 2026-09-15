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


def test_create_app_logs_on_startup(capsys) -> None:
    app = create_app()

    asyncio.run(app.router.on_startup[0]())

    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    assert any(event["event"] == "application_started" for event in events)
