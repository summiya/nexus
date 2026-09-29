"""Model-provider application composition."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.config.settings import Settings
from nexus.infrastructure.model_providers import (
    HttpProviderConfigurationValidator,
    HttpProviderModelCatalog,
)
from nexus.infrastructure.persistence.authorization import SqlAlchemyPermissionChecker
from nexus.infrastructure.persistence.model_provider import (
    SqlAlchemyModelProviderPersistence,
)
from nexus.model_providers.application import (
    ClearDefaultModel,
    CreateModelProvider,
    DeleteConfiguredModel,
    DeleteModelProvider,
    DiscoverProviderModels,
    GetDefaultModels,
    GetModelProvider,
    ListConfiguredModels,
    ListModelProviders,
    ListProviderCatalog,
    ProviderDiscoveryPolicy,
    ProviderValidationPolicy,
    RegisterConfiguredModels,
    SetConfiguredModelEnabled,
    SetDefaultModel,
    SetModelProviderCredential,
    SetModelProviderEnabled,
    UpdateModelProvider,
    ValidateModelProvider,
)
from nexus.model_providers.application._provider_model_discovery import (
    ProviderModelDiscovery,
)
from nexus.model_providers.ports import (
    CredentialStore,
    ProviderConfigurationValidator,
    ProviderModelCatalog,
)
from nexus.ports.rate_limit import RateLimiter


@dataclass(frozen=True)
class ModelProviderComposition:
    catalog: ListProviderCatalog
    list_providers: ListModelProviders
    get_provider: GetModelProvider
    create_provider: CreateModelProvider
    update_provider: UpdateModelProvider
    set_provider_enabled: SetModelProviderEnabled
    set_provider_credential: SetModelProviderCredential
    delete_provider: DeleteModelProvider
    validate_provider: ValidateModelProvider
    discover_models: DiscoverProviderModels
    list_models: ListConfiguredModels
    register_models: RegisterConfiguredModels
    set_model_enabled: SetConfiguredModelEnabled
    delete_model: DeleteConfiguredModel
    get_defaults: GetDefaultModels
    set_default: SetDefaultModel
    clear_default: ClearDefaultModel


def build_model_provider_composition(
    *,
    app_settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    credential_store: CredentialStore | None,
    rate_limiter: RateLimiter,
    validator: ProviderConfigurationValidator | None = None,
    model_catalog: ProviderModelCatalog | None = None,
) -> ModelProviderComposition:
    persistence = SqlAlchemyModelProviderPersistence(session_factory)
    permission_checker = SqlAlchemyPermissionChecker(session_factory)
    discovery = ProviderModelDiscovery(
        persistence=persistence,
        credential_store=credential_store,
        catalog=(
            model_catalog
            if model_catalog is not None
            else HttpProviderModelCatalog(
                timeout_seconds=app_settings.model_provider_discovery_timeout_seconds
            )
        ),
        rate_limiter=rate_limiter,
        policy=ProviderDiscoveryPolicy(
            provider_max_requests=(
                app_settings.model_provider_discovery_rate_limit_max_requests
            ),
            provider_window_seconds=(
                app_settings.model_provider_discovery_rate_limit_window_seconds
            ),
            organization_max_requests=(
                app_settings.model_provider_discovery_organization_rate_limit_max_requests
            ),
            organization_window_seconds=(
                app_settings.model_provider_discovery_organization_rate_limit_window_seconds
            ),
        ),
    )
    return ModelProviderComposition(
        catalog=ListProviderCatalog(permission_checker=permission_checker),
        list_providers=ListModelProviders(
            persistence=persistence,
            permission_checker=permission_checker,
        ),
        get_provider=GetModelProvider(
            persistence=persistence,
            permission_checker=permission_checker,
        ),
        create_provider=CreateModelProvider(
            persistence=persistence,
            permission_checker=permission_checker,
        ),
        update_provider=UpdateModelProvider(
            persistence=persistence,
            permission_checker=permission_checker,
            credential_store=credential_store,
        ),
        set_provider_enabled=SetModelProviderEnabled(
            persistence=persistence,
            permission_checker=permission_checker,
        ),
        set_provider_credential=SetModelProviderCredential(
            persistence=persistence,
            permission_checker=permission_checker,
            credential_store=credential_store,
        ),
        delete_provider=DeleteModelProvider(
            persistence=persistence,
            permission_checker=permission_checker,
            credential_store=credential_store,
        ),
        validate_provider=ValidateModelProvider(
            persistence=persistence,
            permission_checker=permission_checker,
            credential_store=credential_store,
            validator=(
                validator
                if validator is not None
                else HttpProviderConfigurationValidator(
                    timeout_seconds=(
                        app_settings.model_provider_validation_timeout_seconds
                    )
                )
            ),
            rate_limiter=rate_limiter,
            policy=ProviderValidationPolicy(
                provider_max_requests=(
                    app_settings.model_provider_validation_rate_limit_max_requests
                ),
                provider_window_seconds=(
                    app_settings.model_provider_validation_rate_limit_window_seconds
                ),
                organization_max_requests=(
                    app_settings.model_provider_validation_organization_rate_limit_max_requests
                ),
                organization_window_seconds=(
                    app_settings.model_provider_validation_organization_rate_limit_window_seconds
                ),
            ),
        ),
        discover_models=DiscoverProviderModels(
            permission_checker=permission_checker,
            discovery=discovery,
        ),
        list_models=ListConfiguredModels(
            persistence=persistence,
            permission_checker=permission_checker,
        ),
        register_models=RegisterConfiguredModels(
            persistence=persistence,
            permission_checker=permission_checker,
            discovery=discovery,
        ),
        set_model_enabled=SetConfiguredModelEnabled(
            persistence=persistence,
            permission_checker=permission_checker,
        ),
        delete_model=DeleteConfiguredModel(
            persistence=persistence,
            permission_checker=permission_checker,
        ),
        get_defaults=GetDefaultModels(
            persistence=persistence,
            permission_checker=permission_checker,
        ),
        set_default=SetDefaultModel(
            persistence=persistence,
            permission_checker=permission_checker,
        ),
        clear_default=ClearDefaultModel(
            persistence=persistence,
            permission_checker=permission_checker,
        ),
    )


__all__ = ["ModelProviderComposition", "build_model_provider_composition"]
