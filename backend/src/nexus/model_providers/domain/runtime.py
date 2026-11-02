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
from nexus.model_providers.domain.errors import ModelProviderConfigurationError
from nexus.model_providers.domain.validation import (
    MAX_PROVIDER_MODEL_NAME_LENGTH,
    require_bounded_text,
)


@dataclass(frozen=True, slots=True)
class ResolvedChatModel:
    """One immutable runtime snapshot with a redacted provider credential."""

    model_id: ConfiguredModelId
    provider_id: OrganizationProviderId
    provider_type: ProviderType
    provider_model_name: str
    settings: ProviderSettings
    credential: ProviderCredentialSecret = field(repr=False)


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingModel:
    """A configured embedding target; only a trusted adapter reveals its credential."""

    model_id: ConfiguredModelId
    provider_id: OrganizationProviderId
    provider_type: ProviderType
    provider_model_name: str
    embedding_dimension: int
    settings: ProviderSettings
    credential: ProviderCredentialSecret = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.model_id, ConfiguredModelId)
            or not self.model_id.value.int
            or not isinstance(self.provider_id, OrganizationProviderId)
            or not self.provider_id.value.int
            or not isinstance(self.provider_type, ProviderType)
        ):
            raise ModelProviderConfigurationError(
                "Embedding model identity is invalid."
            )
        if type(self.embedding_dimension) is not int or self.embedding_dimension <= 0:
            raise ModelProviderConfigurationError(
                "Embedding dimension must be positive."
            )
        if not isinstance(self.credential, ProviderCredentialSecret):
            raise ModelProviderConfigurationError(
                "Embedding credential must be protected."
            )
        object.__setattr__(
            self,
            "provider_model_name",
            require_bounded_text(
                self.provider_model_name,
                field_name="Provider model name",
                max_length=MAX_PROVIDER_MODEL_NAME_LENGTH,
            ),
        )


__all__ = ["ResolvedChatModel", "ResolvedEmbeddingModel"]
