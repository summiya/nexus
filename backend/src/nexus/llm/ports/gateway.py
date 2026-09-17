"""Provider-independent LLM gateway port."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from nexus.llm.domain.events import LLMEvent
from nexus.llm.domain.requests import LLMRequest
from nexus.llm.domain.responses import LLMResponse


class LLMGateway(Protocol):
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a complete response for a provider-independent request."""

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        """Stream normalized provider-independent LLM events."""
