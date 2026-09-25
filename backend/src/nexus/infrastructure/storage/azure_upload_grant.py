"""Azure User Delegation SAS implementation of the upload-grant boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from azure.core.exceptions import AzureError
from azure.storage.blob import (
    BlobSasPermissions,
    UserDelegationKey,
    generate_blob_sas,
)
from azure.storage.blob.aio import BlobServiceClient

from nexus.files.ports import UploadGrant, UploadGrantError

_UPLOAD_GRANT_FAILURE_MESSAGE = "The upload grant could not be issued."
_KEY_START_SKEW = timedelta(minutes=15)
_TARGET_KEY_LIFETIME = timedelta(hours=1)
_REFRESH_MARGIN = timedelta(minutes=5)
_MAX_KEY_LIFETIME = timedelta(days=7)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class _CachedDelegationKey:
    key: UserDelegationKey = field(repr=False)
    signed_start: datetime
    signed_expiry: datetime


class AzureUserDelegationUploadGrantIssuer:
    """Issue exact-Blob upload grants using a borrowed Azure service client."""

    def __init__(
        self,
        service_client: BlobServiceClient,
        *,
        account_name: str,
        container_name: str,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not isinstance(account_name, str) or not account_name.strip():
            raise ValueError("Azure storage account name must not be blank")
        if not isinstance(container_name, str) or not container_name.strip():
            raise ValueError("Azure storage container name must not be blank")

        self._service_client = service_client
        self._account_name = account_name
        self._container_name = container_name
        self._clock = clock
        self._cached_key: _CachedDelegationKey | None = None
        self._key_lock = asyncio.Lock()

    async def issue_upload_grant(
        self,
        *,
        storage_key: str,
        expires_at: datetime,
    ) -> UploadGrant:
        """Issue a create-only HTTPS grant for one exact Block Blob."""
        if not isinstance(storage_key, str) or not storage_key.strip():
            raise ValueError("Storage key must not be blank")

        now = self._current_time()
        self._validate_requested_expiration(expires_at=expires_at, now=now)

        delegation_key = await self._delegation_key(
            expires_at=expires_at,
            now=now,
        )
        blob_client = self._service_client.get_blob_client(
            container=self._container_name,
            blob=storage_key,
        )

        try:
            sas_token = generate_blob_sas(
                account_name=self._account_name,
                container_name=self._container_name,
                blob_name=storage_key,
                user_delegation_key=delegation_key.key,
                permission=BlobSasPermissions(create=True),
                expiry=expires_at,
                protocol="https",
            )
        except (AzureError, ValueError) as exc:
            raise UploadGrantError(_UPLOAD_GRANT_FAILURE_MESSAGE) from exc

        if not isinstance(sas_token, str) or not sas_token:
            raise UploadGrantError(_UPLOAD_GRANT_FAILURE_MESSAGE)

        return UploadGrant(
            url=f"{blob_client.url}?{sas_token}",
            method="PUT",
            headers={"x-ms-blob-type": "BlockBlob"},
            expires_at=expires_at,
        )

    def _current_time(self) -> datetime:
        now = self._clock()
        if not _is_timezone_aware(now):
            raise ValueError(
                "Upload grant clock must return a timezone-aware timestamp"
            )
        return now

    @staticmethod
    def _validate_requested_expiration(
        *,
        expires_at: datetime,
        now: datetime,
    ) -> None:
        if not _is_timezone_aware(expires_at):
            raise ValueError("Upload grant expiration must be timezone-aware")
        if expires_at <= now:
            raise ValueError("Upload grant expiration must be in the future")

        key_start = now - _KEY_START_SKEW
        maximum_key_expiry = key_start + _MAX_KEY_LIFETIME
        if expires_at > maximum_key_expiry:
            raise ValueError("Upload grant expiration exceeds the provider limit")

    async def _delegation_key(
        self,
        *,
        expires_at: datetime,
        now: datetime,
    ) -> _CachedDelegationKey:
        if self._cached_key_is_preferred(
            cached_key=self._cached_key,
            expires_at=expires_at,
            now=now,
        ):
            assert self._cached_key is not None
            return self._cached_key

        async with self._key_lock:
            current_time = self._current_time()
            self._validate_requested_expiration(
                expires_at=expires_at,
                now=current_time,
            )
            if self._cached_key_is_preferred(
                cached_key=self._cached_key,
                expires_at=expires_at,
                now=current_time,
            ):
                assert self._cached_key is not None
                return self._cached_key

            refreshed_key = await self._request_delegation_key(
                expires_at=expires_at,
                now=current_time,
            )
            self._cached_key = refreshed_key
            return refreshed_key

    async def _request_delegation_key(
        self,
        *,
        expires_at: datetime,
        now: datetime,
    ) -> _CachedDelegationKey:
        key_start = now - _KEY_START_SKEW
        maximum_key_expiry = key_start + _MAX_KEY_LIFETIME
        preferred_key_expiry = max(
            now + _TARGET_KEY_LIFETIME,
            expires_at + _REFRESH_MARGIN,
        )
        requested_key_expiry = min(preferred_key_expiry, maximum_key_expiry)

        try:
            key = await self._service_client.get_user_delegation_key(
                key_start_time=key_start,
                key_expiry_time=requested_key_expiry,
            )
        except AzureError as exc:
            raise UploadGrantError(_UPLOAD_GRANT_FAILURE_MESSAGE) from exc

        verification_time = self._current_time()
        self._validate_requested_expiration(
            expires_at=expires_at,
            now=verification_time,
        )
        signed_start = _parse_provider_timestamp(getattr(key, "signed_start", None))
        signed_expiry = _parse_provider_timestamp(getattr(key, "signed_expiry", None))
        if (
            signed_start is None
            or signed_expiry is None
            or signed_start > verification_time
            or signed_expiry <= signed_start
            or signed_expiry < expires_at
        ):
            raise UploadGrantError(_UPLOAD_GRANT_FAILURE_MESSAGE)

        return _CachedDelegationKey(
            key=key,
            signed_start=signed_start,
            signed_expiry=signed_expiry,
        )

    @staticmethod
    def _cached_key_is_preferred(
        *,
        cached_key: _CachedDelegationKey | None,
        expires_at: datetime,
        now: datetime,
    ) -> bool:
        if cached_key is None or cached_key.signed_start > now:
            return False
        return cached_key.signed_expiry >= expires_at + _REFRESH_MARGIN


def _is_timezone_aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _parse_provider_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None

    normalized = f"{value[:-1]}+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if not _is_timezone_aware(parsed):
        return None
    return parsed


__all__ = ["AzureUserDelegationUploadGrantIssuer"]
