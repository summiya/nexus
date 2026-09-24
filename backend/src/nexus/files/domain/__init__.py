"""Provider-independent File domain contracts."""

from nexus.files.domain.file import (
    MAX_MIME_TYPE_LENGTH,
    MAX_ORIGINAL_NAME_LENGTH,
    File,
    FileStorageStatus,
)

__all__ = [
    "MAX_MIME_TYPE_LENGTH",
    "MAX_ORIGINAL_NAME_LENGTH",
    "File",
    "FileStorageStatus",
]
