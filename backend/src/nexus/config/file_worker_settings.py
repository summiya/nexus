"""Configuration for the dedicated File upload-completion worker."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from nexus.config.settings import ROOT_ENV_FILE


class FileWorkerSettings(BaseSettings):
    """Only the configuration required by the File completion worker."""

    log_level: str = "INFO"
    azure_service_bus_fully_qualified_namespace: str = Field(
        min_length=1,
        max_length=255,
    )
    azure_service_bus_queue_name: str = Field(min_length=1, max_length=260)
    azure_service_bus_managed_identity_client_id: UUID | None = None
    azure_event_grid_expected_source: str = Field(min_length=1, max_length=1024)
    azure_storage_container: str = Field(min_length=1, max_length=63)
    file_upload_completion_source: str = Field(
        default="azure-primary",
        min_length=1,
        max_length=1024,
    )
    file_worker_max_lock_renewal_seconds: int = Field(
        default=300,
        ge=60,
        le=600,
    )

    @field_validator(
        "azure_service_bus_queue_name",
        "azure_event_grid_expected_source",
        "azure_storage_container",
        "file_upload_completion_source",
    )
    @classmethod
    def reject_blank_or_padded_text(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("File worker configuration is invalid")
        return value

    @field_validator("azure_service_bus_fully_qualified_namespace")
    @classmethod
    def validate_service_bus_namespace(cls, value: str) -> str:
        if (
            not value.strip()
            or value != value.strip()
            or "://" in value
            or "/" in value
            or "?" in value
            or "#" in value
            or any(character.isspace() for character in value)
        ):
            raise ValueError("Service Bus namespace is invalid")
        return value

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )


def load_file_worker_settings(
    *,
    env_file: Path | None = ROOT_ENV_FILE,
) -> FileWorkerSettings:
    """Load the dedicated worker settings without web-only configuration."""

    return FileWorkerSettings(_env_file=env_file)  # type: ignore[call-arg]


__all__ = ["FileWorkerSettings", "load_file_worker_settings"]
