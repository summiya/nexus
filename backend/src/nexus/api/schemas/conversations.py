"""Conversation HTTP schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateConversationRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=255)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ConversationResponseBody(BaseModel):
    public_id: UUID
    organization_public_id: UUID
    created_by_user_public_id: UUID
    workspace_public_id: UUID | None
    project_public_id: UUID | None
    title: str | None


class CreateMessageRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=100_000)
    model: str = Field(min_length=1, max_length=255)

    @field_validator("content", "model")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized
