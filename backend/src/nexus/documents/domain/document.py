"""Document processing identity and lifecycle."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

_MAX_VERSION_LENGTH = 128
_MAX_FAILURE_CODE_LENGTH = 64
_MAX_SAFE_FAILURE_MESSAGE_LENGTH = 512
_FAILURE_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*", re.ASCII)


class DocumentDomainError(ValueError):
    """Raised when a Document value or snapshot violates domain invariants."""


class DocumentTransitionError(DocumentDomainError):
    """Raised when a Document lifecycle transition is not allowed."""


class DocumentStatus(StrEnum):
    """Stable processing lifecycle states for a Document."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


def _require_uuid(value: object, field_name: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise DocumentDomainError(f"{field_name} is invalid.")


def _require_text(value: object, field_name: str, maximum: int) -> None:
    if not isinstance(value, str):
        raise DocumentDomainError(f"{field_name} must be a string.")
    if not value.strip():
        raise DocumentDomainError(f"{field_name} is required.")
    if len(value) > maximum:
        raise DocumentDomainError(f"{field_name} is too long.")


def _require_timestamp(value: object, field_name: str) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DocumentDomainError(f"{field_name} must be timezone-aware.")


@dataclass(frozen=True)
class DocumentFailure:
    """Bounded failure information safe for later persistence and presentation."""

    code: str
    safe_message: str

    def __post_init__(self) -> None:
        _require_text(self.code, "Document failure code", _MAX_FAILURE_CODE_LENGTH)
        if _FAILURE_CODE_PATTERN.fullmatch(self.code) is None:
            raise DocumentDomainError("Document failure code is invalid.")
        _require_text(
            self.safe_message,
            "Document failure message",
            _MAX_SAFE_FAILURE_MESSAGE_LENGTH,
        )


@dataclass(frozen=True)
class Document:
    """An immutable tenant-owned processing lifecycle derived from one File."""

    public_id: UUID
    organization_public_id: UUID
    source_file_public_id: UUID
    created_at: datetime
    status: DocumentStatus = DocumentStatus.QUEUED
    processing_version: str | None = None
    extractor_version: str | None = None
    processing_started_at: datetime | None = None
    processing_completed_at: datetime | None = None
    failed_at: datetime | None = None
    failure: DocumentFailure | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.public_id, "Document identifier")
        _require_uuid(self.organization_public_id, "Organization identifier")
        _require_uuid(self.source_file_public_id, "Source File identifier")
        if not isinstance(self.status, DocumentStatus):
            raise DocumentDomainError("Document status is invalid.")
        _require_timestamp(self.created_at, "created_at")

        for field_name, label in (
            ("processing_version", "Processing version"),
            ("extractor_version", "Extractor version"),
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_text(value, label, _MAX_VERSION_LENGTH)
        for field_name in (
            "processing_started_at",
            "processing_completed_at",
            "failed_at",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_timestamp(value, field_name)
        if self.failure is not None and not isinstance(self.failure, DocumentFailure):
            raise DocumentDomainError("Document failure metadata is invalid.")

        self._validate_status_snapshot()
        self._validate_timestamp_order()

    def start_processing(
        self,
        *,
        at: datetime,
        processing_version: str,
    ) -> Document:
        """Start the one processing lifecycle represented by this Document."""
        self._require_status(
            DocumentStatus.QUEUED,
            "Document cannot start processing from its current status.",
        )
        return replace(
            self,
            status=DocumentStatus.PROCESSING,
            processing_version=processing_version,
            processing_started_at=at,
        )

    def record_extractor_version(self, extractor_version: str) -> Document:
        """Record the selected extractor exactly once during processing."""
        self._require_status(
            DocumentStatus.PROCESSING,
            "Document extractor can only be recorded while processing.",
        )
        if self.extractor_version is not None:
            raise DocumentTransitionError(
                "Document extractor version has already been recorded."
            )
        _require_text(extractor_version, "Extractor version", _MAX_VERSION_LENGTH)
        return replace(self, extractor_version=extractor_version)

    def complete(self, *, at: datetime) -> Document:
        """Complete active processing."""
        self._require_status(
            DocumentStatus.PROCESSING,
            "Document cannot be completed from its current status.",
        )
        return replace(
            self,
            status=DocumentStatus.COMPLETED,
            processing_completed_at=at,
        )

    def fail(
        self,
        *,
        at: datetime,
        code: str,
        safe_message: str,
    ) -> Document:
        """Fail active processing with bounded, presentation-safe metadata."""
        self._require_status(
            DocumentStatus.PROCESSING,
            "Document cannot fail from its current status.",
        )
        return replace(
            self,
            status=DocumentStatus.FAILED,
            failed_at=at,
            failure=DocumentFailure(code=code, safe_message=safe_message),
        )

    def _require_status(self, required: DocumentStatus, message: str) -> None:
        if self.status is not required:
            raise DocumentTransitionError(message)

    def _validate_status_snapshot(self) -> None:
        actual = tuple(
            value is not None
            for value in (
                self.processing_version,
                self.processing_started_at,
                self.processing_completed_at,
                self.failed_at,
                self.failure,
            )
        )
        expected = {
            DocumentStatus.QUEUED: (False, False, False, False, False),
            DocumentStatus.PROCESSING: (True, True, False, False, False),
            DocumentStatus.COMPLETED: (True, True, True, False, False),
            DocumentStatus.FAILED: (True, True, False, True, True),
        }
        if actual != expected[self.status] or (
            self.status is DocumentStatus.QUEUED and self.extractor_version is not None
        ):
            raise DocumentDomainError(
                "Document lifecycle metadata is inconsistent with its status."
            )

    def _validate_timestamp_order(self) -> None:
        comparisons = (
            (
                self.processing_started_at,
                self.created_at,
                "Document processing cannot start before creation.",
            ),
            (
                self.processing_completed_at,
                self.processing_started_at,
                "Document processing cannot complete before it starts.",
            ),
            (
                self.failed_at,
                self.processing_started_at,
                "Document processing cannot fail before it starts.",
            ),
        )
        for value, lower_bound, message in comparisons:
            if value is not None and lower_bound is not None and value < lower_bound:
                raise DocumentDomainError(message)
