import asyncio
import logging

from nexus.config.settings import Settings
from nexus.main import create_app


def test_settings_include_log_level_default() -> None:
    settings = Settings()

    assert settings.log_level == "INFO"


def test_configure_logging_sets_level_and_emits_message(caplog) -> None:
    logger = logging.getLogger("nexus")
    logger.setLevel(logging.WARNING)

    from nexus.config.logging import configure_logging

    configure_logging("DEBUG")

    with caplog.at_level(logging.DEBUG, logger="nexus"):
        logger.debug("debug message")

    assert logger.level == logging.DEBUG
    assert "debug message" in caplog.text


def test_create_app_logs_on_startup(caplog) -> None:
    app = create_app()

    with caplog.at_level(logging.INFO, logger="nexus"):
        asyncio.run(app.router.on_startup[0]())

    assert any("NEXUS application startup complete" in record.message for record in caplog.records)
