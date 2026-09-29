"""Provider-neutral runtime model target."""

from __future__ import annotations

from dataclasses import dataclass, field

from nexus.model_providers.domain.contracts import (
    ConfiguredModelId,
    OrganizationProviderId,
    ProviderSettings,
    ProviderType,
)
from nexus.model_providers.domain.credential import ProviderCredentialSecret


@dataclass(frozen=True, slots=True)
class ResolvedChatModel:
    """One immutable runtime snapshot with a redacted provider credential."""

    model_id: ConfiguredModelId
    provider_id: OrganizationProviderId
    provider_type: ProviderType
    provider_model_name: str
    settings: ProviderSettings
    credential: ProviderCredentialSecret = field(repr=False)


__all__ = ["ResolvedChatModel"]
