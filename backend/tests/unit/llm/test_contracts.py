from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from nexus.llm.domain import (
    LLMAuthenticationError,
    LLMCompletedEvent,
    LLMErrorEvent,
    LLMErrorKind,
    LLMEventType,
    LLMFinishReason,
    LLMMessage,
    LLMProviderCapabilities,
    LLMRequest,
    LLMResponse,
    LLMRole,
    LLMTextDeltaEvent,
    LLMToolCall,
    LLMToolCallCompletedEvent,
    LLMToolCallDeltaEvent,
    LLMToolCallStartedEvent,
    LLMToolDefinition,
    LLMUsage,
    LLMUsageEvent,
)


def test_llm_request_normalizes_sequences_and_metadata() -> None:
    message = LLMMessage(role=LLMRole.USER, content="Hello")
    tool = LLMToolDefinition(
        name="search",
        description="Search documents",
        parameters_schema={"type": "object"},
    )

    request = LLMRequest(
        model="gpt-test",
        messages=[message],
        tools=[tool],
        metadata={"trace": "safe"},
    )

    assert request.messages == (message,)
    assert request.tools == (tool,)
    assert isinstance(request.metadata, MappingProxyType)
    assert request.metadata == {"trace": "safe"}


@pytest.mark.parametrize(
    "request_kwargs",
    [
        {"model": "", "messages": [LLMMessage(role=LLMRole.USER, content="Hello")]},
        {"model": "gpt-test", "messages": []},
        {
            "model": "gpt-test",
            "messages": [LLMMessage(role=LLMRole.USER, content="Hello")],
            "temperature": -0.1,
        },
        {
            "model": "gpt-test",
            "messages": [LLMMessage(role=LLMRole.USER, content="Hello")],
            "max_output_tokens": 0,
        },
    ],
)
def test_llm_request_rejects_invalid_core_values(
    request_kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        LLMRequest(**request_kwargs)  # type: ignore[arg-type]


def test_llm_message_rejects_empty_content() -> None:
    with pytest.raises(ValueError):
        LLMMessage(role=LLMRole.USER, content="")


def test_llm_usage_rejects_negative_counts() -> None:
    with pytest.raises(ValueError):
        LLMUsage(input_tokens=-1)


def test_tool_contracts_defensively_copy_mappings() -> None:
    schema = {"type": "object"}
    arguments = {"query": "nexus"}

    definition = LLMToolDefinition(
        name="search",
        description="Search documents",
        parameters_schema=schema,
    )
    call = LLMToolCall(id="call_1", name="search", arguments=arguments)

    schema["type"] = "mutated"
    arguments["query"] = "mutated"

    assert definition.parameters_schema == {"type": "object"}
    assert call.arguments == {"query": "nexus"}
    assert isinstance(definition.parameters_schema, MappingProxyType)
    assert isinstance(call.arguments, MappingProxyType)


def test_response_normalizes_tool_calls_and_metadata() -> None:
    message = LLMMessage(role=LLMRole.ASSISTANT, content="Done")
    tool_call = LLMToolCall(id="call_1", name="search")

    response = LLMResponse(
        message=message,
        finish_reason=LLMFinishReason.TOOL_CALLS,
        usage=LLMUsage(input_tokens=3, output_tokens=2, total_tokens=5),
        tool_calls=[tool_call],
        metadata={"provider": "safe"},
    )

    assert response.tool_calls == (tool_call,)
    assert response.metadata == {"provider": "safe"}


def test_stream_event_contracts_are_provider_independent() -> None:
    tool_call = LLMToolCall(id="call_1", name="search", arguments={"q": "nexus"})
    events = [
        LLMTextDeltaEvent(delta="Hel"),
        LLMToolCallStartedEvent(tool_call_id="call_1", name="search"),
        LLMToolCallDeltaEvent(tool_call_id="call_1", arguments_delta='{"q"'),
        LLMToolCallCompletedEvent(tool_call=tool_call),
        LLMUsageEvent(usage=LLMUsage(input_tokens=1, output_tokens=1, total_tokens=2)),
        LLMCompletedEvent(finish_reason=LLMFinishReason.STOP),
        LLMErrorEvent(
            kind=LLMErrorKind.PROVIDER_UNAVAILABLE,
            message="Provider unavailable",
            retryable=True,
        ),
    ]

    assert [event.type for event in events] == [
        LLMEventType.TEXT_DELTA,
        LLMEventType.TOOL_CALL_STARTED,
        LLMEventType.TOOL_CALL_DELTA,
        LLMEventType.TOOL_CALL_COMPLETED,
        LLMEventType.USAGE,
        LLMEventType.COMPLETED,
        LLMEventType.ERROR,
    ]


def test_llm_error_exposes_only_safe_details() -> None:
    error = LLMAuthenticationError(
        "LLM authentication failed",
        safe_details={"provider": "litellm"},
    )

    assert error.kind is LLMErrorKind.AUTHENTICATION
    assert error.retryable is False
    assert error.safe_details == {"provider": "litellm"}
    assert isinstance(error.safe_details, MappingProxyType)


def test_contracts_are_frozen() -> None:
    message = LLMMessage(role=LLMRole.USER, content="Hello")

    with pytest.raises(FrozenInstanceError):
        message.content = "changed"  # type: ignore[misc]


def test_capabilities_contract_is_explicit() -> None:
    capabilities = LLMProviderCapabilities(
        supports_streaming=True,
        supports_tool_calls=True,
        supports_usage=True,
    )

    assert capabilities.supports_streaming is True
    assert capabilities.supports_tool_calls is True
    assert capabilities.supports_usage is True
    assert capabilities.supports_json_response is False
