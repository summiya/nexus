from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator

from nexus.llm.domain import (
    LLMCompletedEvent,
    LLMEvent,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMRole,
    LLMTextDeltaEvent,
)
from nexus.llm.ports import LLMGateway


class FakeLLMGateway:
    def __init__(self) -> None:
        self.generated_requests: list[LLMRequest] = []
        self.streamed_requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.generated_requests.append(request)
        return LLMResponse(
            message=LLMMessage(role=LLMRole.ASSISTANT, content="Hello"),
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        self.streamed_requests.append(request)
        yield LLMTextDeltaEvent(delta="Hel")
        yield LLMCompletedEvent()


def request() -> LLMRequest:
    return LLMRequest(
        model="gpt-test",
        messages=[LLMMessage(role=LLMRole.USER, content="Hello")],
    )


def test_gateway_port_declares_async_generate() -> None:
    assert inspect.iscoroutinefunction(LLMGateway.generate)


def test_fake_gateway_satisfies_generate_contract() -> None:
    gateway = FakeLLMGateway()
    llm_request = request()

    response = asyncio.run(gateway.generate(llm_request))

    assert gateway.generated_requests == [llm_request]
    assert response.message.content == "Hello"


def test_fake_gateway_satisfies_stream_contract() -> None:
    gateway = FakeLLMGateway()
    llm_request = request()

    async def collect_events() -> list[LLMEvent]:
        return [event async for event in gateway.stream(llm_request)]

    events = asyncio.run(collect_events())

    assert gateway.streamed_requests == [llm_request]
    assert events == [
        LLMTextDeltaEvent(delta="Hel"),
        LLMCompletedEvent(),
    ]
