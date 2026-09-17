"""Configured construction of concrete LLM gateway adapters."""

from __future__ import annotations

from nexus.llm.infrastructure.adapters.litellm import LiteLLMAdapter
from nexus.llm.ports import LLMGateway


class UnsupportedLLMGatewayError(ValueError):
    """Raised when no allow-listed gateway matches the configured identifier."""


def create_llm_gateway(gateway_name: str) -> LLMGateway:
    """Construct the configured gateway without dynamic provider loading."""

    if gateway_name == "litellm":
        return LiteLLMAdapter()
    raise UnsupportedLLMGatewayError("Unsupported LLM gateway configuration")
