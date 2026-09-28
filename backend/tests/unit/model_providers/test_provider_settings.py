from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from nexus.model_providers.application import ListProviderCatalog
from nexus.model_providers.domain import (
    AnthropicSettings,
    AzureOpenAISettings,
    GeminiSettings,
    ModelProviderConfigurationError,
    OpenAICompatibleSettings,
    OpenAISettings,
    ProviderSettings,
    ProviderType,
    provider_endpoint_url,
    provider_required_setting_names,
    provider_settings_from_mapping,
    provider_settings_to_mapping,
)


class AllowAllPermissions:
    async def has_permission(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        permission_key: str,
    ) -> bool:
        return True


_SETTINGS_CASES: tuple[tuple[ProviderType, dict[str, str], ProviderSettings], ...] = (
    (ProviderType.OPENAI, {}, OpenAISettings()),
    (ProviderType.ANTHROPIC, {}, AnthropicSettings()),
    (
        ProviderType.AZURE_OPENAI,
        {
            "endpoint": "https://azure.example.com",
            "api_version": "2026-01-01",
        },
        AzureOpenAISettings(
            endpoint="https://azure.example.com",
            api_version="2026-01-01",
        ),
    ),
    (ProviderType.GEMINI, {}, GeminiSettings()),
    (
        ProviderType.OPENAI_COMPATIBLE,
        {"base_url": "https://compatible.example.com"},
        OpenAICompatibleSettings(base_url="https://compatible.example.com"),
    ),
)


@pytest.mark.parametrize(("provider_type", "mapping", "expected"), _SETTINGS_CASES)
def test_provider_settings_mapping_round_trips_every_provider_type(
    provider_type: ProviderType,
    mapping: dict[str, str],
    expected: ProviderSettings,
) -> None:
    settings = provider_settings_from_mapping(provider_type, mapping)

    assert settings == expected
    assert provider_settings_to_mapping(settings) == mapping


@pytest.mark.parametrize(
    ("provider_type", "mapping"),
    (
        (ProviderType.AZURE_OPENAI, {"endpoint": "https://azure.example.com"}),
        (ProviderType.OPENAI, {"unexpected": "value"}),
        (
            ProviderType.OPENAI_COMPATIBLE,
            {"base_url": 42},
        ),
    ),
)
def test_provider_settings_mapping_rejects_invalid_input(
    provider_type: ProviderType,
    mapping: dict[str, object],
) -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match="Provider settings are invalid",
    ):
        provider_settings_from_mapping(provider_type, mapping)


@pytest.mark.parametrize(("provider_type", "mapping", "expected"), _SETTINGS_CASES)
def test_provider_endpoint_url_is_canonical_for_every_provider_type(
    provider_type: ProviderType,
    mapping: dict[str, str],
    expected: ProviderSettings,
) -> None:
    del provider_type, mapping

    expected_url = (
        expected.endpoint
        if isinstance(expected, AzureOpenAISettings)
        else expected.base_url
        if isinstance(expected, OpenAICompatibleSettings)
        else None
    )
    assert provider_endpoint_url(expected) == expected_url


def test_catalog_required_settings_match_domain_mapping_contract() -> None:
    items = asyncio.run(
        ListProviderCatalog(
            permission_checker=AllowAllPermissions(),  # type: ignore[arg-type]
        ).execute(
            organization_public_id=uuid4(),
            user_public_id=uuid4(),
        )
    )
    sample_values = {
        "endpoint": "https://azure.example.com",
        "api_version": "2026-01-01",
        "base_url": "https://compatible.example.com",
    }

    assert {item.provider_type for item in items} == set(ProviderType)
    for item in items:
        assert item.required_settings == provider_required_setting_names(
            item.provider_type
        )
        mapping = {name: sample_values[name] for name in item.required_settings}
        provider_settings_from_mapping(item.provider_type, mapping)
