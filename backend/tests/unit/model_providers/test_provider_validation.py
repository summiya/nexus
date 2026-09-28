from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nexus.model_providers.domain import (
    ConfiguredProvider,
    ModelProviderConfigurationError,
    OpenAISettings,
    OrganizationProviderId,
    ProviderType,
    ProviderValidationStatus,
)


def _provider(**changes: object) -> ConfiguredProvider:
    values: dict[str, object] = {
        "organization_public_id": uuid4(),
        "provider_id": OrganizationProviderId(uuid4()),
        "provider_type": ProviderType.OPENAI,
        "display_name": "OpenAI",
        "settings": OpenAISettings(),
        "enabled": True,
    }
    values.update(changes)
    return ConfiguredProvider(**values)  # type: ignore[arg-type]


def test_new_provider_is_unvalidated() -> None:
    provider = _provider()

    assert provider.validation_status is ProviderValidationStatus.UNVALIDATED
    assert provider.last_validated_at is None


def test_terminal_validation_requires_aware_timestamp() -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Validated provider must have a timezone-aware timestamp\.$",
    ):
        _provider(validation_status=ProviderValidationStatus.VALID)


def test_terminal_validation_accepts_aware_timestamp() -> None:
    timestamp = datetime(2026, 9, 29, tzinfo=UTC)

    provider = _provider(
        validation_status=ProviderValidationStatus.VALID,
        last_validated_at=timestamp,
    )

    assert provider.last_validated_at == timestamp


def test_unvalidated_rejects_timestamp() -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Unvalidated provider cannot have a validation timestamp\.$",
    ):
        _provider(last_validated_at=datetime(2026, 9, 29, tzinfo=UTC))


def test_unknown_validation_status_uses_domain_error() -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Provider validation status is invalid\.$",
    ):
        ProviderValidationStatus("other")
