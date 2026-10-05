"""Resolve, verify, and stream the admitted source without holding DB resources."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing, asynccontextmanager

from nexus.documents.domain import Document, DocumentStatus
from nexus.documents.ports.processing import (
    DocumentProcessingRequested,
    DocumentRequestReader,
)
from nexus.documents.ports.source import (
    DocumentSource,
    DocumentSourceError,
    DocumentSourceFacts,
    DocumentSourceFailure,
)
from nexus.files.domain import FileStorageStatus, is_canonical_file_storage_key
from nexus.files.ports import (
    FilePersistence,
    ObjectStorage,
    ObjectStorageError,
    ObjectStorageFailure,
    ObjectStorageNotFoundError,
)


class OpenDocumentSource:
    def __init__(
        self,
        *,
        requests: DocumentRequestReader,
        files: FilePersistence,
        storage: ObjectStorage,
        max_size_bytes: int,
    ) -> None:
        if type(max_size_bytes) is not int or max_size_bytes <= 0:
            raise ValueError("Invalid File size limit")
        self._requests = requests
        self._files = files
        self._storage = storage
        self._max_size = max_size_bytes

    @asynccontextmanager
    async def open(
        self, *, document: Document, request: DocumentProcessingRequested
    ) -> AsyncIterator[DocumentSource]:
        if (
            document.status != DocumentStatus.PROCESSING
            or document.public_id != request.document_public_id
            or document.organization_public_id != request.organization_public_id
        ):
            raise DocumentSourceError(DocumentSourceFailure.INVALID_REQUEST)
        facts = await self._requests.get_source_facts(request)
        if (
            facts is None
            or facts.source_file_public_id != document.source_file_public_id
        ):
            raise DocumentSourceError(DocumentSourceFailure.INVALID_REQUEST)
        file = await self._files.get_file(
            organization_public_id=document.organization_public_id,
            file_public_id=document.source_file_public_id,
        )
        if file is None or file.storage_status != FileStorageStatus.AVAILABLE:
            raise DocumentSourceError(DocumentSourceFailure.UNAVAILABLE)
        if (
            file.organization_public_id != document.organization_public_id
            or file.public_id != document.source_file_public_id
            or not is_canonical_file_storage_key(file.storage_key)
        ):
            raise DocumentSourceError(DocumentSourceFailure.INVALID_REQUEST)
        if file.size_bytes != facts.expected_size_bytes:
            raise DocumentSourceError(DocumentSourceFailure.CHANGED)
        if facts.expected_size_bytes > self._max_size:
            raise DocumentSourceError(DocumentSourceFailure.TOO_LARGE)
        await self._verify_properties(file.storage_key, facts)
        async with aclosing(self._stream(file.storage_key, facts)) as content:
            yield DocumentSource(
                file.public_id,
                file.original_name,
                file.mime_type,
                facts.source_entity_tag,
                facts.expected_size_bytes,
                content,
            )

    async def _verify_properties(self, key: str, facts: DocumentSourceFacts) -> None:
        try:
            properties = await self._storage.get_object_properties(storage_key=key)
        except ObjectStorageError as exc:
            raise _source_storage_error(exc) from exc
        if (
            properties.entity_tag != facts.source_entity_tag
            or properties.size_bytes != facts.expected_size_bytes
        ):
            raise DocumentSourceError(DocumentSourceFailure.CHANGED)

    async def _stream(
        self, key: str, facts: DocumentSourceFacts
    ) -> AsyncGenerator[bytes, None]:
        stream = self._storage.stream_object(
            storage_key=key, expected_entity_tag=facts.source_entity_tag
        )
        count = 0
        try:
            async for chunk in stream:
                if not isinstance(chunk, bytes):
                    raise DocumentSourceError(DocumentSourceFailure.STORAGE_FAILURE)
                count += len(chunk)
                if count > facts.expected_size_bytes or count > self._max_size:
                    raise DocumentSourceError(DocumentSourceFailure.CHANGED)
                yield chunk
            if count != facts.expected_size_bytes:
                raise DocumentSourceError(DocumentSourceFailure.CHANGED)
        except ObjectStorageError as exc:
            raise _source_storage_error(exc) from exc
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()


def _source_storage_error(error: ObjectStorageError) -> DocumentSourceError:
    if isinstance(error, ObjectStorageNotFoundError):
        return DocumentSourceError(DocumentSourceFailure.UNAVAILABLE)
    reason = {
        ObjectStorageFailure.CHANGED: DocumentSourceFailure.CHANGED,
        ObjectStorageFailure.TRANSIENT: DocumentSourceFailure.TRANSIENT_STORAGE,
        ObjectStorageFailure.ACCESS: DocumentSourceFailure.STORAGE_ACCESS,
    }.get(error.reason, DocumentSourceFailure.STORAGE_FAILURE)
    return DocumentSourceError(reason)
