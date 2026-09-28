"""Canonical model-provider settings mapping and endpoint rules."""

from __future__ import annotations

from collections.abc import Mapping
from typing import assert_never, cast

from nexus.model_providers.domain.contracts import (
    AnthropicSettings,
    AzureOpenAISettings,
    GeminiSettings,
    OpenAICompatibleSettings,
    OpenAISettings,
    ProviderSettings,
    ProviderType,
)
from nexus.model_providers.domain.errors import ModelProviderConfigurationError


def provider_required_setting_names(provider_type: ProviderType) -> tuple[str, ...]:
    """Return the complete ordered non-secret settings contract for a provider."""

    if not isinstance(provider_type, ProviderType):
        raise ModelProviderConfigurationError("Unknown provider type.")
    if provider_type is ProviderType.OPENAI:
        return ()
    if provider_type is ProviderType.ANTHROPIC:
        return ()
    if provider_type is ProviderType.AZURE_OPENAI:
        return ("endpoint", "api_version")
    if provider_type is ProviderType.GEMINI:
        return ()
    if provider_type is ProviderType.OPENAI_COMPATIBLE:
        return ("base_url",)
    assert_never(provider_type)


def provider_settings_from_mapping(
    provider_type: ProviderType,
    values: Mapping[str, object],
) -> ProviderSettings:
    """Construct validated provider settings from one exact plain mapping."""

    required_names = provider_required_setting_names(provider_type)
    if not isinstance(values, Mapping) or set(values) != set(required_names):
        raise ModelProviderConfigurationError("Provider settings are invalid.")
    if any(not isinstance(values[name], str) for name in required_names):
        raise ModelProviderConfigurationError("Provider settings are invalid.")

    if provider_type is ProviderType.OPENAI:
        return OpenAISettings()
    if provider_type is ProviderType.ANTHROPIC:
        return AnthropicSettings()
    if provider_type is ProviderType.AZURE_OPENAI:
        endpoint = cast(str, values["endpoint"])
        api_version = cast(str, values["api_version"])
        return AzureOpenAISettings(endpoint=endpoint, api_version=api_version)
    if provider_type is ProviderType.GEMINI:
        return GeminiSettings()
    if provider_type is ProviderType.OPENAI_COMPATIBLE:
        base_url = cast(str, values["base_url"])
        return OpenAICompatibleSettings(base_url=base_url)
    assert_never(provider_type)


def provider_settings_to_mapping(settings: ProviderSettings) -> dict[str, str]:
    """Return the canonical plain mapping for validated provider settings."""

    if isinstance(settings, OpenAISettings):
        return {}
    if isinstance(settings, AnthropicSettings):
        return {}
    if isinstance(settings, AzureOpenAISettings):
        return {"endpoint": settings.endpoint, "api_version": settings.api_version}
    if isinstance(settings, GeminiSettings):
        return {}
    if isinstance(settings, OpenAICompatibleSettings):
        return {"base_url": settings.base_url}
    assert_never(settings)


def provider_endpoint_url(settings: ProviderSettings) -> str | None:
    """Return the configured outbound endpoint when the provider owns one."""

    if isinstance(settings, AzureOpenAISettings):
        return settings.endpoint
    if isinstance(settings, OpenAICompatibleSettings):
        return settings.base_url
    if isinstance(settings, (OpenAISettings, AnthropicSettings, GeminiSettings)):
        return None
    assert_never(settings)


__all__ = [
    "provider_endpoint_url",
    "provider_required_setting_names",
    "provider_settings_from_mapping",
    "provider_settings_to_mapping",
]
