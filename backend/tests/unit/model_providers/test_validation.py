from __future__ import annotations

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
    ModelProviderConfigurationError,
    ModelType,
    OpenAICompatibleSettings,
    OpenAISettings,
    OrganizationModelProviderConfiguration,
    OrganizationProviderId,
    ProviderType,
)
from nexus.model_providers.domain.validation import (
    MAX_DISPLAY_NAME_LENGTH,
    MAX_PROVIDER_MODEL_NAME_LENGTH,
    MAX_URL_LENGTH,
    require_bounded_text,
)


def test_configuration_error_is_a_value_error() -> None:
    assert issubclass(ModelProviderConfigurationError, ValueError)


def _provider(
    *,
    organization_id,
    provider_id=None,
    provider_type: ProviderType = ProviderType.OPENAI,
    settings=None,
    enabled: bool = True,
) -> ConfiguredProvider:
    provider_id = provider_id or OrganizationProviderId(uuid4())
    if settings is None:
        settings = OpenAISettings()
    return ConfiguredProvider(
        organization_public_id=organization_id,
        provider_id=provider_id,
        provider_type=provider_type,
        display_name="Provider",
        settings=settings,
        enabled=enabled,
    )


def _chat_model(
    *,
    organization_id,
    provider_id,
    enabled: bool = True,
    streaming: bool = True,
) -> ConfiguredModel:
    capabilities = frozenset({ModelCapability.STREAMING}) if streaming else frozenset()
    return ConfiguredModel(
        organization_public_id=organization_id,
        model_id=ConfiguredModelId(uuid4()),
        provider_id=provider_id,
        provider_model_name="chat-deployment",
        display_name="Chat model",
        model_type=ModelType.CHAT,
        capabilities=capabilities,
        enabled=enabled,
    )


@pytest.mark.parametrize(
    ("provider_type", "settings"),
    [
        (ProviderType.OPENAI, AnthropicSettings()),
        (ProviderType.ANTHROPIC, GeminiSettings()),
        (
            ProviderType.AZURE_OPENAI,
            OpenAICompatibleSettings(base_url="https://example.com"),
        ),
        (ProviderType.GEMINI, OpenAISettings()),
        (
            ProviderType.OPENAI_COMPATIBLE,
            AzureOpenAISettings(
                endpoint="https://example.openai.azure.com",
                api_version="2026-01-01",
            ),
        ),
    ],
)
def test_provider_type_rejects_wrong_settings_type(
    provider_type: ProviderType,
    settings: object,
) -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Provider settings do not match provider type\.$",
    ):
        _provider(
            organization_id=uuid4(),
            provider_type=provider_type,
            settings=settings,
        )


@pytest.mark.parametrize("value", ["", "   "])
def test_azure_requires_endpoint(value: str) -> None:
    with pytest.raises(
        ModelProviderConfigurationError, match=r"^Azure OpenAI endpoint is required\.$"
    ):
        AzureOpenAISettings(endpoint=value, api_version="2026-01-01")


@pytest.mark.parametrize("value", ["", "   "])
def test_azure_requires_api_version(value: str) -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Azure OpenAI API version is required\.$",
    ):
        AzureOpenAISettings(
            endpoint="https://example.openai.azure.com",
            api_version=value,
        )


@pytest.mark.parametrize("value", ["", "   "])
def test_openai_compatible_requires_base_url(value: str) -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^OpenAI-compatible base URL is required\.$",
    ):
        OpenAICompatibleSettings(base_url=value)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "ftp://example.com",
    ],
)
def test_provider_url_requires_https(url: str) -> None:
    with pytest.raises(
        ModelProviderConfigurationError, match=r"^Provider URL must use HTTPS\.$"
    ):
        OpenAICompatibleSettings(base_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "https://",
        "not-a-url",
        "https://exa mple.com",
        "https://example.com:bad",
    ],
)
def test_provider_url_rejects_malformed_values(url: str) -> None:
    with pytest.raises(
        ModelProviderConfigurationError, match=r"^Provider URL is invalid\.$"
    ):
        OpenAICompatibleSettings(base_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "https://user@example.com",
        "https://user:password@example.com",
    ],
)
def test_provider_url_rejects_embedded_credentials(url: str) -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Provider URL must not contain credentials\.$",
    ):
        OpenAICompatibleSettings(base_url=url)


def test_provider_url_rejects_overlong_value() -> None:
    url = "https://example.com/" + ("a" * MAX_URL_LENGTH)

    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^OpenAI-compatible base URL is too long\.$",
    ):
        OpenAICompatibleSettings(base_url=url)


@pytest.mark.parametrize(
    "provider_type",
    [ProviderType.OPENAI, ProviderType.ANTHROPIC, ProviderType.GEMINI],
)
def test_api_key_provider_types_have_no_required_non_secret_settings(
    provider_type: ProviderType,
) -> None:
    settings = {
        ProviderType.OPENAI: OpenAISettings(),
        ProviderType.ANTHROPIC: AnthropicSettings(),
        ProviderType.GEMINI: GeminiSettings(),
    }[provider_type]

    provider = _provider(
        organization_id=uuid4(),
        provider_type=provider_type,
        settings=settings,
    )

    assert provider.settings == settings


@pytest.mark.parametrize("capability", list(ModelCapability))
def test_chat_model_accepts_each_chat_capability(capability: ModelCapability) -> None:
    model = ConfiguredModel(
        organization_public_id=uuid4(),
        model_id=ConfiguredModelId(uuid4()),
        provider_id=OrganizationProviderId(uuid4()),
        provider_model_name="chat-model",
        display_name="Chat model",
        model_type=ModelType.CHAT,
        capabilities={capability},
    )

    assert capability in model.capabilities


@pytest.mark.parametrize("model_type", [ModelType.EMBEDDING, ModelType.RERANKER])
@pytest.mark.parametrize("capability", list(ModelCapability))
def test_non_chat_models_reject_chat_capabilities(
    model_type: ModelType,
    capability: ModelCapability,
) -> None:
    kwargs = {
        "embedding_dimension": 1536 if model_type is ModelType.EMBEDDING else None
    }
    with pytest.raises(
        ModelProviderConfigurationError, match="cannot declare chat capabilities"
    ):
        ConfiguredModel(
            organization_public_id=uuid4(),
            model_id=ConfiguredModelId(uuid4()),
            provider_id=OrganizationProviderId(uuid4()),
            provider_model_name="model",
            display_name="Model",
            model_type=model_type,
            capabilities={capability},
            **kwargs,
        )


@pytest.mark.parametrize("dimension", [None, 0, -1])
def test_embedding_dimension_is_required_and_positive(
    dimension: int | None,
) -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Embedding dimension must be positive\.$",
    ):
        ConfiguredModel(
            organization_public_id=uuid4(),
            model_id=ConfiguredModelId(uuid4()),
            provider_id=OrganizationProviderId(uuid4()),
            provider_model_name="embedding-model",
            display_name="Embedding model",
            model_type=ModelType.EMBEDDING,
            embedding_dimension=dimension,
        )


@pytest.mark.parametrize("dimension", [True, 3.5])
def test_embedding_dimension_rejects_non_integer_values(dimension: object) -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Embedding dimension must be positive\.$",
    ):
        ConfiguredModel(
            organization_public_id=uuid4(),
            model_id=ConfiguredModelId(uuid4()),
            provider_id=OrganizationProviderId(uuid4()),
            provider_model_name="embedding-model",
            display_name="Embedding model",
            model_type=ModelType.EMBEDDING,
            embedding_dimension=dimension,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("target", ["provider", "model"])
def test_enabled_flag_requires_real_bool(target: str) -> None:
    organization_id = uuid4()
    provider_id = OrganizationProviderId(uuid4())

    if target == "provider":
        with pytest.raises(
            ModelProviderConfigurationError,
            match=r"^Provider enabled flag must be a bool\.$",
        ):
            ConfiguredProvider(
                organization_public_id=organization_id,
                provider_id=provider_id,
                provider_type=ProviderType.OPENAI,
                display_name="Provider",
                settings=OpenAISettings(),
                enabled="no",  # type: ignore[arg-type]
            )
        return

    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Model enabled flag must be a bool\.$",
    ):
        ConfiguredModel(
            organization_public_id=organization_id,
            model_id=ConfiguredModelId(uuid4()),
            provider_id=provider_id,
            provider_model_name="chat-model",
            display_name="Chat model",
            model_type=ModelType.CHAT,
            enabled="no",  # type: ignore[arg-type]
        )


def test_require_bounded_text_rejects_non_string_without_attribute_error() -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Display name must be a string\.$",
    ):
        require_bounded_text(
            None,  # type: ignore[arg-type]
            field_name="Display name",
            max_length=10,
        )


def test_chat_model_rejects_embedding_dimension() -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Chat models cannot declare an embedding dimension\.$",
    ):
        ConfiguredModel(
            organization_public_id=uuid4(),
            model_id=ConfiguredModelId(uuid4()),
            provider_id=OrganizationProviderId(uuid4()),
            provider_model_name="chat-model",
            display_name="Chat model",
            model_type=ModelType.CHAT,
            embedding_dimension=1536,
        )


def test_reranker_rejects_embedding_dimension() -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Reranker models cannot declare an embedding dimension\.$",
    ):
        ConfiguredModel(
            organization_public_id=uuid4(),
            model_id=ConfiguredModelId(uuid4()),
            provider_id=OrganizationProviderId(uuid4()),
            provider_model_name="reranker",
            display_name="Reranker",
            model_type=ModelType.RERANKER,
            embedding_dimension=1,
        )


def test_configuration_rejects_cross_organization_provider() -> None:
    provider = _provider(organization_id=uuid4())

    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Provider belongs to a different organization\.$",
    ):
        OrganizationModelProviderConfiguration(
            organization_public_id=uuid4(),
            providers=(provider,),
        )


def test_configuration_rejects_cross_organization_model() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id=organization_id)
    model = _chat_model(
        organization_id=uuid4(),
        provider_id=provider.provider_id,
    )

    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Model belongs to a different organization\.$",
    ):
        OrganizationModelProviderConfiguration(
            organization_public_id=organization_id,
            providers=(provider,),
            models=(model,),
        )


def test_default_must_exist() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id=organization_id)

    with pytest.raises(
        ModelProviderConfigurationError, match=r"^Default model does not exist\.$"
    ):
        OrganizationModelProviderConfiguration(
            organization_public_id=organization_id,
            providers=(provider,),
            defaults=DefaultModelSelection(chat=ConfiguredModelId(uuid4())),
        )


def test_default_must_be_enabled() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id=organization_id)
    model = _chat_model(
        organization_id=organization_id,
        provider_id=provider.provider_id,
        enabled=False,
    )

    with pytest.raises(
        ModelProviderConfigurationError, match=r"^Default model must be enabled\.$"
    ):
        OrganizationModelProviderConfiguration(
            organization_public_id=organization_id,
            providers=(provider,),
            models=(model,),
            defaults=DefaultModelSelection(chat=model.model_id),
        )


def test_default_must_match_selected_type() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id=organization_id)
    embedding = ConfiguredModel(
        organization_public_id=organization_id,
        model_id=ConfiguredModelId(uuid4()),
        provider_id=provider.provider_id,
        provider_model_name="embedding",
        display_name="Embedding",
        model_type=ModelType.EMBEDDING,
        embedding_dimension=1536,
    )

    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Default model type does not match selection\.$",
    ):
        OrganizationModelProviderConfiguration(
            organization_public_id=organization_id,
            providers=(provider,),
            models=(embedding,),
            defaults=DefaultModelSelection(chat=embedding.model_id),
        )


def test_default_provider_must_be_enabled() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id=organization_id, enabled=False)
    model = _chat_model(
        organization_id=organization_id,
        provider_id=provider.provider_id,
    )

    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Default model provider must be enabled\.$",
    ):
        OrganizationModelProviderConfiguration(
            organization_public_id=organization_id,
            providers=(provider,),
            models=(model,),
            defaults=DefaultModelSelection(chat=model.model_id),
        )


def test_default_chat_model_must_support_streaming() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id=organization_id)
    model = _chat_model(
        organization_id=organization_id,
        provider_id=provider.provider_id,
        streaming=False,
    )

    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Default chat model must support streaming\.$",
    ):
        OrganizationModelProviderConfiguration(
            organization_public_id=organization_id,
            providers=(provider,),
            models=(model,),
            defaults=DefaultModelSelection(chat=model.model_id),
        )


def test_model_must_reference_provider_in_same_configuration() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id=organization_id)
    model = _chat_model(
        organization_id=organization_id,
        provider_id=OrganizationProviderId(uuid4()),
    )

    with pytest.raises(
        ModelProviderConfigurationError,
        match=r"^Configured model references an unknown provider\.$",
    ):
        OrganizationModelProviderConfiguration(
            organization_public_id=organization_id,
            providers=(provider,),
            models=(model,),
        )


@pytest.mark.parametrize(
    ("enum_type", "value", "message"),
    [
        (ProviderType, "vertex_ai", "Unknown provider type."),
        (ModelType, "completion", "Unknown model type."),
        (ModelCapability, "audio", "Unknown model capability."),
    ],
)
def test_unknown_enum_values_fail_with_fixed_safe_messages(
    enum_type: type[ProviderType | ModelType | ModelCapability],
    value: str,
    message: str,
) -> None:
    with pytest.raises(ModelProviderConfigurationError) as captured:
        enum_type(value)

    assert str(captured.value) == message


def test_provider_display_name_is_bounded() -> None:
    with pytest.raises(
        ModelProviderConfigurationError, match=r"^Provider display name is too long\.$"
    ):
        ConfiguredProvider(
            organization_public_id=uuid4(),
            provider_id=OrganizationProviderId(uuid4()),
            provider_type=ProviderType.OPENAI,
            display_name="x" * (MAX_DISPLAY_NAME_LENGTH + 1),
            settings=OpenAISettings(),
            enabled=True,
        )


def test_model_display_name_is_bounded() -> None:
    with pytest.raises(
        ModelProviderConfigurationError, match=r"^Model display name is too long\.$"
    ):
        ConfiguredModel(
            organization_public_id=uuid4(),
            model_id=ConfiguredModelId(uuid4()),
            provider_id=OrganizationProviderId(uuid4()),
            provider_model_name="model",
            display_name="x" * (MAX_DISPLAY_NAME_LENGTH + 1),
            model_type=ModelType.CHAT,
        )


def test_provider_model_name_is_bounded() -> None:
    with pytest.raises(
        ModelProviderConfigurationError, match=r"^Provider model name is too long\.$"
    ):
        ConfiguredModel(
            organization_public_id=uuid4(),
            model_id=ConfiguredModelId(uuid4()),
            provider_id=OrganizationProviderId(uuid4()),
            provider_model_name="x" * (MAX_PROVIDER_MODEL_NAME_LENGTH + 1),
            display_name="Model",
            model_type=ModelType.CHAT,
        )


def test_credential_reference_rejects_non_uuid_values() -> None:
    with pytest.raises(
        ModelProviderConfigurationError, match=r"^Credential reference is invalid\.$"
    ):
        CredentialReference("not-a-uuid")  # type: ignore[arg-type]
