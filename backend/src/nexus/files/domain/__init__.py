"""Provider-independent File domain contracts."""

from nexus.files.domain.file import (
    MAX_MIME_TYPE_LENGTH,
    MAX_ORIGINAL_NAME_LENGTH,
    File,
    FileStorageStatus,
)
from nexus.files.domain.upload_context import (
    UPLOAD_CONTEXT_VERSION,
    UploadContext,
)

__all__ = [
    "MAX_MIME_TYPE_LENGTH",
    "MAX_ORIGINAL_NAME_LENGTH",
    "UPLOAD_CONTEXT_VERSION",
    "File",
    "FileStorageStatus",
    "UploadContext",
]
