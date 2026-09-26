"""Object storage infrastructure adapters."""

from nexus.infrastructure.storage.azure_blob import AzureBlobObjectStorage
from nexus.infrastructure.storage.azure_blob_created import (
    AzureBlobCreatedEventMapper,
    AzureBlobCreatedEventMappingError,
)
from nexus.infrastructure.storage.azure_file_worker_event import AzureFileWorkerEventMapper
from nexus.infrastructure.storage.azure_malware_scan import (
    AzureMalwareScanResultMapper,
    AzureMalwareScanResultMappingError,
)
from nexus.infrastructure.storage.azure_upload_grant import (
    AzureUserDelegationUploadGrantIssuer,
)

__all__ = [
    "AzureBlobCreatedEventMapper",
    "AzureBlobCreatedEventMappingError",
    "AzureBlobObjectStorage",
    "AzureFileWorkerEventMapper",
    "AzureMalwareScanResultMapper",
    "AzureMalwareScanResultMappingError",
    "AzureUserDelegationUploadGrantIssuer",
]
