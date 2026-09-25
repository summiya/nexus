from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime

import pytest

import nexus.files.ports as file_ports
from nexus.files.ports import UploadCompletionEvent

TIMESTAMP = datetime(2026, 9, 25, tzinfo=UTC)


def _event(**changes: object) -> UploadCompletionEvent:
    values: dict[str, object] = {
        "event_id": "event-1",
        "source": "azure-primary",
        "storage_key": "files/0123456789abcdef0123456789abcdef",
        "occurred_at": TIMESTAMP,
        "entity_tag": '"0x8D123"',
        "reported_size_bytes": 42,
    }
    values.update(changes)
    return UploadCompletionEvent(**values)  # type: ignore[arg-type]


def test_upload_completion_event_has_exact_provider_neutral_contract() -> None:
    event = _event()

    assert [field.name for field in fields(event)] == [
        "event_id",
        "source",
        "storage_key",
        "occurred_at",
        "entity_tag",
        "reported_size_bytes",
    ]
    assert not hasattr(event, "reported_content_type")
    assert file_ports.UploadCompletionEvent is UploadCompletionEvent


def test_upload_completion_event_is_immutable_and_hides_values_from_repr() -> None:
    event = _event()

    with pytest.raises(FrozenInstanceError):
        event.event_id = "changed"  # type: ignore[misc]

    representation = repr(event)
    assert "event-1" not in representation
    assert "files/" not in representation
    assert "0x8D123" not in representation


def test_upload_completion_event_accepts_canonical_storage_key() -> None:
    storage_key = "files/0123456789abcdef0123456789abcdef"

    assert _event(storage_key=storage_key).storage_key == storage_key


@pytest.mark.parametrize(
    "storage_key",
    [
        "files/0123456789abcdef0123456789abcde",
        "files/0123456789abcdef0123456789abcdef0",
        "files/0123456789ABCDEF0123456789ABCDEF",
        "files/0123456789abcdef0123456789abcdef\n",
        "uploads/0123456789abcdef0123456789abcdef",
        "arbitrary/path",
    ],
)
def test_upload_completion_event_rejects_noncanonical_storage_key(
    storage_key: str,
) -> None:
    with pytest.raises(ValueError, match="^storage_key is invalid$"):
        _event(storage_key=storage_key)


@pytest.mark.parametrize(
    ("field_name", "value", "error_type"),
    [
        ("event_id", 1, TypeError),
        ("event_id", " ", ValueError),
        ("event_id", "a" * 1025, ValueError),
        ("source", 1, TypeError),
        ("source", "", ValueError),
        ("source", "a" * 1025, ValueError),
        ("storage_key", 1, TypeError),
        ("storage_key", "\t", ValueError),
        ("storage_key", "a" * 1025, ValueError),
        ("entity_tag", 1, TypeError),
        ("entity_tag", "", ValueError),
        ("entity_tag", "a" * 1025, ValueError),
    ],
)
def test_upload_completion_event_rejects_invalid_bounded_text(
    field_name: str,
    value: object,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        _event(**{field_name: value})


@pytest.mark.parametrize(
    "occurred_at",
    ["2026-09-25T00:00:00Z", TIMESTAMP.replace(tzinfo=None)],
)
def test_upload_completion_event_requires_aware_datetime(
    occurred_at: object,
) -> None:
    with pytest.raises(ValueError, match="occurred_at must be timezone-aware"):
        _event(occurred_at=occurred_at)


@pytest.mark.parametrize("reported_size_bytes", [True, 1.5, "1"])
def test_upload_completion_event_rejects_non_integer_size(
    reported_size_bytes: object,
) -> None:
    with pytest.raises(TypeError, match="reported_size_bytes must be an integer"):
        _event(reported_size_bytes=reported_size_bytes)


def test_upload_completion_event_rejects_negative_size() -> None:
    with pytest.raises(
        ValueError,
        match="reported_size_bytes must not be negative",
    ):
        _event(reported_size_bytes=-1)


def test_upload_completion_event_allows_zero_byte_object() -> None:
    assert _event(reported_size_bytes=0).reported_size_bytes == 0
