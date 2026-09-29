"""Fail-closed configuration for LiteLLM's bundled model metadata."""

from __future__ import annotations

import os

_LOCAL_MODEL_COST_MAP_ENV = "LITELLM_LOCAL_MODEL_COST_MAP"


class LiteLLMConfigurationError(ValueError):
    """LiteLLM cannot be used under the required local-metadata policy."""


def require_local_litellm_metadata() -> None:
    """Require local metadata before any supported Nexus LiteLLM import."""

    if os.environ.get(_LOCAL_MODEL_COST_MAP_ENV, "").lower() != "true":
        raise LiteLLMConfigurationError("Local LiteLLM model metadata must be enabled.")


__all__ = ["LiteLLMConfigurationError", "require_local_litellm_metadata"]
