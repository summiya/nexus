"""Model-provider HTTP request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from nexus.model_providers.domain import (
    MAX_PROVIDER_CREDENTIAL_SECRET_BYTES,
    ProviderType,
    ProviderValidationStatus,
)
from nexus.model_providers.domain.validation import MAX_DISPLAY_NAME_LENGTH


class ProviderCatalogItemResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_type: ProviderType
    display_name: str
    required_settings: list[str]


class ProviderCatalogResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProviderCatalogItemResponseBody]


class ConfiguredProviderResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_id: UUID
    provider_type: ProviderType
    display_name: str
    settings: dict[str, str]
    enabled: bool
    credential_configured: bool
    validation_status: ProviderValidationStatus
    last_validated_at: datetime | None


class ListConfiguredProvidersResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ConfiguredProviderResponseBody]


class CreateProviderRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_type: ProviderType
    display_name: str = Field(min_length=1, max_length=MAX_DISPLAY_NAME_LENGTH)
    settings: dict[str, str]
    enabled: bool = True


class UpdateProviderRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_DISPLAY_NAME_LENGTH,
    )
    settings: dict[str, str] | None = None

    @model_validator(mode="after")
    def require_change(self) -> UpdateProviderRequestBody:
        if self.display_name is None and self.settings is None:
            raise ValueError("At least one provider field must be supplied.")
        return self


class SetProviderEnabledRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class SetProviderCredentialRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential: SecretStr = Field(
        min_length=1,
        max_length=MAX_PROVIDER_CREDENTIAL_SECRET_BYTES,
        repr=False,
    )


class ProviderCredentialStateResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_configured: bool


class ProviderValidationResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ProviderValidationStatus
    last_validated_at: datetime


__all__ = [
    "ConfiguredProviderResponseBody",
    "CreateProviderRequestBody",
    "ListConfiguredProvidersResponseBody",
    "ProviderCatalogItemResponseBody",
    "ProviderCatalogResponseBody",
    "ProviderCredentialStateResponseBody",
    "ProviderValidationResponseBody",
    "SetProviderCredentialRequestBody",
    "SetProviderEnabledRequestBody",
    "UpdateProviderRequestBody",
]
