"""Authentication API schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SignupRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_name: str = Field(min_length=1, max_length=255)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320)


class SignupResponseBody(BaseModel):
    status: str


class SignupVerificationRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    otp: str = Field(min_length=1, max_length=10)
    organization_name: str = Field(min_length=1, max_length=255)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)


class SignupVerificationResponseBody(BaseModel):
    status: str
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
