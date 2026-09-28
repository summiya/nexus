"""SQLAlchemy model-provider configuration persistence adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import TypeVar
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.infrastructure.persistence import _model_provider_queries as queries
from nexus.model_providers.domain import (
    ConfiguredModel,
    ConfiguredModelId,
    ConfiguredProvider,
    CredentialReference,
    DefaultModelSelection,
    ModelType,
    OrganizationModelProviderConfiguration,
    OrganizationProviderId,
)
from nexus.model_providers.ports import (
    ModelProviderConflictError,
    ModelProviderDeleteRestrictedError,
    ModelProviderPersistence,
    ModelProviderPersistenceError,
    ModelProviderReferenceError,
)

T = TypeVar("T")

_CONFLICT_CONSTRAINTS = frozenset(
    {
        "uq_model_providers_public_id",
        "uq_model_providers_organization_id_display_name",
        "uq_model_providers_credential_reference_not_null",
        "uq_configured_models_public_id",
        "uq_configured_models_provider_model_identity",
    }
)
_REFERENCE_CONSTRAINTS = frozenset(
    {
        "fk_model_providers_organization_id_organizations",
        "fk_configured_models_organization_provider",
        "fk_organization_model_defaults_organization",
        "fk_organization_model_defaults_tenant_model",
    }
)


class SqlAlchemyModelProviderPersistence(ModelProviderPersistence):
    """Persist complete tenant-safe provider/model configurations."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def load_configuration(
        self,
        *,
        organization_public_id: UUID,
    ) -> OrganizationModelProviderConfiguration | None:
        async def load(
            session: AsyncSession,
        ) -> OrganizationModelProviderConfiguration | None:
            organization_id = await queries.organization_id(
                session,
                organization_public_id=organization_public_id,
            )
            if organization_id is None:
                return None
            return await queries.load_configuration(
                session,
                organization_public_id=organization_public_id,
                organization_id=organization_id,
            )

        return await self._run_read(load)

    async def create_provider(self, provider: ConfiguredProvider) -> None:
        async def create(session: AsyncSession) -> None:
            organization_id, current = await self._locked_configuration(
                session,
                provider.organization_public_id,
            )
            OrganizationModelProviderConfiguration(
                organization_public_id=current.organization_public_id,
                providers=(*current.providers, provider),
                models=current.models,
                defaults=current.defaults,
            )
            await queries.insert_provider(
                session,
                organization_id=organization_id,
                provider=provider,
            )

        await self._run_transaction(create)

    async def update_provider(self, provider: ConfiguredProvider) -> None:
        async def update(session: AsyncSession) -> None:
            organization_id, current = await self._locked_configuration(
                session,
                provider.organization_public_id,
            )
            updated = _replace_provider(current, provider)
            OrganizationModelProviderConfiguration(
                organization_public_id=current.organization_public_id,
                providers=updated,
                models=current.models,
                defaults=current.defaults,
            )
            if not await queries.update_provider(
                session,
                organization_id=organization_id,
                provider=provider,
            ):
                raise ModelProviderReferenceError("Configured provider was not found")

        await self._run_transaction(update)

    async def set_provider_credential_reference(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference | None,
    ) -> None:
        async def update(session: AsyncSession) -> None:
            organization_id, current = await self._locked_configuration(
                session,
                organization_public_id,
            )
            existing = _find_provider(current, provider_id)
            provider = replace(existing, credential_reference=credential_reference)
            OrganizationModelProviderConfiguration(
                organization_public_id=current.organization_public_id,
                providers=_replace_provider(current, provider),
                models=current.models,
                defaults=current.defaults,
            )
            if not await queries.update_provider(
                session,
                organization_id=organization_id,
                provider=provider,
            ):
                raise ModelProviderReferenceError("Configured provider was not found")

        await self._run_transaction(update)

    async def delete_provider(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
    ) -> None:
        async def delete(session: AsyncSession) -> None:
            organization_id, current = await self._locked_configuration(
                session,
                organization_public_id,
            )
            _find_provider(current, provider_id)
            OrganizationModelProviderConfiguration(
                organization_public_id=current.organization_public_id,
                providers=tuple(
                    provider
                    for provider in current.providers
                    if provider.provider_id != provider_id
                ),
                models=current.models,
                defaults=current.defaults,
            )
            if not await queries.delete_provider(
                session,
                organization_id=organization_id,
                provider_id=provider_id,
            ):
                raise ModelProviderReferenceError("Configured provider was not found")

        await self._run_transaction(delete, delete_operation=True)

    async def create_model(self, model: ConfiguredModel) -> None:
        async def create(session: AsyncSession) -> None:
            organization_id, current = await self._locked_configuration(
                session,
                model.organization_public_id,
            )
            OrganizationModelProviderConfiguration(
                organization_public_id=current.organization_public_id,
                providers=current.providers,
                models=(*current.models, model),
                defaults=current.defaults,
            )
            if not await queries.insert_model(
                session,
                organization_id=organization_id,
                model=model,
            ):
                raise ModelProviderReferenceError("Configured provider was not found")

        await self._run_transaction(create)

    async def update_model(self, model: ConfiguredModel) -> None:
        async def update(session: AsyncSession) -> None:
            organization_id, current = await self._locked_configuration(
                session,
                model.organization_public_id,
            )
            updated = _replace_model(current, model)
            OrganizationModelProviderConfiguration(
                organization_public_id=current.organization_public_id,
                providers=current.providers,
                models=updated,
                defaults=current.defaults,
            )
            if not await queries.update_model(
                session,
                organization_id=organization_id,
                model=model,
            ):
                raise ModelProviderReferenceError("Configured model was not found")

        await self._run_transaction(update)

    async def delete_model(
        self,
        *,
        organization_public_id: UUID,
        model_id: ConfiguredModelId,
    ) -> None:
        async def delete(session: AsyncSession) -> None:
            organization_id, current = await self._locked_configuration(
                session,
                organization_public_id,
            )
            _find_model(current, model_id)
            OrganizationModelProviderConfiguration(
                organization_public_id=current.organization_public_id,
                providers=current.providers,
                models=tuple(
                    model for model in current.models if model.model_id != model_id
                ),
                defaults=current.defaults,
            )
            if not await queries.delete_model(
                session,
                organization_id=organization_id,
                model_id=model_id,
            ):
                raise ModelProviderReferenceError("Configured model was not found")

        await self._run_transaction(delete, delete_operation=True)

    async def set_default(
        self,
        *,
        organization_public_id: UUID,
        model_type: ModelType,
        model_id: ConfiguredModelId | None,
    ) -> None:
        async def update(session: AsyncSession) -> None:
            organization_id, current = await self._locked_configuration(
                session,
                organization_public_id,
            )
            defaults = _with_default(current.defaults, model_type, model_id)
            OrganizationModelProviderConfiguration(
                organization_public_id=current.organization_public_id,
                providers=current.providers,
                models=current.models,
                defaults=defaults,
            )
            if not await queries.set_default(
                session,
                organization_id=organization_id,
                model_type=model_type,
                model_id=model_id,
            ):
                raise ModelProviderReferenceError("Configured model was not found")

        await self._run_transaction(update)

    async def _locked_configuration(
        self,
        session: AsyncSession,
        organization_public_id: UUID,
    ) -> tuple[int, OrganizationModelProviderConfiguration]:
        organization_id = await queries.lock_organization(
            session,
            organization_public_id=organization_public_id,
        )
        if organization_id is None:
            raise ModelProviderReferenceError("Organization was not found")
        configuration = await queries.load_configuration(
            session,
            organization_public_id=organization_public_id,
            organization_id=organization_id,
        )
        return organization_id, configuration

    async def _run_read(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
    ) -> T:
        try:
            async with self._session_factory() as session:
                return await operation(session)
        except SQLAlchemyError as exc:
            raise ModelProviderPersistenceError(
                "Model provider persistence failed"
            ) from exc

    async def _run_transaction(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
        *,
        delete_operation: bool = False,
    ) -> T:
        transaction = asyncio.create_task(
            self._execute_transaction(
                operation,
                delete_operation=delete_operation,
            )
        )
        try:
            return await asyncio.shield(transaction)
        except asyncio.CancelledError:
            await _settle_cancelled_transaction(transaction)
            raise

    async def _execute_transaction(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
        *,
        delete_operation: bool,
    ) -> T:
        try:
            async with self._session_factory.begin() as session:
                return await operation(session)
        except IntegrityError as exc:
            constraint = _constraint_name(exc)
            if constraint in _CONFLICT_CONSTRAINTS:
                raise ModelProviderConflictError(
                    "Model provider configuration conflicts"
                ) from exc
            if constraint in _REFERENCE_CONSTRAINTS:
                if delete_operation:
                    raise ModelProviderDeleteRestrictedError(
                        "Model provider configuration is still referenced"
                    ) from exc
                raise ModelProviderReferenceError(
                    "Model provider reference is invalid"
                ) from exc
            raise ModelProviderPersistenceError(
                "Model provider persistence failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise ModelProviderPersistenceError(
                "Model provider persistence failed"
            ) from exc


def _find_provider(
    configuration: OrganizationModelProviderConfiguration,
    provider_id: OrganizationProviderId,
) -> ConfiguredProvider:
    for provider in configuration.providers:
        if provider.provider_id == provider_id:
            return provider
    raise ModelProviderReferenceError("Configured provider was not found")


def _replace_provider(
    configuration: OrganizationModelProviderConfiguration,
    replacement: ConfiguredProvider,
) -> tuple[ConfiguredProvider, ...]:
    _find_provider(configuration, replacement.provider_id)
    return tuple(
        replacement if provider.provider_id == replacement.provider_id else provider
        for provider in configuration.providers
    )


def _find_model(
    configuration: OrganizationModelProviderConfiguration,
    model_id: ConfiguredModelId,
) -> ConfiguredModel:
    for model in configuration.models:
        if model.model_id == model_id:
            return model
    raise ModelProviderReferenceError("Configured model was not found")


def _replace_model(
    configuration: OrganizationModelProviderConfiguration,
    replacement: ConfiguredModel,
) -> tuple[ConfiguredModel, ...]:
    _find_model(configuration, replacement.model_id)
    return tuple(
        replacement if model.model_id == replacement.model_id else model
        for model in configuration.models
    )


def _with_default(
    defaults: DefaultModelSelection,
    model_type: ModelType,
    model_id: ConfiguredModelId | None,
) -> DefaultModelSelection:
    if model_type is ModelType.CHAT:
        return replace(defaults, chat=model_id)
    if model_type is ModelType.EMBEDDING:
        return replace(defaults, embedding=model_id)
    return replace(defaults, reranker=model_id)


def _constraint_name(exc: IntegrityError) -> str | None:
    diagnostic = getattr(exc.orig, "diag", None)
    name = getattr(diagnostic, "constraint_name", None)
    return name if isinstance(name, str) else None


async def _settle_cancelled_transaction(transaction: asyncio.Task[object]) -> None:
    while not transaction.done():
        try:
            await asyncio.shield(transaction)
        except asyncio.CancelledError:
            continue
        except BaseException:  # noqa: BLE001 - cancellation remains authoritative
            return
    if not transaction.cancelled():
        transaction.exception()


__all__ = ["SqlAlchemyModelProviderPersistence"]
