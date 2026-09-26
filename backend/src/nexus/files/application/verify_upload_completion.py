"""Verify one committed File object and register its trusted identity."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from nexus.files.domain import File, FileStorageStatus
from nexus.files.ports import (
    FileIdentityConflictError,
    FilePersistence,
    FileReferenceError,
    ObjectStorage,
    ObjectStorageNotFoundError,
    UploadCompletionEvent,
    UploadCompletionRejectedError,
    UploadCompletionRejectionReason,
    UploadContextProtectionError,
    UploadContextProtector,
)
from nexus.logging import get_logger

_UPLOAD_CONTEXT_METADATA_KEY = "nexus_upload_context"
_SAFE_CORRELATION_LENGTH = 16

logger = get_logger(__name__)

type Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class VerifyUploadCompletion:
    """Verify external facts first, then register one File atomically."""

    object_storage: ObjectStorage
    context_protector: UploadContextProtector
    persistence: FilePersistence
    max_size_bytes: int
    clock: Clock = _utc_now

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_size_bytes, bool)
            or not isinstance(self.max_size_bytes, int)
            or self.max_size_bytes <= 0
        ):
            raise ValueError("max_size_bytes must be a positive integer")

    async def handle(self, event: UploadCompletionEvent) -> None:
        correlation = _safe_event_correlation(event)
        try:
            properties = await self.object_storage.get_object_properties(
                storage_key=event.storage_key
            )
        except ObjectStorageNotFoundError:
            logger.info(
                "file_upload_completion_blob_missing",
                correlation=correlation,
            )
            return

        if properties.entity_tag != event.entity_tag:
            logger.info(
                "file_upload_completion_stale_entity_tag",
                correlation=correlation,
            )
            return

        protected_context = properties.metadata.get(_UPLOAD_CONTEXT_METADATA_KEY)
        if not protected_context:
            raise UploadCompletionRejectedError(
                UploadCompletionRejectionReason.MISSING_UPLOAD_CONTEXT
            )

        try:
            context = self.context_protector.unprotect(protected_context)
        except UploadContextProtectionError as exc:
            raise UploadCompletionRejectedError(
                UploadCompletionRejectionReason.INVALID_UPLOAD_CONTEXT
            ) from exc

        if context.storage_key != event.storage_key:
            raise UploadCompletionRejectedError(
                UploadCompletionRejectionReason.STORAGE_KEY_MISMATCH
            )
        if not (
            properties.size_bytes
            == context.declared_size_bytes
            == event.reported_size_bytes
        ):
            raise UploadCompletionRejectedError(
                UploadCompletionRejectionReason.SIZE_MISMATCH
            )
        if properties.size_bytes > self.max_size_bytes:
            raise UploadCompletionRejectedError(
                UploadCompletionRejectionReason.SIZE_LIMIT_EXCEEDED
            )

        now = self.clock()
        file = File(
            public_id=context.file_public_id,
            organization_public_id=context.organization_public_id,
            created_by_user_public_id=context.created_by_user_public_id,
            original_name=context.original_name,
            mime_type=context.mime_type,
            size_bytes=properties.size_bytes,
            storage_key=context.storage_key,
            storage_status=FileStorageStatus.PENDING,
            checksum_sha256=None,
            created_at=now,
            updated_at=now,
        )
        try:
            await self.persistence.register_completed_upload(file)
        except FileReferenceError as exc:
            raise UploadCompletionRejectedError(
                UploadCompletionRejectionReason.INVALID_OWNER
            ) from exc
        except FileIdentityConflictError as exc:
            raise UploadCompletionRejectedError(
                UploadCompletionRejectionReason.FILE_IDENTITY_CONFLICT
            ) from exc


def _safe_event_correlation(event: UploadCompletionEvent) -> str:
    value = f"{event.source}:{event.event_id}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_SAFE_CORRELATION_LENGTH]


__all__ = ["VerifyUploadCompletion"]
