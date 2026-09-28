"""Model-provider application composition."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.infrastructure.persistence.authorization import SqlAlchemyPermissionChecker
from nexus.infrastructure.persistence.model_provider import (
    SqlAlchemyModelProviderPersistence,
)
from nexus.model_providers.application import (
    ListProviderCatalog,
    ManageModelProviders,
    ReadModelProviders,
)
from nexus.model_providers.ports import CredentialStore


@dataclass(frozen=True)
class ModelProviderComposition:
    catalog: ListProviderCatalog
    read: ReadModelProviders
    manage: ManageModelProviders


def build_model_provider_composition(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    credential_store: CredentialStore | None,
) -> ModelProviderComposition:
    persistence = SqlAlchemyModelProviderPersistence(session_factory)
    permission_checker = SqlAlchemyPermissionChecker(session_factory)
    return ModelProviderComposition(
        catalog=ListProviderCatalog(permission_checker=permission_checker),
        read=ReadModelProviders(
            persistence=persistence,
            permission_checker=permission_checker,
        ),
        manage=ManageModelProviders(
            persistence=persistence,
            permission_checker=permission_checker,
            credential_store=credential_store,
        ),
    )


__all__ = ["ModelProviderComposition", "build_model_provider_composition"]
