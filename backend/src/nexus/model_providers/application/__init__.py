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
from nexus.model_providers.application.list_selectable_chat_models import (
    ListSelectableChatModels,
    SelectableChatModel,
    SelectableChatModels,
)
from nexus.model_providers.application.resolve_chat_model import (
    ResolveChatModel,
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
from nexus.model_providers.domain import ResolvedChatModel

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
    "ListSelectableChatModels",
    "ProviderCatalogItem",
    "ProviderDiscoveryPolicy",
    "ProviderValidationPolicy",
    "RegisterConfiguredModels",
    "ResolveChatModel",
    "ResolvedChatModel",
    "SelectableChatModel",
    "SelectableChatModels",
    "SetConfiguredModelEnabled",
    "SetDefaultModel",
    "SetModelProviderCredential",
    "SetModelProviderEnabled",
    "UpdateModelProvider",
    "ValidateModelProvider",
]
