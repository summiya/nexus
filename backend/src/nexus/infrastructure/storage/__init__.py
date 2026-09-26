"""Object storage infrastructure adapters."""

from nexus.infrastructure.storage.azure_blob import AzureBlobObjectStorage
from nexus.infrastructure.storage.azure_blob_created import (
    AzureBlobCreatedEventMapper,
    AzureBlobCreatedEventMappingError,
)
from nexus.infrastructure.storage.azure_download_grant import (
    AzureUserDelegationDownloadGrantIssuer,
)
from nexus.infrastructure.storage.azure_malware_scan import (
    AzureMalwareScanResultMapper,
    AzureMalwareScanResultMappingError,
)
from nexus.infrastructure.storage.azure_upload_grant import (
    AzureUserDelegationUploadGrantIssuer,
)
from nexus.infrastructure.storage.azure_user_delegation_key import (
    AzureUserDelegationKeyProvider,
)

__all__ = [
    "AzureBlobCreatedEventMapper",
    "AzureBlobCreatedEventMappingError",
    "AzureBlobObjectStorage",
    "AzureMalwareScanResultMapper",
    "AzureMalwareScanResultMappingError",
    "AzureUserDelegationDownloadGrantIssuer",
    "AzureUserDelegationKeyProvider",
    "AzureUserDelegationUploadGrantIssuer",
]
