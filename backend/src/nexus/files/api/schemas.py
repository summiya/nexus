"""File HTTP request and response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from nexus.files.domain import (
    MAX_MIME_TYPE_LENGTH,
    MAX_ORIGINAL_NAME_LENGTH,
    FileStorageStatus,
)


class InitiateFileUploadRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_name: str = Field(max_length=MAX_ORIGINAL_NAME_LENGTH)
    mime_type: str | None = Field(default=None, max_length=MAX_MIME_TYPE_LENGTH)
    size_bytes: int = Field(strict=True, ge=0)


class InitiatedFileResponseBody(BaseModel):
    public_id: UUID
    original_name: str
    mime_type: str
    storage_status: FileStorageStatus
    created_at: datetime


class UploadInstructionsResponseBody(BaseModel):
    url: str = Field(repr=False)
    method: str
    headers: dict[str, str] = Field(repr=False)
    expires_at: datetime


class InitiateFileUploadResponseBody(BaseModel):
    file: InitiatedFileResponseBody
    upload: UploadInstructionsResponseBody
