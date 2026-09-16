"""Shared authentication input validation helpers."""

from __future__ import annotations

import re
import unicodedata

from nexus.domain.users import normalize_email
from nexus.errors import ErrorCode, NexusError

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_display_text(value: str, field_name: str, *, max_length: int) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        raise_validation_error(field_name)
    if len(normalized) > max_length:
        raise_validation_error(field_name)
    return normalized


def normalize_signup_email(value: str) -> str:
    email = normalize_email(value)
    if len(email) > 320 or _EMAIL_RE.fullmatch(email) is None:
        raise_validation_error("email")
    return email


def raise_validation_error(field_name: str) -> None:
    raise NexusError(
        ErrorCode.VALIDATION_ERROR,
        "The request validation failed.",
        details={"field": field_name},
    )
