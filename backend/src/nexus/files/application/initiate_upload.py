"""Authorized File upload initiation orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from nexus.authorization.permissions import PermissionChecker, PermissionCheckError
from nexus.errors import ErrorCode, NexusError
from nexus.files.application.upload_intent import (
    UploadIntentPolicy,
    UploadIntentValidationError,
)
from nexus.files.domain import File, FileStorageStatus, FileUploadAttempt
from nexus.files.ports import (
    FilePersistence,
    FilePersistenceError,
    FileReferenceError,
    UploadGrant,
    UploadGrantError,
    UploadGrantIssuer,
)

_FILES_UPLOAD_PERMISSION = "files.upload"
_FORBIDDEN_MESSAGE = "You are not allowed to perform this action."
_AUTHORIZATION_UNAVAILABLE_MESSAGE = "Authorization is temporarily unavailable."
_UPLOAD_UNAVAILABLE_MESSAGE = "The file upload could not be initiated."


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class InitiatedFileUpload:
    """The pending File and ephemeral provider instructions returned to a caller."""

    file: File
    grant: UploadGrant


@dataclass(frozen=True)
class InitiateFileUpload:
    """Authorize, prepare, delegate, and persist one new File upload."""

    intent_policy: UploadIntentPolicy
    permission_checker: PermissionChecker
    persistence: FilePersistence
    upload_grant_issuer: UploadGrantIssuer
    grant_ttl: timedelta
    clock: Callable[[], datetime] = _utc_now

    def __post_init__(self) -> None:
        if not isinstance(self.grant_ttl, timedelta):
            raise TypeError("grant_ttl must be a positive timedelta")
        if self.grant_ttl <= timedelta(0):
            raise ValueError("grant_ttl must be a positive timedelta")

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        original_name: str,
        mime_type: str | None,
        declared_size_bytes: int,
    ) -> InitiatedFileUpload:
        """Initiate one authorized direct upload without holding an I/O transaction."""

        await self._authorize(
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
        )

        try:
            intent = self.intent_policy.prepare(
                original_name=original_name,
                mime_type=mime_type,
                size_bytes=declared_size_bytes,
            )
        except UploadIntentValidationError as exc:
            raise NexusError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc

        requested_at = self._current_time()
        requested_expiration = requested_at + self.grant_ttl
        try:
            grant = await self.upload_grant_issuer.issue_upload_grant(
                storage_key=intent.storage_key,
                expires_at=requested_expiration,
            )
        except UploadGrantError as exc:
            raise _upload_unavailable() from exc

        created_at = self._current_time()
        if (
            not _is_timezone_aware(grant.expires_at)
            or grant.expires_at <= created_at
            or grant.expires_at > requested_expiration
        ):
            raise _upload_unavailable()

        file = File(
            public_id=uuid4(),
            organization_public_id=organization_public_id,
            created_by_user_public_id=user_public_id,
            original_name=intent.original_name,
            mime_type=intent.mime_type,
            size_bytes=None,
            storage_key=intent.storage_key,
            storage_status=FileStorageStatus.PENDING,
            checksum_sha256=None,
            created_at=created_at,
            updated_at=created_at,
        )
        upload_attempt = FileUploadAttempt(
            file_public_id=file.public_id,
            organization_public_id=file.organization_public_id,
            declared_size_bytes=intent.declared_size_bytes,
            grant_expires_at=grant.expires_at,
            created_at=created_at,
        )

        try:
            await self.persistence.create_pending_upload(
                file=file,
                upload_attempt=upload_attempt,
            )
        except (FilePersistenceError, FileReferenceError) as exc:
            raise _upload_unavailable() from exc

        return InitiatedFileUpload(file=file, grant=grant)

    async def _authorize(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
    ) -> None:
        try:
            allowed = await self.permission_checker.has_permission(
                organization_public_id=organization_public_id,
                user_public_id=user_public_id,
                permission_key=_FILES_UPLOAD_PERMISSION,
            )
        except PermissionCheckError as exc:
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                _AUTHORIZATION_UNAVAILABLE_MESSAGE,
                retryable=True,
            ) from exc

        if not allowed:
            raise NexusError(ErrorCode.FORBIDDEN, _FORBIDDEN_MESSAGE)

    def _current_time(self) -> datetime:
        now = self.clock()
        if not _is_timezone_aware(now):
            raise ValueError("Upload initiation clock must be timezone-aware")
        return now


def _is_timezone_aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _upload_unavailable() -> NexusError:
    return NexusError(
        ErrorCode.SERVICE_UNAVAILABLE,
        _UPLOAD_UNAVAILABLE_MESSAGE,
        retryable=True,
    )


__all__ = ["InitiateFileUpload", "InitiatedFileUpload"]
