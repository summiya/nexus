from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from nexus.llm.application import Generate
from nexus.llm.domain import (
    LLMCompletedEvent,
    LLMEvent,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMRole,
)


class FakeGateway:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []
        self.response = LLMResponse(
            message=LLMMessage(role=LLMRole.ASSISTANT, content="Hello")
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return self.response

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        del request
        return _empty_stream()


async def _empty_stream() -> AsyncIterator[LLMEvent]:
    yield LLMCompletedEvent()


def test_generate_delegates_to_injected_gateway() -> None:
    gateway = FakeGateway()
    request = LLMRequest(
        model="gpt-test",
        messages=[LLMMessage(role=LLMRole.USER, content="Hello")],
    )

    response = asyncio.run(Generate(gateway=gateway).execute(request))

    assert response is gateway.response
    assert gateway.requests == [request]
