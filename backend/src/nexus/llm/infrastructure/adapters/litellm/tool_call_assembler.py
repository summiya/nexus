"""LiteLLM streaming tool-call delta assembly."""

from __future__ import annotations

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
    LiteLLMToolCallMappingError,
    normalize_tool_call_arguments,
)

_MISSING = object()


@dataclass
class LiteLLMToolCallAssembler:
    """Reconstruct LiteLLM streamed tool-call fragments for one stream."""

    _states: list[_ToolCallState] = field(default_factory=list)
    _states_by_index: dict[int, _ToolCallState] = field(default_factory=dict)
    _states_by_id: dict[str, _ToolCallState] = field(default_factory=dict)
    _has_invalid_completion: bool = False

    @property
    def has_invalid_completion(self) -> bool:
        return self._has_invalid_completion

    def process_chunk(self, chunk: object) -> list[LLMEvent]:
        events: list[LLMEvent] = []
        for delta in _tool_call_deltas(chunk):
            state = self._resolve_state(delta)
            if state is None:
                self._has_invalid_completion = True
                continue

            state.update(delta)
            if state.invalid or not state.is_stable:
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
        for state in self._states:
            if state.invalid or not state.is_stable:
                self._has_invalid_completion = True
                continue
            arguments = _complete_arguments(state.arguments)
            if arguments is None:
                self._has_invalid_completion = True
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

    def _resolve_state(self, delta: object) -> _ToolCallState | None:
        raw_index = _read(delta, "index", _MISSING)
        index = _valid_index(raw_index)
        tool_call_id = _tool_call_id(delta)

        if index is None and tool_call_id is None:
            return None

        index_state = self._states_by_index.get(index) if index is not None else None
        id_state = (
            self._states_by_id.get(tool_call_id) if tool_call_id is not None else None
        )
        if (
            index_state is not None
            and id_state is not None
            and index_state is not id_state
        ):
            index_state.invalid = True
            id_state.invalid = True
            return None

        state = index_state or id_state
        if state is None:
            state = _ToolCallState()
            self._states.append(state)

        if index is not None and state.provider_index not in (None, index):
            state.invalid = True
            return None
        if (
            tool_call_id is not None
            and state.tool_call_id
            and state.tool_call_id != tool_call_id
        ):
            state.invalid = True
            return None

        if index is not None:
            state.provider_index = index
            self._states_by_index[index] = state
        if tool_call_id is not None:
            self._states_by_id[tool_call_id] = state
        return state


@dataclass
class _ToolCallState:
    provider_index: int | None = None
    tool_call_id: str = ""
    name: str = ""
    arguments: str = ""
    pending_argument_deltas: list[str] = field(default_factory=list)
    started: bool = False
    arguments_seen: bool = False
    invalid: bool = False

    @property
    def is_stable(self) -> bool:
        return bool(self.tool_call_id and self.name and self.arguments_seen)

    def update(self, delta: object) -> None:
        tool_call_id = _read(delta, "id")
        if isinstance(tool_call_id, str) and tool_call_id:
            if self.tool_call_id and tool_call_id != self.tool_call_id:
                self.invalid = True
                return
            self.tool_call_id = tool_call_id

        function = _read(delta, "function", {})
        name = _read(function, "name")
        if isinstance(name, str) and name:
            if self.started:
                if name != self.name:
                    self.invalid = True
                    return
            else:
                self.name = _merge_name_fragment(self.name, name)

        arguments_marker = object()
        arguments = _read(function, "arguments", arguments_marker)
        if arguments is not arguments_marker:
            self.arguments_seen = True
        if isinstance(arguments, str) and arguments:
            self.arguments += arguments
            self.pending_argument_deltas.append(arguments)


def _merge_name_fragment(current: str, incoming: str) -> str:
    if not current:
        return incoming
    if incoming == current:
        return current
    if incoming.startswith(current):
        return incoming
    if current.endswith(incoming):
        return current
    return current + incoming


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


def _tool_call_id(delta: object) -> str | None:
    tool_call_id = _read(delta, "id")
    if isinstance(tool_call_id, str) and tool_call_id:
        return tool_call_id
    return None


def _valid_index(value: object) -> int | None:
    if type(value) is int and value >= 0:
        return value
    return None


def _complete_arguments(value: str) -> dict[str, object] | None:
    try:
        return normalize_tool_call_arguments(value)
    except LiteLLMToolCallMappingError:
        return None


def _read(value: object, key: str, default: object | None = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)
