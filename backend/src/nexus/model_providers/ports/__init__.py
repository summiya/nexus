"""Application-facing model-provider ports."""

from nexus.model_providers.ports.credential_naming import credential_storage_name
from nexus.model_providers.ports.credentials import (
    CredentialNotFoundError,
    CredentialStore,
    CredentialStoreConflictError,
    CredentialStoreError,
)
from nexus.model_providers.ports.discovery import (
    ProviderModelCatalog,
    ProviderModelCatalogError,
    ProviderModelDiscoveryAuthenticationError,
    ProviderModelDiscoveryRejectedError,
    ProviderModelDiscoveryUnavailableError,
    ProviderModelDiscoveryUnsupportedError,
)
from nexus.model_providers.ports.persistence import (
    ConfiguredModelUpdateResult,
    ModelProviderConflictError,
    ModelProviderDeleteRestrictedError,
    ModelProviderPersistence,
    ModelProviderPersistenceError,
    ModelProviderReferenceError,
    ProviderUpdateResult,
)
from nexus.model_providers.ports.validation import ProviderConfigurationValidator

__all__ = [
    "ConfiguredModelUpdateResult",
    "CredentialNotFoundError",
    "CredentialStore",
    "CredentialStoreConflictError",
    "CredentialStoreError",
    "ModelProviderConflictError",
    "ModelProviderDeleteRestrictedError",
    "ModelProviderPersistence",
    "ModelProviderPersistenceError",
    "ModelProviderReferenceError",
    "ProviderConfigurationValidator",
    "ProviderModelCatalog",
    "ProviderModelCatalogError",
    "ProviderModelDiscoveryAuthenticationError",
    "ProviderModelDiscoveryRejectedError",
    "ProviderModelDiscoveryUnavailableError",
    "ProviderModelDiscoveryUnsupportedError",
    "ProviderUpdateResult",
    "credential_storage_name",
]
