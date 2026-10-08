"""Bounded resources for the Document dispatcher and explicit consumer."""

from uuid import UUID

from pydantic import Field, HttpUrl, field_validator, model_validator
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
        default="dp-11-v1", min_length=1, max_length=128
    )
    document_worker_max_delivery_count: int = Field(default=10, ge=1, le=100)
    document_attempt_timeout_seconds: int = Field(default=240, ge=1, le=540)
    azure_storage_account_url: HttpUrl | None = None
    azure_storage_container: str | None = Field(
        default=None, min_length=1, max_length=63
    )
    azure_storage_managed_identity_client_id: UUID | None = None
    azure_document_intelligence_endpoint: HttpUrl | None = None
    azure_document_intelligence_managed_identity_client_id: UUID | None = None
    file_upload_max_size_bytes: int = Field(default=536_870_912, ge=1)

    @field_validator(
        "azure_storage_account_url", "azure_document_intelligence_endpoint"
    )
    @classmethod
    def validate_provider_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and (
            value.scheme != "https"
            or value.username is not None
            or value.password is not None
            or value.path != "/"
            or value.query is not None
            or value.fragment is not None
        ):
            raise ValueError(
                "Provider endpoint must be a credential-free HTTPS service root"
            )
        return value

    def validate_consumer(self) -> None:
        if (
            self.azure_storage_account_url is None
            or self.azure_storage_container is None
            or self.azure_document_intelligence_endpoint is None
        ):
            raise ValueError("Document consumption requires Blob and OCR configuration")
        if self.azure_storage_container != self.azure_storage_container.strip():
            raise ValueError("Invalid Document storage container")
        if (
            self.document_attempt_timeout_seconds + 60
            > self.document_worker_max_lock_renewal_seconds
        ):
            raise ValueError("Document attempt deadline requires lock-renewal headroom")

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
