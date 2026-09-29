"""Transient provider model discovery value."""

from __future__ import annotations

from dataclasses import dataclass, field

from nexus.model_providers.domain.contracts import ModelCapability, ModelType
from nexus.model_providers.domain.errors import ModelProviderConfigurationError
from nexus.model_providers.domain.validation import (
    MAX_DISPLAY_NAME_LENGTH,
    MAX_PROVIDER_MODEL_NAME_LENGTH,
    require_bounded_text,
)


@dataclass(frozen=True)
class ModelCandidate:
    """One safely classified, non-persisted provider model."""

    provider_model_name: str
    display_name: str
    model_type: ModelType
    capabilities: frozenset[ModelCapability] = field(default_factory=frozenset)
    embedding_dimension: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_model_name",
            require_bounded_text(
                self.provider_model_name,
                field_name="Provider model name",
                max_length=MAX_PROVIDER_MODEL_NAME_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "display_name",
            require_bounded_text(
                self.display_name,
                field_name="Model display name",
                max_length=MAX_DISPLAY_NAME_LENGTH,
            ),
        )
        if not isinstance(self.model_type, ModelType):
            raise ModelProviderConfigurationError("Unknown model type.")
        if any(
            not isinstance(capability, ModelCapability)
            for capability in self.capabilities
        ):
            raise ModelProviderConfigurationError("Unknown model capability.")
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        if self.model_type is not ModelType.CHAT and self.capabilities:
            raise ModelProviderConfigurationError(
                "Non-chat model candidates cannot declare chat capabilities."
            )
        if self.embedding_dimension is not None and (
            type(self.embedding_dimension) is not int or self.embedding_dimension <= 0
        ):
            raise ModelProviderConfigurationError(
                "Embedding dimension must be positive when known."
            )
        if self.model_type is not ModelType.EMBEDDING and (
            self.embedding_dimension is not None
        ):
            raise ModelProviderConfigurationError(
                "Only embedding candidates can declare an embedding dimension."
            )


__all__ = ["ModelCandidate"]
