from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from nexus.model_providers.domain import (
    AnthropicSettings,
    AzureOpenAISettings,
    ConfiguredModel,
    ConfiguredModelId,
    ConfiguredProvider,
    CredentialReference,
    DefaultModelSelection,
    GeminiSettings,
    ModelCapability,
    ModelProviderConfiguration,
    ModelType,
    OpenAICompatibleSettings,
    OpenAISettings,
    OrganizationProviderId,
    ProviderType,
)


def _provider(
    *,
    organization_id=None,
    provider_id=None,
    provider_type: ProviderType = ProviderType.OPENAI,
    settings=None,
    enabled: bool = True,
) -> ConfiguredProvider:
    organization_id = organization_id or uuid4()
    provider_id = provider_id or OrganizationProviderId(uuid4())
    if settings is None:
        settings = {
            ProviderType.OPENAI: OpenAISettings(),
            ProviderType.ANTHROPIC: AnthropicSettings(),
            ProviderType.AZURE_OPENAI: AzureOpenAISettings(
                endpoint="https://example.openai.azure.com",
                api_version="2026-01-01",
            ),
            ProviderType.GEMINI: GeminiSettings(),
            ProviderType.OPENAI_COMPATIBLE: OpenAICompatibleSettings(
                base_url="https://llm.example.com/v1",
            ),
        }[provider_type]
    return ConfiguredProvider(
        organization_public_id=organization_id,
        provider_id=provider_id,
        provider_type=provider_type,
        display_name="Primary provider",
        settings=settings,
        enabled=enabled,
    )


def _model(
    *,
    organization_id,
    provider_id,
    model_type: ModelType = ModelType.CHAT,
    enabled: bool = True,
    capabilities=frozenset({ModelCapability.STREAMING}),
    embedding_dimension: int | None = None,
) -> ConfiguredModel:
    if model_type is ModelType.EMBEDDING:
        capabilities = frozenset()
        embedding_dimension = embedding_dimension or 1536
    elif model_type is ModelType.RERANKER:
        capabilities = frozenset()
        embedding_dimension = None
    return ConfiguredModel(
        organization_public_id=organization_id,
        model_id=ConfiguredModelId(uuid4()),
        provider_id=provider_id,
        provider_model_name="provider-model",
        display_name="Model",
        model_type=model_type,
        capabilities=capabilities,
        embedding_dimension=embedding_dimension,
        enabled=enabled,
    )


def test_provider_types_cover_v1_and_define_gemini_as_ai_studio() -> None:
    assert [provider.value for provider in ProviderType] == [
        "openai",
        "anthropic",
        "azure_openai",
        "gemini",
        "openai_compatible",
    ]
    assert "Google AI Studio" in ProviderType.__doc__
    assert "Vertex AI" in ProviderType.__doc__


def test_model_types_cover_chat_embedding_and_reranker() -> None:
    assert [model_type.value for model_type in ModelType] == [
        "chat",
        "embedding",
        "reranker",
    ]


@pytest.mark.parametrize(
    ("provider_type", "settings"),
    [
        (ProviderType.OPENAI, OpenAISettings()),
        (ProviderType.ANTHROPIC, AnthropicSettings()),
        (
            ProviderType.AZURE_OPENAI,
            AzureOpenAISettings(
                endpoint="https://example.openai.azure.com",
                api_version="2026-01-01",
            ),
        ),
        (ProviderType.GEMINI, GeminiSettings()),
        (
            ProviderType.OPENAI_COMPATIBLE,
            OpenAICompatibleSettings(base_url="https://llm.example.com/v1"),
        ),
    ],
)
def test_valid_configured_provider_for_each_provider_type(
    provider_type: ProviderType,
    settings: object,
) -> None:
    provider = _provider(provider_type=provider_type, settings=settings)

    assert provider.provider_type is provider_type
    assert provider.enabled is True


def test_multiple_providers_of_same_type_have_distinct_configured_identities() -> None:
    organization_id = uuid4()
    first = _provider(organization_id=organization_id)
    second = _provider(organization_id=organization_id)

    configuration = ModelProviderConfiguration(
        organization_public_id=organization_id,
        providers=(first, second),
    )

    assert first.provider_id != second.provider_id
    assert len(configuration.providers) == 2


def test_azure_deployment_name_is_model_level_provider_model_name() -> None:
    organization_id = uuid4()
    provider = _provider(
        organization_id=organization_id,
        provider_type=ProviderType.AZURE_OPENAI,
    )
    model = ConfiguredModel(
        organization_public_id=organization_id,
        model_id=ConfiguredModelId(uuid4()),
        provider_id=provider.provider_id,
        provider_model_name="chat-production-deployment",
        display_name="GPT production",
        model_type=ModelType.CHAT,
        capabilities={ModelCapability.STREAMING},
    )

    assert provider.settings == AzureOpenAISettings(
        endpoint="https://example.openai.azure.com",
        api_version="2026-01-01",
    )
    assert model.provider_model_name == "chat-production-deployment"


@pytest.mark.parametrize(
    "model_type",
    [ModelType.CHAT, ModelType.EMBEDDING, ModelType.RERANKER],
)
def test_valid_model_construction_for_each_model_type(model_type: ModelType) -> None:
    organization_id = uuid4()
    provider = _provider(organization_id=organization_id)
    model = _model(
        organization_id=organization_id,
        provider_id=provider.provider_id,
        model_type=model_type,
    )

    assert model.model_type is model_type


def test_credential_reference_never_exposes_locator_in_repr_or_str() -> None:
    reference = CredentialReference("kv://org/provider/credential")

    assert "kv://org/provider/credential" not in repr(reference)
    assert "kv://org/provider/credential" not in str(reference)
    assert repr(reference) == "CredentialReference(<redacted>)"
    assert str(reference) == "<redacted>"


def test_contracts_are_immutable() -> None:
    provider = _provider()

    with pytest.raises(FrozenInstanceError):
        provider.display_name = "Changed"  # type: ignore[misc]


def test_configuration_defensively_freezes_sequences() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id=organization_id)
    providers = [provider]

    configuration = ModelProviderConfiguration(
        organization_public_id=organization_id,
        providers=providers,
    )
    providers.clear()

    assert configuration.providers == (provider,)


def test_valid_defaults_reference_configured_model_ids() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id=organization_id)
    chat = _model(
        organization_id=organization_id,
        provider_id=provider.provider_id,
        model_type=ModelType.CHAT,
    )
    embedding = _model(
        organization_id=organization_id,
        provider_id=provider.provider_id,
        model_type=ModelType.EMBEDDING,
    )
    reranker = _model(
        organization_id=organization_id,
        provider_id=provider.provider_id,
        model_type=ModelType.RERANKER,
    )

    configuration = ModelProviderConfiguration(
        organization_public_id=organization_id,
        providers=(provider,),
        models=(chat, embedding, reranker),
        defaults=DefaultModelSelection(
            chat=chat.model_id,
            embedding=embedding.model_id,
            reranker=reranker.model_id,
        ),
    )

    assert configuration.defaults.chat == chat.model_id
    assert configuration.defaults.embedding == embedding.model_id
    assert configuration.defaults.reranker == reranker.model_id
