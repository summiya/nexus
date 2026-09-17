"""Stateless LiteLLM/NEXUS contract mapping helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from nexus.llm.domain import (
    LLMFinishReason,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMRole,
    LLMToolCall,
    LLMToolDefinition,
    LLMUsage,
)

type LiteLLMPayload = dict[str, object]


def to_litellm_payload(request: LLMRequest) -> LiteLLMPayload:
    payload: LiteLLMPayload = {
        "model": request.model,
        "messages": [_message_to_litellm(message) for message in request.messages],
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_output_tokens is not None:
        payload["max_tokens"] = request.max_output_tokens
    if request.tools:
        payload["tools"] = [_tool_to_litellm(tool) for tool in request.tools]
    return payload


def to_llm_response(response: object) -> LLMResponse:
    choice = _first_choice(response)
    message = _read(choice, "message")
    tool_calls = tuple(_tool_call_from_litellm(value) for value in _tool_calls(message))
    content = _read(message, "content")

    return LLMResponse(
        message=LLMMessage(
            role=_role_from_litellm(_read(message, "role", "assistant")),
            content=content if isinstance(content, str) else None,
        ),
        finish_reason=_finish_reason_from_litellm(_read(choice, "finish_reason")),
        usage=_usage_from_litellm(_read(response, "usage")),
        tool_calls=tool_calls,
        metadata=_safe_metadata(response),
    )


def _message_to_litellm(message: LLMMessage) -> dict[str, object]:
    mapped: dict[str, object] = {"role": message.role.value, "content": message.content}
    if message.name is not None:
        mapped["name"] = message.name
    if message.tool_call_id is not None:
        mapped["tool_call_id"] = message.tool_call_id
    return mapped


def _tool_to_litellm(tool: LLMToolDefinition) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters_schema),
        },
    }


def _first_choice(response: object) -> object:
    choices = _read(response, "choices", [])
    if not isinstance(choices, Sequence):
        raise TypeError("LiteLLM response choices must be a sequence")
    if not choices:
        raise ValueError("LiteLLM response did not include choices")
    return choices[0]


def _tool_calls(message: object) -> list[object]:
    value = _read(message, "tool_calls", [])
    if not isinstance(value, Sequence):
        return []
    return list(value or [])


def _tool_call_from_litellm(tool_call: object) -> LLMToolCall:
    function = _read(tool_call, "function", {})
    arguments = _read(function, "arguments", {})
    return LLMToolCall(
        id=str(_read(tool_call, "id")),
        name=str(_read(function, "name")),
        arguments=arguments if isinstance(arguments, Mapping) else {"raw": arguments},
    )


def _usage_from_litellm(usage: object) -> LLMUsage | None:
    if usage is None:
        return None
    input_tokens = _as_int(_read(usage, "prompt_tokens", 0))
    output_tokens = _as_int(_read(usage, "completion_tokens", 0))
    total_tokens = _as_int(_read(usage, "total_tokens", input_tokens + output_tokens))
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def _finish_reason_from_litellm(value: object) -> LLMFinishReason:
    match value:
        case "stop":
            return LLMFinishReason.STOP
        case "length":
            return LLMFinishReason.LENGTH
        case "tool_calls" | "function_call":
            return LLMFinishReason.TOOL_CALLS
        case "content_filter":
            return LLMFinishReason.CONTENT_FILTER
        case _:
            return LLMFinishReason.UNKNOWN


def _role_from_litellm(value: object) -> LLMRole:
    try:
        return LLMRole(str(value))
    except ValueError:
        return LLMRole.ASSISTANT


def _safe_metadata(response: object) -> dict[str, object]:
    metadata: dict[str, object] = {}
    model = _read(response, "model")
    response_id = _read(response, "id")
    if isinstance(model, str) and model:
        metadata["model"] = model
    if isinstance(response_id, str) and response_id:
        metadata["provider_response_id"] = response_id
    return metadata


def _read(value: object, key: str, default: object | None = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _as_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0
