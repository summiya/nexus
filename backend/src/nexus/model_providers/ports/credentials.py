"""Provider-neutral credential storage boundary."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from nexus.model_providers.domain import (
    CredentialReference,
    OrganizationProviderId,
    ProviderCredentialSecret,
)


class CredentialStoreError(RuntimeError):
    """Raised when credential storage cannot complete safely."""


class CredentialNotFoundError(CredentialStoreError):
    """Raised when a requested credential does not exist."""


class CredentialStoreConflictError(CredentialStoreError):
    """Raised when a credential reference cannot safely be reused."""


class CredentialStore(Protocol):
    """Organization/provider/reference-scoped credential storage capability."""

    async def put(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
        secret: ProviderCredentialSecret,
    ) -> None: ...

    async def resolve(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
    ) -> ProviderCredentialSecret: ...

    async def delete(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
    ) -> None: ...
