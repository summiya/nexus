"""Configuration for the dedicated File upload-completion worker."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import Field, HttpUrl, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from nexus.config.settings import (
    DEFAULT_FILE_UPLOAD_MAX_SIZE_BYTES,
    ROOT_ENV_FILE,
    validate_file_upload_context_key,
)

_INVALID_ACCOUNT_URL_MESSAGE = (
    "Azure storage account URL must be a credential-free HTTPS service root"
)


class FileWorkerSettings(BaseSettings):
    """Only the configuration required by the File completion worker."""

    log_level: str = "INFO"
    app_env: str = "development"
    database_url: str = Field(min_length=1)
    file_upload_max_size_bytes: int = Field(
        default=DEFAULT_FILE_UPLOAD_MAX_SIZE_BYTES,
        gt=0,
    )
    file_upload_context_key: SecretStr
    file_worker_database_pool_size: int = Field(default=2, ge=1, le=20)
    file_worker_database_max_overflow: int = Field(default=0, ge=0, le=20)
    azure_service_bus_fully_qualified_namespace: str = Field(
        min_length=1,
        max_length=255,
    )
    azure_service_bus_queue_name: str = Field(min_length=1, max_length=260)
    azure_service_bus_malware_scan_queue_name: str = Field(
        default="file-malware-scan-results",
        min_length=1,
        max_length=260,
    )
    azure_service_bus_managed_identity_client_id: UUID | None = None
    azure_event_grid_expected_source: str = Field(min_length=1, max_length=1024)
    azure_malware_scan_expected_topic: str = Field(min_length=1, max_length=2048)
    azure_storage_container: str = Field(min_length=1, max_length=63)
    azure_storage_account_url: HttpUrl
    file_upload_completion_source: str = Field(
        default="azure-primary",
        min_length=1,
        max_length=1024,
    )
    file_malware_scan_source: str = Field(
        default="azure-defender-storage",
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
        "azure_service_bus_malware_scan_queue_name",
        "azure_event_grid_expected_source",
        "azure_malware_scan_expected_topic",
        "azure_storage_container",
        "file_upload_completion_source",
        "file_malware_scan_source",
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

    @field_validator("file_upload_context_key")
    @classmethod
    def validate_upload_context_key(
        cls,
        value: SecretStr,
        info: ValidationInfo,
    ) -> SecretStr:
        return validate_file_upload_context_key(
            value,
            app_env=info.data.get("app_env"),
        )

    @field_validator("azure_storage_account_url")
    @classmethod
    def validate_storage_account_url(cls, value: HttpUrl) -> HttpUrl:
        if (
            value.scheme != "https"
            or value.username is not None
            or value.password is not None
            or value.path != "/"
            or value.query is not None
            or value.fragment is not None
        ):
            raise ValueError(_INVALID_ACCOUNT_URL_MESSAGE)
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
