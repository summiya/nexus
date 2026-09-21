"""Configured policy for models that Nexus may invoke."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


class ModelNotAllowedError(ValueError):
    """Raised when a caller requests a model outside the configured allowlist."""


@dataclass(frozen=True)
class ModelPolicy:
    """Resolve only explicitly configured provider model identifiers."""

    allowed_models: frozenset[str]

    def __post_init__(self) -> None:
        if not self.allowed_models or any(not model for model in self.allowed_models):
            raise ValueError("At least one non-blank LLM model must be configured")

    @classmethod
    def from_models(cls, models: Iterable[str]) -> ModelPolicy:
        return cls(frozenset(model.strip() for model in models))

    def resolve(self, requested_model: str) -> str:
        model = requested_model.strip()
        if not model or model not in self.allowed_models:
            raise ModelNotAllowedError("Requested model is not allowed")
        return model
