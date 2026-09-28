"""Cancellation-safe model-provider credential lifecycle helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from uuid import UUID

from nexus.logging import get_logger
from nexus.model_providers.domain import CredentialReference, OrganizationProviderId
from nexus.model_providers.ports import (
    CredentialStore,
    CredentialStoreError,
    credential_storage_name,
)

logger = get_logger(__name__)


async def settle_before_cancellation[T](operation: Awaitable[T]) -> T:
    """Settle one critical cross-system operation before propagating cancellation."""

    task: asyncio.Future[T] = asyncio.ensure_future(operation)
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancellation = exc
        except BaseException:  # noqa: BLE001 - task.result re-raises without cancellation
            break
    if cancellation is not None:
        if not task.cancelled():
            task.exception()
        raise cancellation
    return task.result()


async def delete_credential_best_effort(
    store: CredentialStore | None,
    *,
    organization_public_id: UUID,
    actor_user_public_id: UUID,
    provider_id: OrganizationProviderId,
    credential_reference: CredentialReference,
    reason: str,
) -> bool:
    storage_name = credential_storage_name(
        organization_public_id=organization_public_id,
        provider_id=provider_id,
        credential_reference=credential_reference,
    )
    if store is not None:
        try:
            await store.delete(
                organization_public_id=organization_public_id,
                provider_id=provider_id,
                credential_reference=credential_reference,
            )
            return True
        except CredentialStoreError:
            pass
    logger.warning(
        "model_provider_credential_cleanup_failed",
        organization_public_id=str(organization_public_id),
        actor_user_public_id=str(actor_user_public_id),
        provider_public_id=str(provider_id.value),
        orphan_storage_name=storage_name,
        cleanup_reason=reason,
    )
    return False
