from __future__ import annotations

import pytest

from nexus.llm.infrastructure.adapters.litellm import LiteLLMAdapter
from nexus.llm.infrastructure.gateway_factory import (
    UnsupportedLLMGatewayError,
    create_llm_gateway,
)


def test_factory_builds_litellm_gateway_without_network_access() -> None:
    gateway = create_llm_gateway("litellm")

    assert isinstance(gateway, LiteLLMAdapter)


def test_factory_rejects_unsupported_gateway_without_fallback() -> None:
    with pytest.raises(
        UnsupportedLLMGatewayError,
        match="Unsupported LLM gateway configuration",
    ):
        create_llm_gateway("unsupported")
