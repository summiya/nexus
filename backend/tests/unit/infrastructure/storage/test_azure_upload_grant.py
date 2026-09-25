from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast
from urllib.parse import parse_qs, urlsplit

import pytest
from azure.core.exceptions import AzureError
from azure.storage.blob import BlobSasPermissions, UserDelegationKey
from azure.storage.blob.aio import BlobServiceClient

import nexus.infrastructure.storage as storage_infrastructure
from nexus.files.ports import UploadGrantError
from nexus.infrastructure.storage import azure_upload_grant
from nexus.infrastructure.storage.azure_upload_grant import (
    AzureUserDelegationUploadGrantIssuer,
)

NOW = datetime(2030, 1, 1, 12, tzinfo=UTC)
REQUESTED_EXPIRY = NOW + timedelta(minutes=10)
SAFE_ERROR = "The upload grant could not be issued."


@dataclass
class FakeDelegationKey:
    signed_start: object
    signed_expiry: object


class FakeBlobClient:
    def __init__(self, url: str) -> None:
        self.url = url


class FakeBlobServiceClient:
    def __init__(
        self,
        *delegation_keys: FakeDelegationKey,
        blob_url: str = "https://private.example/custom/blob%20path",
    ) -> None:
        self.delegation_keys = list(delegation_keys) or [_delegation_key()]
        self.blob_url = blob_url
        self.key_calls: list[dict[str, datetime]] = []
        self.blob_calls: list[dict[str, str]] = []
        self.key_error: BaseException | None = None
        self.key_request_started = asyncio.Event()
        self.release_key_request: asyncio.Event | None = None
        self.close_calls = 0

    async def get_user_delegation_key(
        self,
        *,
        key_start_time: datetime,
        key_expiry_time: datetime,
    ) -> UserDelegationKey:
        self.key_calls.append(
            {
                "key_start_time": key_start_time,
                "key_expiry_time": key_expiry_time,
            }
        )
        self.key_request_started.set()
        if self.release_key_request is not None:
            await self.release_key_request.wait()
        if self.key_error is not None:
            raise self.key_error
        index = len(self.key_calls) - 1
        return cast(UserDelegationKey, self.delegation_keys[index])

    def get_blob_client(self, *, container: str, blob: str) -> FakeBlobClient:
        self.blob_calls.append({"container": container, "blob": blob})
        return FakeBlobClient(self.blob_url)

    async def close(self) -> None:
        self.close_calls += 1


def _timestamp(value: datetime) -> str:
    return value.isoformat()


def _delegation_key(
    *,
    signed_start: object | None = None,
    signed_expiry: object | None = None,
) -> FakeDelegationKey:
    return FakeDelegationKey(
        signed_start=(
            _timestamp(NOW - timedelta(minutes=15))
            if signed_start is None
            else signed_start
        ),
        signed_expiry=(
            _timestamp(NOW + timedelta(hours=1))
            if signed_expiry is None
            else signed_expiry
        ),
    )


def _real_delegation_key() -> UserDelegationKey:
    key = UserDelegationKey()
    key.signed_oid = "11111111-1111-4111-8111-111111111111"
    key.signed_tid = "22222222-2222-4222-8222-222222222222"
    key.signed_start = _timestamp(NOW - timedelta(minutes=15))
    key.signed_expiry = _timestamp(NOW + timedelta(hours=1))
    key.signed_service = "b"
    key.signed_version = "2026-04-06"
    key.value = base64.b64encode(b"nexus-test-signing-key-material").decode()
    return key


def _issuer(
    client: FakeBlobServiceClient,
    *,
    clock: Callable[[], datetime] = lambda: NOW,
) -> AzureUserDelegationUploadGrantIssuer:
    return AzureUserDelegationUploadGrantIssuer(
        cast(BlobServiceClient, client),
        account_name="nexusaccount",
        container_name="files-container",
        clock=clock,
    )


def _install_signer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    error: BaseException | None = None,
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_generate_blob_sas(**kwargs: object) -> str:
        calls.append(kwargs)
        if error is not None:
            raise error
        return "sv=2030-01-01&sig=REDACTED"

    monkeypatch.setattr(
        azure_upload_grant,
        "generate_blob_sas",
        fake_generate_blob_sas,
    )
    return calls


@pytest.mark.parametrize(
    ("account_name", "container_name"),
    [
        ("", "files"),
        ("   ", "files"),
        (123, "files"),
        ("account", ""),
        ("account", "\t"),
        ("account", 123),
    ],
)
def test_constructor_rejects_blank_or_non_string_names(
    account_name: object,
    container_name: object,
) -> None:
    client = FakeBlobServiceClient()

    with pytest.raises(ValueError):
        AzureUserDelegationUploadGrantIssuer(
            cast(BlobServiceClient, client),
            account_name=account_name,  # type: ignore[arg-type]
            container_name=container_name,  # type: ignore[arg-type]
            clock=lambda: NOW,
        )


@pytest.mark.parametrize("storage_key", ["", "   ", 123])
def test_rejects_blank_or_non_string_storage_key_before_provider_io(
    storage_key: object,
) -> None:
    async def scenario() -> None:
        client = FakeBlobServiceClient()

        with pytest.raises(ValueError, match="Storage key must not be blank"):
            await _issuer(client).issue_upload_grant(
                storage_key=storage_key,  # type: ignore[arg-type]
                expires_at=REQUESTED_EXPIRY,
            )

        assert client.key_calls == []
        assert client.blob_calls == []

    asyncio.run(scenario())


def test_issues_exact_blob_scoped_create_only_https_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        blob_url = "https://private.example/base/container/blob%20value"
        client = FakeBlobServiceClient(blob_url=blob_url)
        signer_calls = _install_signer(monkeypatch)
        issuer = _issuer(client)
        storage_key = "files/opaque value/%2F"

        grant = await issuer.issue_upload_grant(
            storage_key=storage_key,
            expires_at=REQUESTED_EXPIRY,
        )

        assert client.blob_calls == [
            {"container": "files-container", "blob": storage_key}
        ]
        assert grant.url == f"{blob_url}?sv=2030-01-01&sig=REDACTED"
        assert grant.method == "PUT"
        assert grant.headers == {"x-ms-blob-type": "BlockBlob"}
        assert grant.expires_at is REQUESTED_EXPIRY
        assert client.close_calls == 0

        assert len(signer_calls) == 1
        signer_call = signer_calls[0]
        assert signer_call["account_name"] == "nexusaccount"
        assert signer_call["container_name"] == "files-container"
        assert signer_call["blob_name"] == storage_key
        assert signer_call["expiry"] is REQUESTED_EXPIRY
        assert signer_call["protocol"] == "https"
        assert "start" not in signer_call
        assert "account_key" not in signer_call

        permission = cast(BlobSasPermissions, signer_call["permission"])
        assert permission.create is True
        assert permission.write is False
        assert permission.read is False
        assert permission.delete is False
        assert permission.add is False
        assert permission.tag is False

    asyncio.run(scenario())


def test_real_sdk_emits_create_only_sas_with_compatible_service_version() -> None:
    async def scenario() -> None:
        client = FakeBlobServiceClient(cast(FakeDelegationKey, _real_delegation_key()))

        grant = await _issuer(client).issue_upload_grant(
            storage_key="files/0123456789abcdef0123456789abcdef",
            expires_at=REQUESTED_EXPIRY,
        )

        query = parse_qs(urlsplit(grant.url).query, keep_blank_values=True)
        assert query["sp"] == ["c"]
        assert "w" not in query["sp"][0]
        assert query["spr"] == ["https"]
        assert query["sr"] == ["b"]
        assert date.fromisoformat(query["sv"][0]) >= date(2026, 4, 6)
        assert query["sig"][0]
        assert "st" not in query

    asyncio.run(scenario())


def test_requests_short_skewed_key_lifetime_covering_the_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        client = FakeBlobServiceClient()
        _install_signer(monkeypatch)

        await _issuer(client).issue_upload_grant(
            storage_key="opaque-key",
            expires_at=REQUESTED_EXPIRY,
        )

        assert client.key_calls == [
            {
                "key_start_time": NOW - timedelta(minutes=15),
                "key_expiry_time": NOW + timedelta(hours=1),
            }
        ]
        assert client.key_calls[0]["key_expiry_time"] >= REQUESTED_EXPIRY

    asyncio.run(scenario())


def test_cache_reuses_a_key_with_sufficient_refresh_margin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        client = FakeBlobServiceClient(
            _delegation_key(signed_expiry=_timestamp(NOW + timedelta(hours=1)))
        )
        signer_calls = _install_signer(monkeypatch)
        issuer = _issuer(client)

        await issuer.issue_upload_grant(
            storage_key="first-key",
            expires_at=NOW + timedelta(minutes=10),
        )
        await issuer.issue_upload_grant(
            storage_key="second-key",
            expires_at=NOW + timedelta(minutes=20),
        )

        assert len(client.key_calls) == 1
        assert len(signer_calls) == 2

    asyncio.run(scenario())


def test_cache_refreshes_when_requested_expiry_exceeds_cached_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        client = FakeBlobServiceClient(
            _delegation_key(signed_expiry=_timestamp(NOW + timedelta(minutes=30))),
            _delegation_key(signed_expiry=_timestamp(NOW + timedelta(hours=2))),
        )
        _install_signer(monkeypatch)
        issuer = _issuer(client)

        await issuer.issue_upload_grant(
            storage_key="first-key",
            expires_at=NOW + timedelta(minutes=10),
        )
        await issuer.issue_upload_grant(
            storage_key="second-key",
            expires_at=NOW + timedelta(minutes=45),
        )

        assert len(client.key_calls) == 2

    asyncio.run(scenario())


def test_cache_refreshes_when_key_covers_grant_but_not_refresh_margin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        client = FakeBlobServiceClient(
            _delegation_key(signed_expiry=_timestamp(NOW + timedelta(minutes=30))),
            _delegation_key(signed_expiry=_timestamp(NOW + timedelta(hours=1))),
        )
        _install_signer(monkeypatch)
        issuer = _issuer(client)

        await issuer.issue_upload_grant(
            storage_key="first-key",
            expires_at=NOW + timedelta(minutes=10),
        )
        await issuer.issue_upload_grant(
            storage_key="second-key",
            expires_at=NOW + timedelta(minutes=27),
        )

        assert len(client.key_calls) == 2

    asyncio.run(scenario())


def test_fresh_key_that_covers_current_grant_without_margin_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        requested_expiry = NOW + timedelta(minutes=30)
        client = FakeBlobServiceClient(
            _delegation_key(signed_expiry=_timestamp(requested_expiry))
        )
        _install_signer(monkeypatch)

        grant = await _issuer(client).issue_upload_grant(
            storage_key="opaque-key",
            expires_at=requested_expiry,
        )

        assert grant.expires_at is requested_expiry
        assert len(client.key_calls) == 1

    asyncio.run(scenario())


def test_refresh_margin_does_not_reject_provider_valid_grant_near_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        key_start = NOW - timedelta(minutes=15)
        maximum_key_expiry = key_start + timedelta(days=7)
        requested_expiry = maximum_key_expiry - timedelta(minutes=2)
        client = FakeBlobServiceClient(
            _delegation_key(
                signed_start=_timestamp(key_start),
                signed_expiry=_timestamp(maximum_key_expiry),
            )
        )
        _install_signer(monkeypatch)

        grant = await _issuer(client).issue_upload_grant(
            storage_key="opaque-key",
            expires_at=requested_expiry,
        )

        assert grant.expires_at is requested_expiry
        assert client.key_calls[0]["key_expiry_time"] == maximum_key_expiry

    asyncio.run(scenario())


def test_requested_grant_beyond_provider_maximum_is_rejected_before_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        client = FakeBlobServiceClient()
        signer_calls = _install_signer(monkeypatch)
        maximum_key_expiry = NOW - timedelta(minutes=15) + timedelta(days=7)

        with pytest.raises(ValueError):
            await _issuer(client).issue_upload_grant(
                storage_key="opaque-key",
                expires_at=maximum_key_expiry + timedelta(microseconds=1),
            )

        assert client.key_calls == []
        assert client.blob_calls == []
        assert signer_calls == []

    asyncio.run(scenario())


def test_concurrent_first_use_acquires_one_delegation_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        client = FakeBlobServiceClient()
        client.release_key_request = asyncio.Event()
        signer_calls = _install_signer(monkeypatch)
        issuer = _issuer(client)
        tasks = [
            asyncio.create_task(
                issuer.issue_upload_grant(
                    storage_key=f"key-{index}",
                    expires_at=REQUESTED_EXPIRY,
                )
            )
            for index in range(10)
        ]

        await client.key_request_started.wait()
        await asyncio.sleep(0)
        assert len(client.key_calls) == 1

        client.release_key_request.set()
        grants = await asyncio.gather(*tasks)

        assert len(client.key_calls) == 1
        assert len(signer_calls) == 10
        assert len({grant.url for grant in grants}) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "expires_at",
    [
        NOW.replace(tzinfo=None),
        NOW,
        NOW - timedelta(microseconds=1),
    ],
)
def test_invalid_requested_expiration_is_rejected_before_provider_io(
    monkeypatch: pytest.MonkeyPatch,
    expires_at: datetime,
) -> None:
    async def scenario() -> None:
        client = FakeBlobServiceClient()
        signer_calls = _install_signer(monkeypatch)

        with pytest.raises(ValueError):
            await _issuer(client).issue_upload_grant(
                storage_key="opaque-key",
                expires_at=expires_at,
            )

        assert client.key_calls == []
        assert signer_calls == []

    asyncio.run(scenario())


def test_naive_clock_is_rejected_before_provider_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        client = FakeBlobServiceClient()
        signer_calls = _install_signer(monkeypatch)

        with pytest.raises(ValueError):
            await _issuer(
                client, clock=lambda: NOW.replace(tzinfo=None)
            ).issue_upload_grant(
                storage_key="opaque-key",
                expires_at=REQUESTED_EXPIRY,
            )

        assert client.key_calls == []
        assert signer_calls == []

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("signed_start", "signed_expiry"),
    [
        (None, _timestamp(NOW + timedelta(hours=1))),
        ("not-a-timestamp", _timestamp(NOW + timedelta(hours=1))),
        (
            _timestamp(NOW - timedelta(minutes=15)).removesuffix("+00:00"),
            _timestamp(NOW + timedelta(hours=1)),
        ),
        (_timestamp(NOW + timedelta(seconds=1)), _timestamp(NOW + timedelta(hours=1))),
        (_timestamp(NOW - timedelta(minutes=15)), None),
        (_timestamp(NOW - timedelta(minutes=15)), "not-a-timestamp"),
        (
            _timestamp(NOW - timedelta(minutes=15)),
            _timestamp(NOW + timedelta(hours=1)).removesuffix("+00:00"),
        ),
        (
            _timestamp(NOW - timedelta(minutes=15)),
            _timestamp(NOW - timedelta(minutes=15)),
        ),
        (
            _timestamp(NOW - timedelta(minutes=15)),
            _timestamp(REQUESTED_EXPIRY - timedelta(microseconds=1)),
        ),
    ],
    ids=[
        "missing-start",
        "malformed-start",
        "naive-start",
        "future-start",
        "missing-expiry",
        "malformed-expiry",
        "naive-expiry",
        "expiry-not-after-start",
        "expiry-before-grant",
    ],
)
def test_unusable_authoritative_key_lifetime_is_rejected_safely(
    monkeypatch: pytest.MonkeyPatch,
    signed_start: object,
    signed_expiry: object,
) -> None:
    async def scenario() -> None:
        client = FakeBlobServiceClient(
            FakeDelegationKey(
                signed_start=signed_start,
                signed_expiry=signed_expiry,
            )
        )
        signer_calls = _install_signer(monkeypatch)

        with pytest.raises(UploadGrantError, match=f"^{SAFE_ERROR}$") as captured:
            await _issuer(client).issue_upload_grant(
                storage_key="opaque-key",
                expires_at=REQUESTED_EXPIRY,
            )

        assert str(signed_start) not in str(captured.value)
        assert str(signed_expiry) not in str(captured.value)
        assert signer_calls == []

    asyncio.run(scenario())


def test_authoritative_key_start_equal_to_current_time_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        client = FakeBlobServiceClient(
            _delegation_key(
                signed_start=_timestamp(NOW),
                signed_expiry=_timestamp(NOW + timedelta(hours=1)),
            )
        )
        _install_signer(monkeypatch)

        grant = await _issuer(client).issue_upload_grant(
            storage_key="opaque-key",
            expires_at=REQUESTED_EXPIRY,
        )

        assert grant.expires_at is REQUESTED_EXPIRY

    asyncio.run(scenario())


def test_returned_key_lifetime_is_checked_against_time_after_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        times = iter([NOW, NOW, NOW + timedelta(minutes=1)])
        client = FakeBlobServiceClient(
            _delegation_key(
                signed_start=_timestamp(NOW + timedelta(seconds=30)),
                signed_expiry=_timestamp(NOW + timedelta(hours=1)),
            )
        )
        _install_signer(monkeypatch)

        grant = await _issuer(client, clock=lambda: next(times)).issue_upload_grant(
            storage_key="opaque-key",
            expires_at=REQUESTED_EXPIRY,
        )

        assert grant.expires_at is REQUESTED_EXPIRY

    asyncio.run(scenario())


def test_delegation_key_provider_error_becomes_safe_upload_grant_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        provider_error = AzureError("provider credential detail")
        client = FakeBlobServiceClient()
        client.key_error = provider_error
        _install_signer(monkeypatch)

        with pytest.raises(UploadGrantError, match=f"^{SAFE_ERROR}$") as captured:
            await _issuer(client).issue_upload_grant(
                storage_key="opaque-key",
                expires_at=REQUESTED_EXPIRY,
            )

        assert "provider credential detail" not in str(captured.value)
        assert captured.value.__cause__ is provider_error

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "provider_error",
    [AzureError("signing detail"), ValueError("invalid signing material")],
)
def test_signing_provider_failure_becomes_safe_upload_grant_error(
    monkeypatch: pytest.MonkeyPatch,
    provider_error: Exception,
) -> None:
    async def scenario() -> None:
        client = FakeBlobServiceClient()
        _install_signer(monkeypatch, error=provider_error)

        with pytest.raises(UploadGrantError, match=f"^{SAFE_ERROR}$") as captured:
            await _issuer(client).issue_upload_grant(
                storage_key="opaque-key",
                expires_at=REQUESTED_EXPIRY,
            )

        assert str(provider_error) not in str(captured.value)
        assert captured.value.__cause__ is provider_error

    asyncio.run(scenario())


def test_cancellation_during_key_acquisition_remains_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        client = FakeBlobServiceClient()
        client.key_error = asyncio.CancelledError()
        _install_signer(monkeypatch)

        with pytest.raises(asyncio.CancelledError):
            await _issuer(client).issue_upload_grant(
                storage_key="opaque-key",
                expires_at=REQUESTED_EXPIRY,
            )

    asyncio.run(scenario())


def test_infrastructure_package_exports_the_azure_issuer() -> None:
    assert (
        storage_infrastructure.AzureUserDelegationUploadGrantIssuer
        is AzureUserDelegationUploadGrantIssuer
    )
