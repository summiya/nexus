"""Immutable organization-scoped provider/model contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeAlias
from uuid import UUID

from nexus.model_providers.domain.validation import (
    MAX_API_VERSION_LENGTH,
    MAX_CREDENTIAL_REFERENCE_LENGTH,
    MAX_DISPLAY_NAME_LENGTH,
    MAX_PROVIDER_MODEL_NAME_LENGTH,
    require_bounded_text,
    require_https_url,
)


class ProviderType(StrEnum):
    """Provider families supported by the V1 BYOK foundation.

    GEMINI means the Google AI Studio API-key provider. Vertex AI is a
    different provider shape and is intentionally outside the V1 contract.
    """

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE_OPENAI = "azure_openai"
    GEMINI = "gemini"
    OPENAI_COMPATIBLE = "openai_compatible"

    @classmethod
    def _missing_(cls, value: object) -> ProviderType:
        raise ValueError("Unknown provider type.")


class ModelType(StrEnum):
    CHAT = "chat"
    EMBEDDING = "embedding"
    RERANKER = "reranker"

    @classmethod
    def _missing_(cls, value: object) -> ModelType:
        raise ValueError("Unknown model type.")


class ModelCapability(StrEnum):
    STREAMING = "streaming"
    TOOLS = "tools"
    VISION = "vision"
    STRUCTURED_OUTPUT = "structured_output"

    @classmethod
    def _missing_(cls, value: object) -> ModelCapability:
        raise ValueError("Unknown model capability.")


@dataclass(frozen=True)
class OrganizationProviderId:
    value: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.value, UUID):
            raise ValueError("Configured provider identifier is invalid.")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class ConfiguredModelId:
    value: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.value, UUID):
            raise ValueError("Configured model identifier is invalid.")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class CredentialReference:
    """Opaque locator only; never credential material."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "value",
            require_bounded_text(
                self.value,
                field_name="Credential reference",
                max_length=MAX_CREDENTIAL_REFERENCE_LENGTH,
            ),
        )

    def __repr__(self) -> str:
        return "CredentialReference(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"


@dataclass(frozen=True)
class OpenAISettings:
    pass


@dataclass(frozen=True)
class AnthropicSettings:
    pass


@dataclass(frozen=True)
class GeminiSettings:
    pass


@dataclass(frozen=True)
class AzureOpenAISettings:
    endpoint: str
    api_version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "endpoint",
            require_https_url(self.endpoint, field_name="Azure OpenAI endpoint"),
        )
        object.__setattr__(
            self,
            "api_version",
            require_bounded_text(
                self.api_version,
                field_name="Azure OpenAI API version",
                max_length=MAX_API_VERSION_LENGTH,
            ),
        )


@dataclass(frozen=True)
class OpenAICompatibleSettings:
    base_url: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "base_url",
            require_https_url(
                self.base_url,
                field_name="OpenAI-compatible base URL",
            ),
        )


ProviderSettings: TypeAlias = (
    OpenAISettings
    | AnthropicSettings
    | AzureOpenAISettings
    | GeminiSettings
    | OpenAICompatibleSettings
)

_EXPECTED_SETTINGS = {
    ProviderType.OPENAI: OpenAISettings,
    ProviderType.ANTHROPIC: AnthropicSettings,
    ProviderType.AZURE_OPENAI: AzureOpenAISettings,
    ProviderType.GEMINI: GeminiSettings,
    ProviderType.OPENAI_COMPATIBLE: OpenAICompatibleSettings,
}


@dataclass(frozen=True)
class ConfiguredProvider:
    organization_public_id: UUID
    provider_id: OrganizationProviderId
    provider_type: ProviderType
    display_name: str
    settings: ProviderSettings
    enabled: bool
    credential_reference: CredentialReference | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.organization_public_id, UUID):
            raise ValueError("Organization identifier is invalid.")
        if not isinstance(self.provider_type, ProviderType):
            raise ValueError("Unknown provider type.")
        object.__setattr__(
            self,
            "display_name",
            require_bounded_text(
                self.display_name,
                field_name="Provider display name",
                max_length=MAX_DISPLAY_NAME_LENGTH,
            ),
        )
        expected = _EXPECTED_SETTINGS[self.provider_type]
        if not isinstance(self.settings, expected):
            raise ValueError("Provider settings do not match provider type.")


@dataclass(frozen=True)
class ConfiguredModel:
    """One organization-owned model configuration.

    provider_model_name is the provider's invocation identifier. For Azure
    OpenAI it is the deployment name, allowing one configured Azure provider
    to expose multiple chat or embedding deployments.
    """

    organization_public_id: UUID
    model_id: ConfiguredModelId
    provider_id: OrganizationProviderId
    provider_model_name: str
    display_name: str
    model_type: ModelType
    capabilities: frozenset[ModelCapability] = field(default_factory=frozenset)
    embedding_dimension: int | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.organization_public_id, UUID):
            raise ValueError("Organization identifier is invalid.")
        if not isinstance(self.model_type, ModelType):
            raise ValueError("Unknown model type.")
        if any(
            not isinstance(capability, ModelCapability)
            for capability in self.capabilities
        ):
            raise ValueError("Unknown model capability.")
        object.__setattr__(
            self,
            "provider_model_name",
            require_bounded_text(
                self.provider_model_name,
                field_name="Provider model name",
                max_length=MAX_PROVIDER_MODEL_NAME_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "display_name",
            require_bounded_text(
                self.display_name,
                field_name="Model display name",
                max_length=MAX_DISPLAY_NAME_LENGTH,
            ),
        )
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        self._validate_type_contract()

    def _validate_type_contract(self) -> None:
        if self.model_type is ModelType.CHAT:
            if self.embedding_dimension is not None:
                raise ValueError("Chat models cannot declare an embedding dimension.")
            return

        if self.capabilities:
            raise ValueError(
                f"{self.model_type.value.capitalize()} models cannot declare chat capabilities."
            )

        if self.model_type is ModelType.EMBEDDING:
            if self.embedding_dimension is None or self.embedding_dimension <= 0:
                raise ValueError("Embedding dimension must be positive.")
            return

        if self.embedding_dimension is not None:
            raise ValueError("Reranker models cannot declare an embedding dimension.")


@dataclass(frozen=True)
class DefaultModelSelection:
    chat: ConfiguredModelId | None = None
    embedding: ConfiguredModelId | None = None
    reranker: ConfiguredModelId | None = None

    def for_type(self, model_type: ModelType) -> ConfiguredModelId | None:
        if model_type is ModelType.CHAT:
            return self.chat
        if model_type is ModelType.EMBEDDING:
            return self.embedding
        return self.reranker


@dataclass(frozen=True)
class ModelProviderConfiguration:
    """One organization's provider/model configuration and defaults."""

    organization_public_id: UUID
    providers: tuple[ConfiguredProvider, ...] = field(default_factory=tuple)
    models: tuple[ConfiguredModel, ...] = field(default_factory=tuple)
    defaults: DefaultModelSelection = field(default_factory=DefaultModelSelection)

    def __post_init__(self) -> None:
        if not isinstance(self.organization_public_id, UUID):
            raise ValueError("Organization identifier is invalid.")
        object.__setattr__(self, "providers", tuple(self.providers))
        object.__setattr__(self, "models", tuple(self.models))
        self._validate()

    def _validate(self) -> None:
        providers: dict[OrganizationProviderId, ConfiguredProvider] = {}
        for provider in self.providers:
            if provider.organization_public_id != self.organization_public_id:
                raise ValueError("Provider belongs to a different organization.")
            if provider.provider_id in providers:
                raise ValueError("Configured provider identifier must be unique.")
            providers[provider.provider_id] = provider

        models: dict[ConfiguredModelId, ConfiguredModel] = {}
        for model in self.models:
            if model.organization_public_id != self.organization_public_id:
                raise ValueError("Model belongs to a different organization.")
            if model.model_id in models:
                raise ValueError("Configured model identifier must be unique.")
            if model.provider_id not in providers:
                raise ValueError("Configured model references an unknown provider.")
            models[model.model_id] = model

        self._validate_default(
            ModelType.CHAT,
            self.defaults.chat,
            providers=providers,
            models=models,
        )
        self._validate_default(
            ModelType.EMBEDDING,
            self.defaults.embedding,
            providers=providers,
            models=models,
        )
        self._validate_default(
            ModelType.RERANKER,
            self.defaults.reranker,
            providers=providers,
            models=models,
        )

    @staticmethod
    def _validate_default(
        selected_type: ModelType,
        model_id: ConfiguredModelId | None,
        *,
        providers: dict[OrganizationProviderId, ConfiguredProvider],
        models: dict[ConfiguredModelId, ConfiguredModel],
    ) -> None:
        if model_id is None:
            return

        model = models.get(model_id)
        if model is None:
            raise ValueError("Default model does not exist.")
        if not model.enabled:
            raise ValueError("Default model must be enabled.")
        if model.model_type is not selected_type:
            raise ValueError("Default model type does not match selection.")

        provider = providers[model.provider_id]
        if not provider.enabled:
            raise ValueError("Default model provider must be enabled.")

        if (
            selected_type is ModelType.CHAT
            and ModelCapability.STREAMING not in model.capabilities
        ):
            raise ValueError("Default chat model must support streaming.")


__all__ = [
    "AnthropicSettings",
    "AzureOpenAISettings",
    "ConfiguredModel",
    "ConfiguredModelId",
    "ConfiguredProvider",
    "CredentialReference",
    "DefaultModelSelection",
    "GeminiSettings",
    "ModelCapability",
    "ModelProviderConfiguration",
    "ModelType",
    "OpenAICompatibleSettings",
    "OpenAISettings",
    "OrganizationProviderId",
    "ProviderSettings",
    "ProviderType",
]
