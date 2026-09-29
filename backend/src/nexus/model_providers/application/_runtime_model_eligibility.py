"""Shared runtime chat-model eligibility predicates."""

from nexus.model_providers.domain import (
    ConfiguredModel,
    ConfiguredProvider,
    ModelCapability,
    ModelType,
    ProviderValidationStatus,
)


def is_streaming_chat_model(model: ConfiguredModel) -> bool:
    """Return whether a configured model can serve streaming chat requests."""

    return (
        model.enabled
        and model.model_type is ModelType.CHAT
        and ModelCapability.STREAMING in model.capabilities
    )


def is_runtime_provider_eligible(provider: ConfiguredProvider) -> bool:
    """Return whether a provider is currently eligible for runtime use."""

    return (
        provider.enabled
        and provider.validation_status is ProviderValidationStatus.VALID
    )


__all__ = ["is_runtime_provider_eligible", "is_streaming_chat_model"]
