import logging

from nexus.config.settings import settings

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: str | None = None) -> logging.Logger:
    resolved_level = (level or settings.log_level or "INFO").upper()
    numeric_level = getattr(logging, resolved_level, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    if not root_logger.handlers:
        handler: logging.Handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setLevel(numeric_level)
            handler.setFormatter(logging.Formatter(LOG_FORMAT))

    logger = logging.getLogger("nexus")
    logger.setLevel(numeric_level)
    return logger
