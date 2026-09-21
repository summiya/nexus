import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_SENSITIVE_FIELD_PARTS = frozenset(
    {
        "authorization",
        "cookie",
        "credential",
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "request_body",
        "response_body",
        "prompt",
    }
)
_REDACTED = "[REDACTED]"


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_FIELD_PARTS)


def _redact_sensitive_fields(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Provide defense in depth if a sensitive field is logged accidentally."""
    for key in tuple(event_dict):
        if _is_sensitive_key(key):
            event_dict[key] = _REDACTED
    return event_dict


def configure_logging(level: str | None = None) -> None:
    """Configure sink-independent structured JSON logging to stdout."""
    resolved_level = (level or "INFO").upper()
    numeric_level = getattr(logging, resolved_level, logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _redact_sensitive_fields,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return the application logging facade used by NEXUS modules."""
    return structlog.get_logger(name)
