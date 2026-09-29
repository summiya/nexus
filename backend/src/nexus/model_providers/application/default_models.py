"""Organization default-model selection application services."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nexus.authorization import PermissionChecker
from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.application._shared import (
    MANAGE_PERMISSION,
    NOT_FOUND,
    READ_PERMISSION,
    authorize,
    conflict,
    load_configuration,
    unavailable,
)
from nexus.model_providers.domain import (
    ConfiguredModelId,
    DefaultModelSelection,
    ModelProviderConfigurationError,
    ModelType,
)
from nexus.model_providers.ports import (
    ModelProviderConflictError,
    ModelProviderPersistence,
    ModelProviderPersistenceError,
    ModelProviderReferenceError,
)


@dataclass(frozen=True)
class GetDefaultModels:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
    ) -> DefaultModelSelection:
        await authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=READ_PERMISSION,
        )
        configuration = await load_configuration(
            self.persistence,
            organization_public_id=organization_public_id,
        )
        return (
            DefaultModelSelection() if configuration is None else configuration.defaults
        )


@dataclass(frozen=True)
class SetDefaultModel:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        model_type: ModelType,
        model_public_id: UUID,
    ) -> DefaultModelSelection:
        await authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=MANAGE_PERMISSION,
        )
        return await _set_default(
            self.persistence,
            organization_public_id=organization_public_id,
            model_type=model_type,
            model_id=ConfiguredModelId(model_public_id),
        )


@dataclass(frozen=True)
class ClearDefaultModel:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        model_type: ModelType,
    ) -> None:
        await authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=MANAGE_PERMISSION,
        )
        await _set_default(
            self.persistence,
            organization_public_id=organization_public_id,
            model_type=model_type,
            model_id=None,
        )


async def _set_default(
    persistence: ModelProviderPersistence,
    *,
    organization_public_id: UUID,
    model_type: ModelType,
    model_id: ConfiguredModelId | None,
) -> DefaultModelSelection:
    try:
        return await persistence.set_default(
            organization_public_id=organization_public_id,
            model_type=model_type,
            model_id=model_id,
        )
    except (ModelProviderConflictError, ModelProviderConfigurationError) as exc:
        raise conflict() from exc
    except ModelProviderReferenceError as exc:
        raise NexusError(ErrorCode.NOT_FOUND, NOT_FOUND) from exc
    except ModelProviderPersistenceError as exc:
        raise unavailable() from exc


__all__ = ["ClearDefaultModel", "GetDefaultModels", "SetDefaultModel"]
