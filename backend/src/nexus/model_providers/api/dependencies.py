"""FastAPI dependencies for model-provider application services."""

from typing import Annotated

from fastapi import Depends

from nexus.api.dependencies import AppContainerDep
from nexus.model_providers.application import (
    CreateModelProvider,
    DeleteConfiguredModel,
    DeleteModelProvider,
    DiscoverProviderModels,
    GetModelProvider,
    ListConfiguredModels,
    ListModelProviders,
    ListProviderCatalog,
    RegisterConfiguredModels,
    SetConfiguredModelEnabled,
    SetModelProviderCredential,
    SetModelProviderEnabled,
    UpdateModelProvider,
    ValidateModelProvider,
)


def get_provider_catalog(container: AppContainerDep) -> ListProviderCatalog:
    return container.model_providers.catalog


def get_provider_list(container: AppContainerDep) -> ListModelProviders:
    return container.model_providers.list_providers


def get_provider(container: AppContainerDep) -> GetModelProvider:
    return container.model_providers.get_provider


def get_provider_creator(container: AppContainerDep) -> CreateModelProvider:
    return container.model_providers.create_provider


def get_provider_updater(container: AppContainerDep) -> UpdateModelProvider:
    return container.model_providers.update_provider


def get_provider_enabled_setter(container: AppContainerDep) -> SetModelProviderEnabled:
    return container.model_providers.set_provider_enabled


def get_provider_credential_setter(
    container: AppContainerDep,
) -> SetModelProviderCredential:
    return container.model_providers.set_provider_credential


def get_provider_deleter(container: AppContainerDep) -> DeleteModelProvider:
    return container.model_providers.delete_provider


def get_provider_validator(container: AppContainerDep) -> ValidateModelProvider:
    return container.model_providers.validate_provider


def get_provider_model_discovery(
    container: AppContainerDep,
) -> DiscoverProviderModels:
    return container.model_providers.discover_models


def get_configured_model_list(container: AppContainerDep) -> ListConfiguredModels:
    return container.model_providers.list_models


def get_configured_model_registrar(
    container: AppContainerDep,
) -> RegisterConfiguredModels:
    return container.model_providers.register_models


def get_configured_model_enabled_setter(
    container: AppContainerDep,
) -> SetConfiguredModelEnabled:
    return container.model_providers.set_model_enabled


def get_configured_model_deleter(container: AppContainerDep) -> DeleteConfiguredModel:
    return container.model_providers.delete_model


ProviderCatalogDep = Annotated[ListProviderCatalog, Depends(get_provider_catalog)]
ProviderListDep = Annotated[ListModelProviders, Depends(get_provider_list)]
ProviderDep = Annotated[GetModelProvider, Depends(get_provider)]
ProviderCreatorDep = Annotated[CreateModelProvider, Depends(get_provider_creator)]
ProviderUpdaterDep = Annotated[UpdateModelProvider, Depends(get_provider_updater)]
ProviderEnabledSetterDep = Annotated[
    SetModelProviderEnabled, Depends(get_provider_enabled_setter)
]
ProviderCredentialSetterDep = Annotated[
    SetModelProviderCredential, Depends(get_provider_credential_setter)
]
ProviderDeleterDep = Annotated[DeleteModelProvider, Depends(get_provider_deleter)]
ProviderValidatorDep = Annotated[ValidateModelProvider, Depends(get_provider_validator)]
ProviderModelDiscoveryDep = Annotated[
    DiscoverProviderModels, Depends(get_provider_model_discovery)
]
ConfiguredModelListDep = Annotated[
    ListConfiguredModels, Depends(get_configured_model_list)
]
ConfiguredModelRegistrarDep = Annotated[
    RegisterConfiguredModels, Depends(get_configured_model_registrar)
]
ConfiguredModelEnabledSetterDep = Annotated[
    SetConfiguredModelEnabled, Depends(get_configured_model_enabled_setter)
]
ConfiguredModelDeleterDep = Annotated[
    DeleteConfiguredModel, Depends(get_configured_model_deleter)
]


__all__ = [
    "ConfiguredModelDeleterDep",
    "ConfiguredModelEnabledSetterDep",
    "ConfiguredModelListDep",
    "ConfiguredModelRegistrarDep",
    "ProviderCatalogDep",
    "ProviderCreatorDep",
    "ProviderCredentialSetterDep",
    "ProviderDeleterDep",
    "ProviderDep",
    "ProviderEnabledSetterDep",
    "ProviderListDep",
    "ProviderModelDiscoveryDep",
    "ProviderUpdaterDep",
    "ProviderValidatorDep",
]
