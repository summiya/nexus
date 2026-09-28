"""FastAPI dependencies for model-provider application services."""

from typing import Annotated

from fastapi import Depends

from nexus.api.dependencies import AppContainerDep
from nexus.model_providers.application import (
    ListProviderCatalog,
    ManageModelProviders,
    ReadModelProviders,
)


def get_provider_catalog(container: AppContainerDep) -> ListProviderCatalog:
    return container.model_providers.catalog


def get_provider_reader(container: AppContainerDep) -> ReadModelProviders:
    return container.model_providers.read


def get_provider_manager(container: AppContainerDep) -> ManageModelProviders:
    return container.model_providers.manage


ProviderCatalogDep = Annotated[ListProviderCatalog, Depends(get_provider_catalog)]
ProviderReaderDep = Annotated[ReadModelProviders, Depends(get_provider_reader)]
ProviderManagerDep = Annotated[ManageModelProviders, Depends(get_provider_manager)]


__all__ = ["ProviderCatalogDep", "ProviderManagerDep", "ProviderReaderDep"]
