from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from types import MappingProxyType
from typing import get_type_hints

import pytest

import nexus.files.ports as file_ports
from nexus.files.ports.upload_grant import (
    UploadGrant,
    UploadGrantError,
    UploadGrantIssuer,
)

EXPIRES_AT = datetime(2030, 1, 1, tzinfo=UTC)


def _grant(
    *,
    url: str = "https://storage.example/files/object?signature=opaque",
    method: str = "PUT",
    headers: Mapping[str, str] | None = None,
    expires_at: datetime = EXPIRES_AT,
) -> UploadGrant:
    return UploadGrant(
        url=url,
        method=method,
        headers={} if headers is None else headers,
        expires_at=expires_at,
    )


def test_upload_grant_is_frozen_and_hides_bearer_material_from_repr() -> None:
    grant = _grant(headers={"x-upload-secret": "sensitive-value"})

    with pytest.raises(FrozenInstanceError):
        grant.method = "POST"  # type: ignore[misc]

    representation = repr(grant)
    assert grant.url not in representation
    assert "sensitive-value" not in representation


def test_upload_grant_defensively_copies_and_freezes_headers() -> None:
    source = {"X-Provider-Header": " required value "}
    grant = _grant(headers=source)

    source["X-Provider-Header"] = "changed"

    assert isinstance(grant.headers, MappingProxyType)
    assert grant.headers == {"X-Provider-Header": " required value "}
    with pytest.raises(TypeError):
        grant.headers["another"] = "value"  # type: ignore[index]


def test_upload_grant_preserves_url_and_header_instructions_verbatim() -> None:
    url = "  http://127.0.0.1:10000/files/object?Sig=AbC%2B123  "
    headers = {"X-Custom-Case": " value with surrounding spaces "}

    grant = _grant(url=url, headers=headers)

    assert grant.url == url
    assert dict(grant.headers) == headers


@pytest.mark.parametrize("url", ["", " ", "\t"])
def test_upload_grant_rejects_blank_url(url: str) -> None:
    with pytest.raises(ValueError, match="URL must not be blank"):
        _grant(url=url)


def test_upload_grant_rejects_non_string_url() -> None:
    with pytest.raises(ValueError, match="URL must not be blank"):
        _grant(url=123)  # type: ignore[arg-type]


def test_upload_grant_normalizes_the_http_method() -> None:
    assert _grant(method=" put ").method == "PUT"


@pytest.mark.parametrize("method", ["", " ", "\t"])
def test_upload_grant_rejects_blank_http_method(method: str) -> None:
    with pytest.raises(ValueError, match="HTTP method must not be blank"):
        _grant(method=method)


def test_upload_grant_rejects_non_string_http_method() -> None:
    with pytest.raises(ValueError, match="HTTP method must not be blank"):
        _grant(method=123)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "headers, expected_error, message",
    [
        ({"": "value"}, ValueError, "header names must not be blank"),
        ({"  ": "value"}, ValueError, "header names must not be blank"),
        ({1: "value"}, TypeError, "headers must use string names and values"),
        ({"name": 1}, TypeError, "headers must use string names and values"),
    ],
)
def test_upload_grant_rejects_invalid_headers(
    headers: Mapping[object, object],
    expected_error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(expected_error, match=message):
        _grant(headers=headers)  # type: ignore[arg-type]


def test_upload_grant_accepts_timezone_aware_expiration() -> None:
    expires_at = datetime(2030, 1, 1, tzinfo=timezone(timedelta(hours=4)))

    assert _grant(expires_at=expires_at).expires_at is expires_at


def test_upload_grant_rejects_naive_expiration() -> None:
    with pytest.raises(ValueError, match="expiration must be timezone-aware"):
        _grant(expires_at=EXPIRES_AT.replace(tzinfo=None))


def test_upload_grant_issuer_is_an_async_keyword_only_contract() -> None:
    parameters = inspect.signature(UploadGrantIssuer.issue_upload_grant).parameters
    type_hints = get_type_hints(UploadGrantIssuer.issue_upload_grant)

    assert inspect.iscoroutinefunction(UploadGrantIssuer.issue_upload_grant)
    assert parameters["storage_key"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["expires_at"].kind is inspect.Parameter.KEYWORD_ONLY
    assert type_hints["storage_key"] is str
    assert type_hints["expires_at"] is datetime
    assert type_hints["return"] is UploadGrant


def test_file_ports_export_the_upload_grant_contract() -> None:
    assert file_ports.UploadGrant is UploadGrant
    assert file_ports.UploadGrantError is UploadGrantError
    assert file_ports.UploadGrantIssuer is UploadGrantIssuer


def test_upload_grant_error_is_provider_neutral() -> None:
    assert issubclass(UploadGrantError, Exception)
