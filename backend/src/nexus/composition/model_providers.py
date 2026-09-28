"""Model-provider application composition."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.infrastructure.persistence.authorization import SqlAlchemyPermissionChecker
from nexus.infrastructure.persistence.model_provider import (
    SqlAlchemyModelProviderPersistence,
)
from nexus.model_providers.application import (
    CreateModelProvider,
    DeleteModelProvider,
    GetModelProvider,
    ListModelProviders,
    ListProviderCatalog,
    SetModelProviderCredential,
    SetModelProviderEnabled,
    UpdateModelProvider,
)
from nexus.model_providers.ports import CredentialStore


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


def build_model_provider_composition(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    credential_store: CredentialStore | None,
) -> ModelProviderComposition:
    persistence = SqlAlchemyModelProviderPersistence(session_factory)
    permission_checker = SqlAlchemyPermissionChecker(session_factory)
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
    )


__all__ = ["ModelProviderComposition", "build_model_provider_composition"]
