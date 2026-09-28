"""Public provider/model domain contracts."""

from nexus.model_providers.domain.contracts import (
    AnthropicSettings,
    AzureOpenAISettings,
    ConfiguredModel,
    ConfiguredModelId,
    ConfiguredProvider,
    CredentialReference,
    DefaultModelSelection,
    GeminiSettings,
    ModelCapability,
    ModelType,
    OpenAICompatibleSettings,
    OpenAISettings,
    OrganizationModelProviderConfiguration,
    OrganizationProviderId,
    ProviderSettings,
    ProviderType,
)
from nexus.model_providers.domain.credential import (
    MAX_PROVIDER_CREDENTIAL_SECRET_BYTES,
    ProviderCredentialSecret,
)
from nexus.model_providers.domain.errors import ModelProviderConfigurationError

__all__ = [
    "MAX_PROVIDER_CREDENTIAL_SECRET_BYTES",
    "AnthropicSettings",
    "AzureOpenAISettings",
    "ConfiguredModel",
    "ConfiguredModelId",
    "ConfiguredProvider",
    "CredentialReference",
    "DefaultModelSelection",
    "GeminiSettings",
    "ModelCapability",
    "ModelProviderConfigurationError",
    "ModelType",
    "OpenAICompatibleSettings",
    "OpenAISettings",
    "OrganizationModelProviderConfiguration",
    "OrganizationProviderId",
    "ProviderCredentialSecret",
    "ProviderSettings",
    "ProviderType",
]
