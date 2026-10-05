"""Bounded resources for the Document dispatcher and future consumer."""

from uuid import UUID

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DocumentWorkerSettings(BaseSettings):
    database_url: str = Field(min_length=1)
    log_level: str = "INFO"
    azure_service_bus_fully_qualified_namespace: str = Field(
        min_length=1, max_length=255
    )
    azure_service_bus_document_queue_name: str = Field(
        default="document-processing-requests", min_length=1, max_length=260
    )
    azure_service_bus_managed_identity_client_id: UUID | None = None
    document_database_pool_size: int = Field(default=2, ge=1, le=20)
    document_dispatch_concurrency: int = Field(default=2, ge=1, le=20)
    document_dispatch_lease_seconds: int = Field(default=60, ge=30, le=600)
    document_dispatch_send_timeout_seconds: int = Field(default=20, ge=1, le=60)
    document_dispatch_poll_seconds: float = Field(default=2, ge=0.1, le=60)
    document_worker_concurrency: int = Field(default=2, ge=1, le=20)
    document_worker_max_lock_renewal_seconds: int = Field(default=300, ge=60, le=600)
    document_processing_version: str = Field(
        default="dp-04", min_length=1, max_length=128
    )

    @model_validator(mode="after")
    def validate_bounds(self) -> "DocumentWorkerSettings":
        namespace = self.azure_service_bus_fully_qualified_namespace
        if any(c.isspace() for c in namespace) or any(c in namespace for c in "/:?#"):
            raise ValueError("Invalid Service Bus namespace")
        for text in (
            self.azure_service_bus_document_queue_name,
            self.document_processing_version,
        ):
            if not text.strip() or text != text.strip():
                raise ValueError("Invalid Document worker configuration")
        if (
            self.document_dispatch_send_timeout_seconds
            >= self.document_dispatch_lease_seconds
        ):
            raise ValueError("Send timeout must be shorter than dispatch lease")
        return self

    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)
