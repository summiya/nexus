"""Deterministic, non-identifying credential storage names."""

from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from nexus.model_providers.domain import CredentialReference, OrganizationProviderId

_NAME_PREFIX = "npc-v1-"
_DIGEST_DOMAIN = b"nexus-provider-credential-v1\x00"


def credential_storage_name(
    *,
    organization_public_id: UUID,
    provider_id: OrganizationProviderId,
    credential_reference: CredentialReference,
) -> str:
    """Return a fixed-length Key Vault-compatible opaque credential name."""

    digest = sha256(
        _DIGEST_DOMAIN
        + organization_public_id.bytes
        + provider_id.value.bytes
        + credential_reference.value.bytes
    ).hexdigest()
    return f"{_NAME_PREFIX}{digest}"
