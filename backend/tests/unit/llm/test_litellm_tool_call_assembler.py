from __future__ import annotations

from nexus.llm.domain import (
    LLMToolCallDeltaEvent,
    LLMToolCallStartedEvent,
)
from nexus.llm.infrastructure.adapters.litellm.tool_call_assembler import (
    LiteLLMToolCallAssembler,
)


def chunk(*tool_calls: dict[str, object]) -> dict[str, object]:
    return {"choices": [{"delta": {"tool_calls": list(tool_calls)}}]}


def test_indexes_keep_interleaved_calls_independent() -> None:
    assembler = LiteLLMToolCallAssembler()

    assembler.process_chunk(
        chunk(
            {
                "index": 0,
                "id": "call_1",
                "function": {"name": "search", "arguments": '{"q"'},
            },
            {
                "index": 1,
                "id": "call_2",
                "function": {"name": "lookup", "arguments": '{"id"'},
            },
        )
    )
    assembler.process_chunk(
        chunk(
            {"index": 1, "function": {"arguments": ': "42"}'}},
            {"index": 0, "function": {"arguments": ': "nexus"}'}},
        )
    )

    events = assembler.complete()

    assert [event.tool_call.id for event in events] == ["call_1", "call_2"]
    assert events[0].tool_call.arguments == {"q": "nexus"}
    assert events[1].tool_call.arguments == {"id": "42"}
    assert assembler.has_invalid_completion is False


def test_missing_index_uses_stable_id_without_merging_calls() -> None:
    assembler = LiteLLMToolCallAssembler()

    assembler.process_chunk(
        chunk(
            {
                "id": "call_1",
                "function": {"name": "search", "arguments": '{"q": "one"}'},
            },
            {
                "id": "call_2",
                "function": {"name": "search", "arguments": '{"q": "two"}'},
            },
        )
    )

    events = assembler.complete()

    assert [event.tool_call.id for event in events] == ["call_1", "call_2"]
    assert assembler.has_invalid_completion is False


def test_unidentifiable_fragment_is_invalid_instead_of_defaulting_to_zero() -> None:
    assembler = LiteLLMToolCallAssembler()

    assembler.process_chunk(
        chunk(
            {
                "index": 0,
                "id": "call_1",
                "function": {"name": "search", "arguments": "{}"},
            },
            {"function": {"arguments": '{"unexpected": true}'}},
        )
    )

    assert assembler.complete()
    assert assembler.has_invalid_completion is True


def test_invalid_index_uses_id_but_never_merges_unidentified_calls() -> None:
    assembler = LiteLLMToolCallAssembler()

    assembler.process_chunk(
        chunk(
            {
                "index": "invalid",
                "id": "call_1",
                "function": {"name": "search", "arguments": "{}"},
            }
        )
    )
    assembler.process_chunk(
        chunk({"index": "invalid", "function": {"arguments": "{}"}})
    )

    events = assembler.complete()

    assert len(events) == 1
    assert events[0].tool_call.id == "call_1"
    assert assembler.has_invalid_completion is True


def test_late_index_aliases_existing_id_state() -> None:
    assembler = LiteLLMToolCallAssembler()

    assembler.process_chunk(
        chunk(
            {
                "id": "call_1",
                "function": {"name": "search", "arguments": '{"q"'},
            }
        )
    )
    assembler.process_chunk(
        chunk(
            {
                "index": 0,
                "id": "call_1",
                "function": {"arguments": ': "nexus"}'},
            }
        )
    )

    events = assembler.complete()

    assert len(events) == 1
    assert events[0].tool_call.arguments == {"q": "nexus"}
    assert assembler.has_invalid_completion is False


def test_repeated_id_updates_the_same_call() -> None:
    assembler = LiteLLMToolCallAssembler()

    assembler.process_chunk(
        chunk(
            {
                "index": 0,
                "id": "call_1",
                "function": {"name": "search", "arguments": '{"q"'},
            }
        )
    )
    assembler.process_chunk(
        chunk(
            {
                "index": 0,
                "id": "call_1",
                "function": {"arguments": ': "nexus"}'},
            }
        )
    )

    events = assembler.complete()

    assert len(events) == 1
    assert events[0].tool_call.id == "call_1"
    assert events[0].tool_call.arguments == {"q": "nexus"}
    assert assembler.has_invalid_completion is False


def test_conflicting_id_for_index_invalidates_call() -> None:
    assembler = LiteLLMToolCallAssembler()

    assembler.process_chunk(
        chunk(
            {
                "index": 0,
                "id": "call_1",
                "function": {"name": "search", "arguments": '{"q"'},
            }
        )
    )
    assembler.process_chunk(
        chunk(
            {
                "index": 0,
                "id": "call_2",
                "function": {"arguments": ': "nexus"}'},
            }
        )
    )

    assert assembler.complete() == []
    assert assembler.has_invalid_completion is True


def test_arguments_wait_for_stable_identity_and_keep_one_public_id() -> None:
    assembler = LiteLLMToolCallAssembler()

    early_events = assembler.process_chunk(
        chunk({"index": 0, "function": {"arguments": '{"q"'}})
    )
    stable_events = assembler.process_chunk(
        chunk(
            {
                "index": 0,
                "id": "call_1",
                "function": {"name": "search", "arguments": ': "nexus"}'},
            }
        )
    )

    assert early_events == []
    assert stable_events == [
        LLMToolCallStartedEvent(tool_call_id="call_1", name="search"),
        LLMToolCallDeltaEvent(tool_call_id="call_1", arguments_delta='{"q"'),
        LLMToolCallDeltaEvent(tool_call_id="call_1", arguments_delta=': "nexus"}'),
    ]


def test_repeated_and_fragmented_names_do_not_duplicate() -> None:
    assembler = LiteLLMToolCallAssembler()

    assembler.process_chunk(
        chunk({"index": 0, "id": "call_1", "function": {"name": "sea"}})
    )
    assembler.process_chunk(chunk({"index": 0, "function": {"name": "rch"}}))
    events = assembler.process_chunk(
        chunk({"index": 0, "function": {"name": "search", "arguments": "{}"}})
    )

    assert events[0] == LLMToolCallStartedEvent(
        tool_call_id="call_1",
        name="search",
    )
    assert assembler.complete()[0].tool_call.name == "search"


def test_conflicting_name_after_started_invalidates_completion() -> None:
    assembler = LiteLLMToolCallAssembler()

    assembler.process_chunk(
        chunk(
            {
                "index": 0,
                "id": "call_1",
                "function": {"name": "search", "arguments": "{}"},
            }
        )
    )
    assembler.process_chunk(chunk({"index": 0, "function": {"name": "lookup"}}))

    assert assembler.complete() == []
    assert assembler.has_invalid_completion is True


def test_incomplete_or_malformed_arguments_are_invalid() -> None:
    incomplete = LiteLLMToolCallAssembler()
    malformed = LiteLLMToolCallAssembler()

    incomplete.process_chunk(chunk({"index": 0, "function": {"arguments": "{}"}}))
    malformed.process_chunk(
        chunk(
            {
                "index": 0,
                "id": "call_1",
                "function": {"name": "search", "arguments": '{"q"'},
            }
        )
    )

    assert incomplete.complete() == []
    assert incomplete.has_invalid_completion is True
    assert malformed.complete() == []
    assert malformed.has_invalid_completion is True


def test_assembler_state_is_not_shared_between_instances() -> None:
    first = LiteLLMToolCallAssembler()
    second = LiteLLMToolCallAssembler()

    first.process_chunk(
        chunk(
            {
                "index": 0,
                "id": "call_1",
                "function": {"name": "search", "arguments": "{}"},
            }
        )
    )

    assert len(first.complete()) == 1
    assert second.complete() == []
    assert second.has_invalid_completion is False
