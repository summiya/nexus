"""Metadata admission for initial Document ingestion; no content inspection."""

from datetime import datetime
from uuid import uuid4

from nexus.documents.application.formats import document_format
from nexus.documents.domain import Document
from nexus.files.domain import File, FileStorageStatus


def initial_document(file: File, *, at: datetime) -> Document | None:
    """Construct one queued candidate only for an eligible AVAILABLE File."""
    if file.storage_status is not FileStorageStatus.AVAILABLE:
        return None
    if document_format(file.original_name, file.mime_type) is None:
        return None
    return Document(
        public_id=uuid4(),
        organization_public_id=file.organization_public_id,
        source_file_public_id=file.public_id,
        created_at=at,
    )
