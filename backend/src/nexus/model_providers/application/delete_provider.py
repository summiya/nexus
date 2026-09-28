"""Delete one configured model provider and clean up its credential."""

from dataclasses import dataclass
from uuid import UUID

from nexus.authorization import PermissionChecker
from nexus.errors import ErrorCode, NexusError
from nexus.logging import get_logger
from nexus.model_providers.application._credential_lifecycle import (
    delete_credential_best_effort,
    settle_before_cancellation,
)
from nexus.model_providers.application._shared import (
    MANAGE_PERMISSION,
    NOT_FOUND,
    authorize,
    conflict,
    credential_unavailable,
    get_provider,
    unavailable,
)
from nexus.model_providers.domain import OrganizationProviderId
from nexus.model_providers.ports import (
    CredentialStore,
    ModelProviderDeleteRestrictedError,
    ModelProviderPersistence,
    ModelProviderPersistenceError,
    ModelProviderReferenceError,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class DeleteModelProvider:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker
    credential_store: CredentialStore | None

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_public_id: UUID,
    ) -> None:
        await authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=MANAGE_PERMISSION,
        )
        provider_id = OrganizationProviderId(provider_public_id)
        existing = await get_provider(
            self.persistence,
            organization_public_id=organization_public_id,
            provider_id=provider_id,
        )
        if existing.credential_reference is not None and self.credential_store is None:
            raise credential_unavailable()
        await settle_before_cancellation(
            self._delete_and_cleanup(
                organization_public_id=organization_public_id,
                actor_user_public_id=user_public_id,
                provider_id=provider_id,
            )
        )

    async def _delete_and_cleanup(
        self,
        *,
        organization_public_id: UUID,
        actor_user_public_id: UUID,
        provider_id: OrganizationProviderId,
    ) -> None:
        try:
            deleted = await self.persistence.delete_provider(
                organization_public_id=organization_public_id,
                provider_id=provider_id,
            )
        except ModelProviderDeleteRestrictedError as exc:
            raise conflict() from exc
        except ModelProviderReferenceError as exc:
            raise NexusError(ErrorCode.NOT_FOUND, NOT_FOUND) from exc
        except ModelProviderPersistenceError as exc:
            raise unavailable() from exc
        reference = deleted.credential_reference
        if reference is None:
            return
        cleanup_succeeded = await delete_credential_best_effort(
            self.credential_store,
            organization_public_id=organization_public_id,
            actor_user_public_id=actor_user_public_id,
            provider_id=provider_id,
            credential_reference=reference,
            reason="provider_delete_cleanup",
        )
        if cleanup_succeeded:
            logger.info(
                "model_provider_credential_deleted",
                organization_public_id=str(organization_public_id),
                actor_user_public_id=str(actor_user_public_id),
                provider_public_id=str(provider_id.value),
            )


__all__ = ["DeleteModelProvider"]
