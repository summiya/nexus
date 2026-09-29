"""Model-provider application services."""

from nexus.model_providers.application.catalog import (
    ListProviderCatalog,
    ProviderCatalogItem,
)
from nexus.model_providers.application.configured_models import (
    ConfiguredModelItem,
    DeleteConfiguredModel,
    ListConfiguredModels,
    RegisterConfiguredModels,
    SetConfiguredModelEnabled,
)
from nexus.model_providers.application.create_provider import CreateModelProvider
from nexus.model_providers.application.default_models import (
    ClearDefaultModel,
    GetDefaultModels,
    SetDefaultModel,
)
from nexus.model_providers.application.delete_provider import DeleteModelProvider
from nexus.model_providers.application.discover_provider_models import (
    DiscoverProviderModels,
    ProviderDiscoveryPolicy,
)
from nexus.model_providers.application.get_provider import GetModelProvider
from nexus.model_providers.application.list_providers import ListModelProviders
from nexus.model_providers.application.resolve_chat_model import (
    ResolveChatModel,
    ResolvedChatModel,
)
from nexus.model_providers.application.set_provider_credential import (
    SetModelProviderCredential,
)
from nexus.model_providers.application.set_provider_enabled import (
    SetModelProviderEnabled,
)
from nexus.model_providers.application.update_provider import UpdateModelProvider
from nexus.model_providers.application.validate_provider import (
    ProviderValidationPolicy,
    ValidateModelProvider,
)

__all__ = [
    "ClearDefaultModel",
    "ConfiguredModelItem",
    "CreateModelProvider",
    "DeleteConfiguredModel",
    "DeleteModelProvider",
    "DiscoverProviderModels",
    "GetDefaultModels",
    "GetModelProvider",
    "ListConfiguredModels",
    "ListModelProviders",
    "ListProviderCatalog",
    "ProviderCatalogItem",
    "ProviderDiscoveryPolicy",
    "ProviderValidationPolicy",
    "RegisterConfiguredModels",
    "ResolveChatModel",
    "ResolvedChatModel",
    "SetConfiguredModelEnabled",
    "SetDefaultModel",
    "SetModelProviderCredential",
    "SetModelProviderEnabled",
    "UpdateModelProvider",
    "ValidateModelProvider",
]
