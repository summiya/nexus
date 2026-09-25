"""Tests use sanitized documentation-derived, not production-captured, fixtures."""

from __future__ import annotations

import ast
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from nexus.infrastructure.storage import (
    AzureBlobCreatedEventMapper,
    AzureBlobCreatedEventMappingError,
    azure_blob_created,
)

TESTS_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = TESTS_ROOT / "fixtures" / "storage" / "azure_blob_created_events.json"
MAPPER_PATH = (
    TESTS_ROOT.parent
    / "src"
    / "nexus"
    / "infrastructure"
    / "storage"
    / "azure_blob_created.py"
)
AZURE_SOURCE = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/nexus-test/providers/Microsoft.Storage/storageAccounts/nexustest"
)
SAFE_ERROR = "Azure BlobCreated event is invalid."
CANONICAL_SUBJECT = (
    "/blobServices/default/containers/nexus-files/blobs/"
    "files/0123456789abcdef0123456789abcdef"
)


def _fixtures() -> list[dict[str, object]]:
    return cast(
        list[dict[str, object]],
        json.loads(FIXTURE_PATH.read_text(encoding="utf-8")),
    )


def _event(index: int = 0) -> dict[str, object]:
    return deepcopy(_fixtures()[index])


def _data(event: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], event["data"])


def _mapper() -> AzureBlobCreatedEventMapper:
    return AzureBlobCreatedEventMapper(
        expected_source=AZURE_SOURCE,
        expected_container="nexus-files",
        nexus_source="azure-primary",
    )


@pytest.mark.parametrize(
    ("fixture_index", "storage_key", "event_id", "entity_tag", "size"),
    [
        (
            0,
            "files/0123456789abcdef0123456789abcdef",
            "put-blob-event",
            "0x8D4BCC2E4835CD0",
            1024,
        ),
        (
            1,
            "files/fedcba9876543210fedcba9876543210",
            "put-block-list-event",
            "0x8D4BCC2E4835CD1",
            52428800,
        ),
    ],
)
def test_maps_supported_blob_created_events(
    fixture_index: int,
    storage_key: str,
    event_id: str,
    entity_tag: str,
    size: int,
) -> None:
    mapped = _mapper().map_event(_event(fixture_index))

    assert mapped.event_id == event_id
    assert mapped.source == "azure-primary"
    assert mapped.storage_key == storage_key
    assert mapped.entity_tag == entity_tag
    assert mapped.reported_size_bytes == size
    assert not hasattr(mapped, "reported_content_type")


def test_accepts_documented_seven_digit_azure_timestamp() -> None:
    mapped = _mapper().map_event(_event())

    assert mapped.occurred_at == datetime(
        2017,
        6,
        26,
        18,
        41,
        0,
        958410,
        tzinfo=UTC,
    )


def test_mapping_is_independent_of_json_property_order() -> None:
    event = _event()
    reordered = dict(reversed(tuple(event.items())))
    reordered["data"] = dict(reversed(tuple(_data(event).items())))

    assert _mapper().map_event(reordered) == _mapper().map_event(event)


def test_data_url_is_ignored_for_identity_and_mapping() -> None:
    event = _event()
    _data(event)["url"] = "javascript:alert('untrusted')"

    mapped = _mapper().map_event(event)

    assert mapped.storage_key == "files/0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("specversion", "0.3"),
        ("type", "Microsoft.Storage.BlobDeleted"),
        ("source", "/subscriptions/other/storageAccounts/other"),
        ("id", ""),
        ("id", "a" * 1025),
        ("time", "not-a-time"),
        ("time", "2017-06-26T18:41:00.9584103"),
        ("subject", "/malformed"),
        (
            "subject",
            CANONICAL_SUBJECT.replace("nexus-files", "other"),
        ),
        (
            "subject",
            f"{CANONICAL_SUBJECT[:-1]}F",
        ),
        (
            "subject",
            f"{CANONICAL_SUBJECT}\n",
        ),
    ],
)
def test_rejects_invalid_cloud_event_fields(field: str, value: object) -> None:
    event = _event()
    event[field] = value

    with pytest.raises(AzureBlobCreatedEventMappingError, match=SAFE_ERROR):
        _mapper().map_event(event)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api", "PutBlock"),
        ("api", "DeleteBlob"),
        ("api", []),
        ("api", {}),
        ("blobType", "AppendBlob"),
        ("blobType", "PageBlob"),
        ("blobType", []),
        ("blobType", {}),
        ("eTag", ""),
        ("eTag", "a" * 1025),
        ("contentLength", -1),
        ("contentLength", True),
        ("contentLength", 1.5),
        ("contentLength", "1"),
    ],
)
def test_rejects_invalid_blob_data_fields(field: str, value: object) -> None:
    event = _event()
    _data(event)[field] = value

    with pytest.raises(AzureBlobCreatedEventMappingError, match=SAFE_ERROR):
        _mapper().map_event(event)


@pytest.mark.parametrize("missing_field", ["id", "time", "subject", "data"])
def test_rejects_missing_required_event_fields(missing_field: str) -> None:
    event = _event()
    del event[missing_field]

    with pytest.raises(AzureBlobCreatedEventMappingError, match=SAFE_ERROR):
        _mapper().map_event(event)


def test_zero_byte_object_is_valid() -> None:
    event = _event()
    _data(event)["contentLength"] = 0

    assert _mapper().map_event(event).reported_size_bytes == 0


def test_mapping_error_does_not_expose_payload_value() -> None:
    event = _event()
    sensitive_value = "untrusted-sensitive-provider-value"
    event["time"] = sensitive_value

    with pytest.raises(AzureBlobCreatedEventMappingError) as caught:
        _mapper().map_event(event)

    assert str(caught.value) == SAFE_ERROR
    assert sensitive_value not in str(caught.value)


@pytest.mark.parametrize("domain_error", [TypeError("unsafe"), ValueError("unsafe")])
def test_domain_construction_errors_use_single_safe_mapper_error(
    monkeypatch: pytest.MonkeyPatch,
    domain_error: Exception,
) -> None:
    def reject_event(**_values: object) -> None:
        raise domain_error

    monkeypatch.setattr(azure_blob_created, "UploadCompletionEvent", reject_event)

    with pytest.raises(AzureBlobCreatedEventMappingError) as caught:
        _mapper().map_event(_event())

    assert str(caught.value) == SAFE_ERROR
    assert caught.value.__cause__ is None


def test_mapper_contains_no_azure_sdk_or_duplicate_key_regex() -> None:
    tree = ast.parse(MAPPER_PATH.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert not any(
        module == "azure" or module.startswith("azure.") for module in imported_modules
    )
    assert "re" not in imported_modules
    assert "nexus.files.domain" in imported_modules
