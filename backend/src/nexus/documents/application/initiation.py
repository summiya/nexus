"""Metadata admission for initial Document ingestion; no content inspection."""

from datetime import datetime
from pathlib import PurePosixPath
from uuid import uuid4

from nexus.documents.domain import Document
from nexus.files.domain import File, FileStorageStatus

_SUPPORTED_MIME_TYPES = {
    ".pdf": frozenset({"application/pdf", "application/octet-stream"}),
    ".txt": frozenset({"text/plain", "application/octet-stream"}),
    ".md": frozenset({"text/markdown", "text/plain", "application/octet-stream"}),
}


def initial_document(file: File, *, at: datetime) -> Document | None:
    """Construct one queued candidate only for an eligible AVAILABLE File."""
    if file.storage_status is not FileStorageStatus.AVAILABLE:
        return None
    suffix = PurePosixPath(file.original_name).suffix.lower()
    if file.mime_type.lower() not in _SUPPORTED_MIME_TYPES.get(suffix, frozenset()):
        return None
    return Document(
        public_id=uuid4(),
        organization_public_id=file.organization_public_id,
        source_file_public_id=file.public_id,
        created_at=at,
    )
