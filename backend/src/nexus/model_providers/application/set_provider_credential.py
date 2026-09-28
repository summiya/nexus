"""Assign or replace one configured provider credential."""

from dataclasses import dataclass
from uuid import UUID, uuid4

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
from nexus.model_providers.domain import (
    ConfiguredProvider,
    CredentialReference,
    ModelProviderConfigurationError,
    OrganizationProviderId,
    ProviderCredentialSecret,
)
from nexus.model_providers.ports import (
    CredentialStore,
    CredentialStoreConflictError,
    CredentialStoreError,
    ModelProviderConflictError,
    ModelProviderPersistence,
    ModelProviderPersistenceError,
    ModelProviderReferenceError,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class SetModelProviderCredential:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker
    credential_store: CredentialStore | None

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_public_id: UUID,
        secret: ProviderCredentialSecret,
    ) -> ConfiguredProvider:
        await authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=MANAGE_PERMISSION,
        )
        store = self.credential_store
        if store is None:
            raise credential_unavailable()
        provider_id = OrganizationProviderId(provider_public_id)
        provider = await get_provider(
            self.persistence,
            organization_public_id=organization_public_id,
            provider_id=provider_id,
        )
        return await settle_before_cancellation(
            self._replace_credential(
                store=store,
                organization_public_id=organization_public_id,
                actor_user_public_id=user_public_id,
                provider_id=provider_id,
                old_reference=provider.credential_reference,
                secret=secret,
            )
        )

    async def _replace_credential(
        self,
        *,
        store: CredentialStore,
        organization_public_id: UUID,
        actor_user_public_id: UUID,
        provider_id: OrganizationProviderId,
        old_reference: CredentialReference | None,
        secret: ProviderCredentialSecret,
    ) -> ConfiguredProvider:
        new_reference = CredentialReference(uuid4())
        try:
            await store.put(
                organization_public_id=organization_public_id,
                provider_id=provider_id,
                credential_reference=new_reference,
                secret=secret,
            )
        except CredentialStoreConflictError as exc:
            raise conflict() from exc
        except CredentialStoreError as exc:
            raise credential_unavailable() from exc

        try:
            updated = await self.persistence.set_provider_credential_reference(
                organization_public_id=organization_public_id,
                provider_id=provider_id,
                expected_credential_reference=old_reference,
                credential_reference=new_reference,
            )
        except (
            ModelProviderConflictError,
            ModelProviderReferenceError,
            ModelProviderPersistenceError,
            ModelProviderConfigurationError,
        ) as exc:
            await delete_credential_best_effort(
                store,
                organization_public_id=organization_public_id,
                actor_user_public_id=actor_user_public_id,
                provider_id=provider_id,
                credential_reference=new_reference,
                reason="credential_switch_compensation",
            )
            if isinstance(exc, ModelProviderConflictError):
                raise conflict() from exc
            if isinstance(exc, ModelProviderReferenceError):
                raise NexusError(ErrorCode.NOT_FOUND, NOT_FOUND) from exc
            if isinstance(exc, ModelProviderConfigurationError):
                raise NexusError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
            raise unavailable() from exc

        if old_reference is not None:
            await delete_credential_best_effort(
                store,
                organization_public_id=organization_public_id,
                actor_user_public_id=actor_user_public_id,
                provider_id=provider_id,
                credential_reference=old_reference,
                reason="credential_replacement_cleanup",
            )
            event = "model_provider_credential_replaced"
        else:
            event = "model_provider_credential_set"
        logger.info(
            event,
            organization_public_id=str(organization_public_id),
            actor_user_public_id=str(actor_user_public_id),
            provider_public_id=str(provider_id.value),
        )
        return updated


__all__ = ["SetModelProviderCredential"]
