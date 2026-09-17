from __future__ import annotations

from types import SimpleNamespace

import pytest

from nexus.llm.domain import (
    LLMFinishReason,
    LLMMessage,
    LLMRequest,
    LLMRole,
    LLMToolCall,
    LLMToolDefinition,
)
from nexus.llm.infrastructure.adapters.litellm.mapping import (
    LiteLLMToolCallMappingError,
    to_litellm_payload,
    to_llm_response,
)


def test_maps_messages_model_and_generation_parameters() -> None:
    request = LLMRequest(
        model="gpt-test",
        messages=[
            LLMMessage(role=LLMRole.SYSTEM, content="Be concise"),
            LLMMessage(role=LLMRole.USER, content="Hello"),
            LLMMessage(role=LLMRole.ASSISTANT, content="Hi"),
            LLMMessage(role=LLMRole.TOOL, content="Result", tool_call_id="call_1"),
        ],
        temperature=0.2,
        max_output_tokens=128,
    )

    payload = to_litellm_payload(request)

    assert payload == {
        "model": "gpt-test",
        "messages": [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "tool", "content": "Result", "tool_call_id": "call_1"},
        ],
        "temperature": 0.2,
        "max_tokens": 128,
    }


def test_maps_tool_definitions_to_litellm_payload() -> None:
    parameters_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
    }
    request = LLMRequest(
        model="gpt-test",
        messages=[LLMMessage(role=LLMRole.USER, content="Search")],
        tools=[
            LLMToolDefinition(
                name="search",
                description="Search documents",
                parameters_schema=parameters_schema,
            )
        ],
    )

    payload = to_litellm_payload(request)

    assert payload["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search documents",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        }
    ]
    assert request.tools[0].parameters_schema == parameters_schema


def test_maps_litellm_response_usage_and_finish_reason() -> None:
    response = {
        "id": "resp_123",
        "model": "gpt-test",
        "choices": [
            {
                "message": {"role": "assistant", "content": "Hello"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 4,
            "completion_tokens": 2,
            "total_tokens": 6,
        },
    }

    mapped = to_llm_response(response)

    assert mapped.message.role is LLMRole.ASSISTANT
    assert mapped.message.content == "Hello"
    assert mapped.finish_reason is LLMFinishReason.STOP
    assert mapped.usage is not None
    assert mapped.usage.input_tokens == 4
    assert mapped.usage.output_tokens == 2
    assert mapped.usage.total_tokens == 6
    assert mapped.metadata == {
        "model": "gpt-test",
        "provider_response_id": "resp_123",
    }


def test_maps_assistant_tool_call_only_response() -> None:
    response = SimpleNamespace(
        id="resp_123",
        model="gpt-test",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            function=SimpleNamespace(
                                name="search",
                                arguments={"query": "nexus"},
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=None,
    )

    mapped = to_llm_response(response)

    assert mapped.message.content is None
    assert mapped.finish_reason is LLMFinishReason.TOOL_CALLS
    assert len(mapped.tool_calls) == 1
    assert mapped.tool_calls[0].id == "call_1"
    assert mapped.tool_calls[0].name == "search"
    assert mapped.tool_calls[0].arguments == {"query": "nexus"}
    assert isinstance(mapped.tool_calls[0], LLMToolCall)


def test_maps_json_string_tool_call_arguments() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "search",
                                "arguments": '{"query": "nexus"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }

    mapped = to_llm_response(response)

    assert mapped.tool_calls[0].arguments == {"query": "nexus"}
    assert not isinstance(mapped.tool_calls[0].arguments, str)


@pytest.mark.parametrize("arguments", ['{"query"', '["nexus"]', '"nexus"', "1", "null"])
def test_invalid_tool_call_arguments_are_rejected(arguments: str) -> None:
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "search",
                                "arguments": arguments,
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }

    with pytest.raises(LiteLLMToolCallMappingError):
        to_llm_response(response)


def test_maps_multiple_tool_calls_without_provider_object_leakage() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "search",
                                "arguments": '{"query": "nexus"}',
                            },
                        },
                        {
                            "id": "call_2",
                            "function": {
                                "name": "lookup",
                                "arguments": {"id": "42"},
                            },
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }

    mapped = to_llm_response(response)

    assert mapped.tool_calls == (
        LLMToolCall(id="call_1", name="search", arguments={"query": "nexus"}),
        LLMToolCall(id="call_2", name="lookup", arguments={"id": "42"}),
    )
    assert all(isinstance(tool_call, LLMToolCall) for tool_call in mapped.tool_calls)


def test_rejects_nested_provider_objects_in_tool_call_arguments() -> None:
    provider_object = SimpleNamespace(secret="provider-secret")
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "search",
                                "arguments": {"provider": provider_object},
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }

    with pytest.raises(LiteLLMToolCallMappingError):
        to_llm_response(response)
