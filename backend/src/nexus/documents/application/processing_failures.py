"""One delivery-level failure policy; component failures stay provider-neutral."""

from dataclasses import dataclass

from nexus.documents.application.normalize_document import (
    DocumentNormalizationError,
    DocumentNormalizationFailure,
)
from nexus.documents.domain import DocumentFailure
from nexus.documents.ports.chunk_persistence import (
    ChunkConflictError,
    ChunkPersistenceError,
    StoredChunkCorruptionError,
)
from nexus.documents.ports.dispatch import DocumentDispatchError
from nexus.documents.ports.extraction import (
    DocumentExtractionError,
    DocumentExtractionFailure,
)
from nexus.documents.ports.persistence import DocumentPersistenceError
from nexus.documents.ports.segmentation import (
    DocumentSegmentationError,
    DocumentSegmentationFailure,
)
from nexus.documents.ports.source import DocumentSourceError, DocumentSourceFailure
from nexus.files.ports import ObjectStorageError, ObjectStorageFailure
from nexus.files.ports.persistence import FilePersistenceError


@dataclass(frozen=True)
class ProcessingFailure:
    retryable: bool
    failure: DocumentFailure
    unexpected: bool = False


class ProcessingVersionConflict(Exception):
    def __init__(self) -> None:
        super().__init__("Document processing version conflicts")


def policy(code: str, message: str, *, retryable: bool = False) -> ProcessingFailure:
    return ProcessingFailure(retryable, DocumentFailure(code, message))


RESOURCE_LIMIT = policy(
    "DOCUMENT_RESOURCE_LIMIT", "Document processing exceeded supported resource limits."
)
EMPTY = policy("EMPTY_DOCUMENT", "The document contains no usable content.")
ARTIFACT_MISMATCH = policy(
    "ARTIFACT_MISMATCH", "The normalized artifact failed integrity verification."
)
STORAGE_UNAVAILABLE = policy(
    "STORAGE_UNAVAILABLE", "Document storage is unavailable.", retryable=True
)
RETRY_EXHAUSTED = policy(
    "RETRY_EXHAUSTED", "Document processing exhausted its delivery budget."
)


PROCESSING_OUTPUT_CORRUPT = policy(
    "PROCESSING_OUTPUT_CORRUPT", "The persisted processing output is invalid."
)


def classify_processing_failure(error: Exception) -> ProcessingFailure:
    if isinstance(error, StoredChunkCorruptionError):
        return PROCESSING_OUTPUT_CORRUPT
    if isinstance(error, DocumentSourceError):
        return {
            DocumentSourceFailure.INVALID_REQUEST: policy(
                "INVALID_PROCESSING_CONTEXT",
                "The document processing context is invalid.",
            ),
            DocumentSourceFailure.UNAVAILABLE: policy(
                "SOURCE_UNAVAILABLE", "The admitted source is unavailable."
            ),
            DocumentSourceFailure.CHANGED: policy(
                "SOURCE_CHANGED", "The admitted source version has changed."
            ),
            DocumentSourceFailure.TOO_LARGE: RESOURCE_LIMIT,
        }.get(error.reason, STORAGE_UNAVAILABLE)
    if isinstance(error, DocumentExtractionError):
        return {
            DocumentExtractionFailure.UNSUPPORTED: policy(
                "UNSUPPORTED_DOCUMENT", "The document format is unsupported."
            ),
            DocumentExtractionFailure.EMPTY: EMPTY,
            DocumentExtractionFailure.MALFORMED: policy(
                "MALFORMED_DOCUMENT", "The document content cannot be read."
            ),
            DocumentExtractionFailure.RESOURCE_LIMIT: RESOURCE_LIMIT,
            DocumentExtractionFailure.ENCRYPTED: policy(
                "ENCRYPTED_DOCUMENT", "Encrypted documents are unsupported."
            ),
            DocumentExtractionFailure.PARSER_FAILURE: policy(
                "PARSER_UNAVAILABLE", "Document parsing is unavailable.", retryable=True
            ),
        }.get(
            error.reason,
            policy(
                "PROVIDER_UNAVAILABLE",
                "The document processing provider is unavailable.",
                retryable=True,
            ),
        )
    if isinstance(error, DocumentNormalizationError):
        return {
            DocumentNormalizationFailure.EMPTY: EMPTY,
            DocumentNormalizationFailure.RESOURCE_LIMIT: RESOURCE_LIMIT,
            DocumentNormalizationFailure.ARTIFACT_MISMATCH: ARTIFACT_MISMATCH,
        }[error.reason]
    if isinstance(error, DocumentSegmentationError):
        return (
            EMPTY
            if error.reason is DocumentSegmentationFailure.EMPTY
            else RESOURCE_LIMIT
        )
    if isinstance(error, ProcessingVersionConflict):
        return policy(
            "PROCESSING_VERSION_CONFLICT",
            "The generation requires an incompatible processing recipe.",
        )
    if isinstance(error, ChunkConflictError):
        return policy(
            "CHUNK_CONFLICT", "The processing result conflicts with its generation."
        )
    if isinstance(
        error,
        (
            DocumentPersistenceError,
            ChunkPersistenceError,
            DocumentDispatchError,
            FilePersistenceError,
        ),
    ):
        return policy(
            "PERSISTENCE_UNAVAILABLE",
            "Document processing persistence is unavailable.",
            retryable=True,
        )
    if isinstance(error, ObjectStorageError):
        return (
            ARTIFACT_MISMATCH
            if error.reason is ObjectStorageFailure.CHANGED
            else STORAGE_UNAVAILABLE
        )
    return ProcessingFailure(
        True,
        DocumentFailure(
            "PROCESSING_UNAVAILABLE",
            "Document processing could not finish this attempt.",
        ),
        unexpected=not isinstance(error, TimeoutError),
    )
