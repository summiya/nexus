"""Conversation HTTP request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nexus.conversations.domain import (
    ConversationMessageRole,
    GenerationFinishReason,
    GenerationStatus,
)


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


class ConversationListItemResponseBody(BaseModel):
    public_id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class ListConversationsResponseBody(BaseModel):
    items: list[ConversationListItemResponseBody]


class ConversationGenerationResponseBody(BaseModel):
    public_id: UUID
    model: str
    status: GenerationStatus
    finish_reason: GenerationFinishReason | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    started_at: datetime | None
    completed_at: datetime | None
    error_kind: str | None


class ConversationMessageResponseBody(BaseModel):
    public_id: UUID
    role: ConversationMessageRole
    content: str
    created_at: datetime
    generation: ConversationGenerationResponseBody | None


class GetConversationMessagesResponseBody(BaseModel):
    items: list[ConversationMessageResponseBody]


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
