"""File HTTP request and response schemas."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from nexus.files.domain import (
    MAX_MIME_TYPE_LENGTH,
    MAX_ORIGINAL_NAME_LENGTH,
)
from nexus.files.ports import UPLOAD_CONTEXT_MAX_LENGTH


class InitiateFileUploadRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_name: str = Field(max_length=MAX_ORIGINAL_NAME_LENGTH)
    mime_type: str | None = Field(default=None, max_length=MAX_MIME_TYPE_LENGTH)
    size_bytes: int = Field(strict=True, ge=0)


class UploadMetadataResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nexus_upload_context: str = Field(
        min_length=1,
        max_length=UPLOAD_CONTEXT_MAX_LENGTH,
        repr=False,
    )


class UploadInstructionsResponseBody(BaseModel):
    url: str = Field(repr=False)
    method: str
    headers: dict[str, str] = Field(repr=False)
    metadata: UploadMetadataResponseBody = Field(repr=False)
    expires_at: datetime


class InitiateFileUploadResponseBody(BaseModel):
    upload: UploadInstructionsResponseBody


class FileMetadataStorageStatus(StrEnum):
    """Public File statuses; internal DELETING is intentionally excluded."""

    PENDING = "pending"
    AVAILABLE = "available"
    FAILED = "failed"


class FileMetadataResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_id: UUID
    original_name: str
    mime_type: str
    size_bytes: int | None
    storage_status: FileMetadataStorageStatus
    created_at: datetime
    updated_at: datetime


class ListFilesResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FileMetadataResponseBody]
    next_cursor: str | None


class FileDownloadResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(repr=False)
    expires_at: datetime
