"""Conversation domain contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


def _require_timezone_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class Conversation:
    """A conversation container and its tenant/scope identities."""

    public_id: UUID
    organization_public_id: UUID
    created_by_user_public_id: UUID
    created_at: datetime
    updated_at: datetime
    workspace_public_id: UUID | None = None
    project_public_id: UUID | None = None
    title: str | None = None

    def __post_init__(self) -> None:
        if self.project_public_id is not None and self.workspace_public_id is None:
            raise ValueError("project scope requires a workspace scope")
        _require_timezone_aware(self.created_at, "created_at")
        _require_timezone_aware(self.updated_at, "updated_at")
