from __future__ import annotations

from types import SimpleNamespace

from nexus.llm.domain import (
    LLMFinishReason,
    LLMMessage,
    LLMRequest,
    LLMRole,
    LLMToolDefinition,
)
from nexus.llm.infrastructure.adapters.litellm.mapping import (
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
    request = LLMRequest(
        model="gpt-test",
        messages=[LLMMessage(role=LLMRole.USER, content="Search")],
        tools=[
            LLMToolDefinition(
                name="search",
                description="Search documents",
                parameters_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
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
