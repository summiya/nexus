"""Provider configuration validation state."""

from __future__ import annotations

from enum import StrEnum

from nexus.model_providers.domain.errors import ModelProviderConfigurationError


class ProviderValidationStatus(StrEnum):
    """Current validation state for one configured provider."""

    UNVALIDATED = "unvalidated"
    VALID = "valid"
    INVALID_CREDENTIALS = "invalid_credentials"
    UNREACHABLE = "unreachable"
    UNSUPPORTED_CONFIGURATION = "unsupported_configuration"

    @classmethod
    def _missing_(cls, value: object) -> ProviderValidationStatus:
        raise ModelProviderConfigurationError("Provider validation status is invalid.")


TERMINAL_PROVIDER_VALIDATION_STATUSES = frozenset(
    {
        ProviderValidationStatus.VALID,
        ProviderValidationStatus.INVALID_CREDENTIALS,
        ProviderValidationStatus.UNREACHABLE,
        ProviderValidationStatus.UNSUPPORTED_CONFIGURATION,
    }
)


__all__ = [
    "TERMINAL_PROVIDER_VALIDATION_STATUSES",
    "ProviderValidationStatus",
]
