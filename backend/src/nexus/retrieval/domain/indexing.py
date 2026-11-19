"""Immutable, model-neutral indexing lifecycle; tenant scope grants no access."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class IndexingTransitionError(ValueError):
    """An indexing snapshot or transition violates the lifecycle contract."""


class IndexingStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


def require_indexing_identity(
    organization_public_id: UUID,
    document_public_id: UUID,
    configured_model_public_id: UUID,
    embedding_generation: int,
) -> None:
    if any(
        not isinstance(value, UUID) or not value.int
        for value in (
            organization_public_id,
            document_public_id,
            configured_model_public_id,
        )
    ) or (type(embedding_generation) is not int or embedding_generation < 1):
        raise ValueError("Invalid indexing generation identity")


def _require_text(value: object, maximum: int) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or not value.strip()
        or value != value.strip()
    ):
        raise ValueError("Indexing metadata must be bounded and meaningful")


@dataclass(frozen=True, slots=True, repr=False)
class IndexingGeneration:
    """One independently versioned attempt over a stored Document chunk set.

    Snapshot fields describe a model, not its credentials or current eligibility.
    Persistence verifies source eligibility and durable coverage before completion.
    """

    organization_public_id: UUID
    document_public_id: UUID
    configured_model_public_id: UUID
    embedding_generation: int
    embedding_version: str
    provider_type: str
    provider_model_name: str
    embedding_dimension: int
    created_at: datetime
    status: IndexingStatus = IndexingStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        require_indexing_identity(*self.identity)
        for value, maximum in (
            (self.embedding_version, 128),
            (self.provider_type, 32),
            (self.provider_model_name, 256),
        ):
            _require_text(value, maximum)
        if type(self.embedding_dimension) is not int or self.embedding_dimension < 1:
            raise ValueError("Indexing dimension must be a positive integer")
        if not isinstance(self.status, IndexingStatus):
            raise TypeError("Invalid indexing status")
        for at in (self.created_at, self.started_at, self.finished_at):
            if at is None:
                continue
            if (
                not isinstance(at, datetime)
                or at.tzinfo is None
                or at.utcoffset() is None
            ):
                raise ValueError("Indexing timestamps must be timezone-aware")
        if not isinstance(self.created_at, datetime):
            raise TypeError("Indexing creation timestamp is required")
        if self.failure_code is not None:
            _require_text(self.failure_code, 64)
            if re.fullmatch(r"[A-Z][A-Z0-9_]*", self.failure_code, re.ASCII) is None:
                raise ValueError("Invalid indexing failure code")
        if self.status is IndexingStatus.PENDING:
            valid = (
                self.started_at is None
                and self.finished_at is None
                and self.failure_code is None
            )
        elif self.status is IndexingStatus.PROCESSING:
            valid = (
                self.started_at is not None
                and self.finished_at is None
                and self.failure_code is None
            )
        elif self.status is IndexingStatus.COMPLETED:
            valid = (
                self.started_at is not None
                and self.finished_at is not None
                and self.failure_code is None
            )
        else:
            valid = self.finished_at is not None and self.failure_code is not None
        if not valid:
            raise ValueError("Indexing lifecycle metadata is inconsistent")
        if (self.started_at is not None and self.started_at < self.created_at) or (
            self.finished_at is not None
            and self.finished_at < (self.started_at or self.created_at)
        ):
            raise ValueError("Indexing timestamps are out of order")

    @property
    def identity(self) -> tuple[UUID, UUID, UUID, int]:
        return (
            self.organization_public_id,
            self.document_public_id,
            self.configured_model_public_id,
            self.embedding_generation,
        )

    @property
    def model_snapshot(self) -> tuple[str, str, str, int]:
        return (
            self.embedding_version,
            self.provider_type,
            self.provider_model_name,
            self.embedding_dimension,
        )

    def start(self, *, at: datetime) -> IndexingGeneration:
        if self.status is not IndexingStatus.PENDING:
            raise IndexingTransitionError("Indexing cannot start from this state")
        return replace(self, status=IndexingStatus.PROCESSING, started_at=at)

    def complete(self, *, at: datetime) -> IndexingGeneration:
        if self.status is not IndexingStatus.PROCESSING:
            raise IndexingTransitionError("Indexing cannot complete from this state")
        return replace(self, status=IndexingStatus.COMPLETED, finished_at=at)

    def fail(self, *, at: datetime, code: str) -> IndexingGeneration:
        if self.status not in (IndexingStatus.PENDING, IndexingStatus.PROCESSING):
            raise IndexingTransitionError("Indexing cannot fail from this state")
        return replace(
            self, status=IndexingStatus.FAILED, finished_at=at, failure_code=code
        )

    def is_immediate_successor(self, proposed: IndexingGeneration) -> bool:
        if (
            self.identity != proposed.identity
            or self.model_snapshot != proposed.model_snapshot
            or self.created_at != proposed.created_at
        ):
            return False
        if (
            proposed.status is IndexingStatus.PROCESSING
            and self.status is IndexingStatus.PENDING
            and proposed.started_at is not None
        ):
            return self.start(at=proposed.started_at) == proposed
        if (
            proposed.status is IndexingStatus.COMPLETED
            and self.status is IndexingStatus.PROCESSING
            and proposed.finished_at is not None
        ):
            return self.complete(at=proposed.finished_at) == proposed
        if (
            proposed.status is IndexingStatus.FAILED
            and self.status in (IndexingStatus.PENDING, IndexingStatus.PROCESSING)
            and proposed.finished_at is not None
            and proposed.failure_code is not None
        ):
            return (
                self.fail(at=proposed.finished_at, code=proposed.failure_code)
                == proposed
            )
        return False
