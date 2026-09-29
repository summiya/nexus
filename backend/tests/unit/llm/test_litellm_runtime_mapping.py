from __future__ import annotations

from uuid import uuid4

import pytest

from nexus.llm.domain import LLMInvalidRequestError
from nexus.llm.infrastructure.adapters.litellm.runtime_mapping import (
    RuntimeClientKind,
    map_runtime_target,
)
from nexus.model_providers.domain import (
    AnthropicSettings,
    AzureOpenAISettings,
    ConfiguredModelId,
    GeminiSettings,
    OpenAICompatibleSettings,
    OpenAISettings,
    OrganizationProviderId,
    ProviderCredentialSecret,
    ProviderSettings,
    ProviderType,
    ResolvedChatModel,
)


def target(
    provider_type: ProviderType,
    settings: ProviderSettings,
    *,
    model: str = "authoritative-model",
) -> ResolvedChatModel:
    return ResolvedChatModel(
        model_id=ConfiguredModelId(uuid4()),
        provider_id=OrganizationProviderId(uuid4()),
        provider_type=provider_type,
        provider_model_name=model,
        settings=settings,
        credential=ProviderCredentialSecret("secret"),
    )


@pytest.mark.parametrize(
    ("resolved", "provider", "endpoint", "kind", "extra"),
    [
        (
            target(ProviderType.OPENAI, OpenAISettings()),
            "openai",
            "https://api.openai.com/v1",
            RuntimeClientKind.OPENAI,
            {},
        ),
        (
            target(ProviderType.ANTHROPIC, AnthropicSettings()),
            "anthropic",
            "https://api.anthropic.com",
            RuntimeClientKind.HTTP_HANDLER,
            {"api_base": "https://api.anthropic.com", "rust": False},
        ),
        (
            target(
                ProviderType.AZURE_OPENAI,
                AzureOpenAISettings(
                    endpoint="https://azure.example/custom",
                    api_version="2026-09-01",
                ),
                model="deployment-name",
            ),
            "azure",
            "https://azure.example/custom",
            RuntimeClientKind.AZURE_OPENAI,
            {
                "api_base": "https://azure.example/custom",
                "api_version": "2026-09-01",
            },
        ),
        (
            target(ProviderType.GEMINI, GeminiSettings()),
            "gemini",
            "https://generativelanguage.googleapis.com",
            RuntimeClientKind.HTTP_HANDLER,
            {"api_base": "https://generativelanguage.googleapis.com"},
        ),
        (
            target(
                ProviderType.OPENAI_COMPATIBLE,
                OpenAICompatibleSettings(
                    base_url="https://compatible.example/custom/v1"
                ),
                model="operator-alias",
            ),
            "openai",
            "https://compatible.example/custom/v1",
            RuntimeClientKind.OPENAI,
            {"api_base": "https://compatible.example/custom/v1"},
        ),
    ],
)
def test_provider_mapping_is_explicit_and_preserves_target_identity(
    resolved: ResolvedChatModel,
    provider: str,
    endpoint: str,
    kind: RuntimeClientKind,
    extra: dict[str, object],
) -> None:
    mapping = map_runtime_target(resolved)

    assert mapping.model == resolved.provider_model_name
    assert mapping.custom_llm_provider == provider
    assert mapping.endpoint == endpoint
    assert mapping.client_kind is kind
    assert mapping.invocation_arguments() == {
        "model": resolved.provider_model_name,
        "custom_llm_provider": provider,
        **extra,
    }


def test_mismatched_provider_settings_fail_safely() -> None:
    resolved = target(ProviderType.OPENAI, GeminiSettings())

    with pytest.raises(LLMInvalidRequestError) as captured:
        map_runtime_target(resolved)

    assert str(captured.value) == "LLM runtime target is invalid."
    assert "Gemini" not in str(captured.value)
