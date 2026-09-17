"""LiteLLM streaming tool-call delta assembly."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from nexus.llm.domain import (
    LLMEvent,
    LLMToolCall,
    LLMToolCallCompletedEvent,
    LLMToolCallDeltaEvent,
    LLMToolCallStartedEvent,
)
from nexus.llm.infrastructure.adapters.litellm.mapping import (
    normalize_tool_call_arguments,
)


@dataclass
class LiteLLMToolCallAssembler:
    """Reconstruct LiteLLM streamed tool-call fragments for one stream."""

    _states: dict[int, _ToolCallState] = field(default_factory=dict)

    def process_chunk(self, chunk: object) -> list[LLMEvent]:
        events: list[LLMEvent] = []
        for delta in _tool_call_deltas(chunk):
            index = _tool_call_index(delta)
            state = self._states.setdefault(index, _ToolCallState(index=index))
            state.update(delta)
            if not state.is_stable:
                continue
            if not state.started:
                events.append(
                    LLMToolCallStartedEvent(
                        tool_call_id=state.tool_call_id,
                        name=state.name,
                    )
                )
                state.started = True
            for arguments_delta in state.pending_argument_deltas:
                events.append(
                    LLMToolCallDeltaEvent(
                        tool_call_id=state.tool_call_id,
                        arguments_delta=arguments_delta,
                    )
                )
            state.pending_argument_deltas.clear()
        return events

    def complete(self) -> list[LLMToolCallCompletedEvent]:
        events: list[LLMToolCallCompletedEvent] = []
        for state in self._states.values():
            if not state.is_stable:
                continue
            arguments = _complete_arguments(state.arguments)
            if arguments is None:
                continue
            events.append(
                LLMToolCallCompletedEvent(
                    tool_call=LLMToolCall(
                        id=state.tool_call_id,
                        name=state.name,
                        arguments=arguments,
                    )
                )
            )
        return events


@dataclass
class _ToolCallState:
    index: int
    tool_call_id: str = ""
    name: str = ""
    arguments: str = ""
    pending_argument_deltas: list[str] = field(default_factory=list)
    started: bool = False

    @property
    def is_stable(self) -> bool:
        return bool(self.tool_call_id and self.name)

    def update(self, delta: object) -> None:
        tool_call_id = _read(delta, "id")
        if isinstance(tool_call_id, str) and tool_call_id:
            self.tool_call_id = tool_call_id

        function = _read(delta, "function", {})
        name = _read(function, "name")
        if isinstance(name, str) and name:
            self.name += name

        arguments = _read(function, "arguments")
        if isinstance(arguments, str) and arguments:
            self.arguments += arguments
            self.pending_argument_deltas.append(arguments)


def _tool_call_deltas(chunk: object) -> list[object]:
    choice = _first_choice(chunk)
    if choice is None:
        return []
    delta = _read(choice, "delta", {})
    tool_calls = _read(delta, "tool_calls", [])
    if not isinstance(tool_calls, Sequence):
        return []
    return list(tool_calls or [])


def _first_choice(chunk: object) -> object | None:
    choices = _read(chunk, "choices", [])
    if not isinstance(choices, Sequence) or not choices:
        return None
    return choices[0]


def _tool_call_index(delta: object) -> int:
    index = _read(delta, "index", 0)
    return index if isinstance(index, int) else 0


def _complete_arguments(value: str) -> dict[str, object] | None:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, Mapping):
        return None
    return normalize_tool_call_arguments(decoded)


def _read(value: object, key: str, default: object | None = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)
