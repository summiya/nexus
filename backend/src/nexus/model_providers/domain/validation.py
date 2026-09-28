"""Deterministic provider/model validation helpers."""

from __future__ import annotations

from urllib.parse import urlsplit

from nexus.model_providers.domain.errors import ModelProviderConfigurationError

MAX_DISPLAY_NAME_LENGTH = 200
MAX_PROVIDER_MODEL_NAME_LENGTH = 256
MAX_API_VERSION_LENGTH = 64
MAX_URL_LENGTH = 2048


def require_bounded_text(
    value: str,
    *,
    field_name: str,
    max_length: int,
) -> str:
    if not isinstance(value, str):
        raise ModelProviderConfigurationError(f"{field_name} must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ModelProviderConfigurationError(f"{field_name} is required.")
    if len(normalized) > max_length:
        raise ModelProviderConfigurationError(f"{field_name} is too long.")
    return normalized


def require_https_url(value: str, *, field_name: str) -> str:
    """Validate URL syntax only.

    Network and SSRF defenses such as private/loopback/link-local address checks,
    metadata-address blocking, DNS resolution, and DNS re-validation belong to a
    later infrastructure validation phase.
    """

    normalized = require_bounded_text(
        value,
        field_name=field_name,
        max_length=MAX_URL_LENGTH,
    )
    try:
        parsed = urlsplit(normalized)
    except ValueError as exc:
        raise ModelProviderConfigurationError("Provider URL is invalid.") from exc

    if not parsed.scheme:
        raise ModelProviderConfigurationError("Provider URL is invalid.")
    if parsed.scheme.lower() != "https":
        raise ModelProviderConfigurationError("Provider URL must use HTTPS.")
    if not parsed.hostname:
        raise ModelProviderConfigurationError("Provider URL is invalid.")
    if any(character.isspace() for character in parsed.netloc) or "\\" in parsed.netloc:
        raise ModelProviderConfigurationError("Provider URL is invalid.")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ModelProviderConfigurationError("Provider URL is invalid.") from exc
    if parsed.username is not None or parsed.password is not None:
        raise ModelProviderConfigurationError(
            "Provider URL must not contain credentials."
        )
    if parsed.fragment:
        raise ModelProviderConfigurationError("Provider URL is invalid.")
    return normalized


__all__ = [
    "MAX_API_VERSION_LENGTH",
    "MAX_DISPLAY_NAME_LENGTH",
    "MAX_PROVIDER_MODEL_NAME_LENGTH",
    "MAX_URL_LENGTH",
    "require_bounded_text",
    "require_https_url",
]
