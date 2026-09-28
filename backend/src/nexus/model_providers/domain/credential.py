"""Secure model-provider credential value contracts."""

from __future__ import annotations

from dataclasses import dataclass, field

from nexus.model_providers.domain.errors import ModelProviderConfigurationError

MAX_PROVIDER_CREDENTIAL_SECRET_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True, repr=False)
class ProviderCredentialSecret:
    """A credential whose plaintext requires an explicit reveal operation."""

    _value: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self._value, str)
            or not self._value.strip()
            or len(self._value.encode("utf-8")) > MAX_PROVIDER_CREDENTIAL_SECRET_BYTES
        ):
            raise ModelProviderConfigurationError(
                "Provider credential secret is invalid."
            )

    def reveal(self) -> str:
        """Return the exact credential plaintext for a trusted adapter operation."""

        return self._value

    def __str__(self) -> str:
        return "<redacted>"

    def __repr__(self) -> str:
        return "ProviderCredentialSecret(<redacted>)"


__all__ = ["MAX_PROVIDER_CREDENTIAL_SECRET_BYTES", "ProviderCredentialSecret"]
