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
from nexus.model_providers.domain.provider_settings import (
    provider_endpoint_url,
    provider_required_setting_names,
    provider_settings_from_mapping,
    provider_settings_to_mapping,
)

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
    "provider_endpoint_url",
    "provider_required_setting_names",
    "provider_settings_from_mapping",
    "provider_settings_to_mapping",
]
