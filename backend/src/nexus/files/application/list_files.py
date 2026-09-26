"""List tenant-scoped File metadata with keyset pagination."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from nexus.authorization import PermissionChecker
from nexus.errors import ErrorCode, NexusError
from nexus.files.application.read_access import authorize_files_read
from nexus.files.domain import File
from nexus.files.ports import FilePersistence, FilePersistenceError

DEFAULT_FILE_PAGE_SIZE = 50
MAX_FILE_PAGE_SIZE = 100


@dataclass(frozen=True)
class FilePageCursor:
    """Provider-neutral keyset position for deterministic File pagination."""

    created_at: datetime
    public_id: UUID

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("File page cursor timestamp must be timezone-aware")


@dataclass(frozen=True)
class FilePage:
    """One bounded page of tenant-scoped File metadata."""

    items: tuple[File, ...]
    next_cursor: FilePageCursor | None


@dataclass(frozen=True)
class ListFiles:
    """Authorize and list Files without count/offset scans."""

    persistence: FilePersistence
    permission_checker: PermissionChecker

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        limit: int = DEFAULT_FILE_PAGE_SIZE,
        cursor: FilePageCursor | None = None,
    ) -> FilePage:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("File page limit must be an integer")
        if limit < 1 or limit > MAX_FILE_PAGE_SIZE:
            raise ValueError(
                f"File page limit must be between 1 and {MAX_FILE_PAGE_SIZE}"
            )

        await authorize_files_read(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
        )
        try:
            rows = await self.persistence.list_files(
                organization_public_id=organization_public_id,
                before_created_at=(cursor.created_at if cursor is not None else None),
                before_public_id=(cursor.public_id if cursor is not None else None),
                limit=limit + 1,
            )
        except FilePersistenceError as exc:
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The files could not be retrieved.",
                retryable=True,
            ) from exc

        items = rows[:limit]
        next_cursor = (
            FilePageCursor(
                created_at=items[-1].created_at,
                public_id=items[-1].public_id,
            )
            if len(rows) > limit and items
            else None
        )
        return FilePage(items=items, next_cursor=next_cursor)


__all__ = [
    "DEFAULT_FILE_PAGE_SIZE",
    "MAX_FILE_PAGE_SIZE",
    "FilePage",
    "FilePageCursor",
    "ListFiles",
]
