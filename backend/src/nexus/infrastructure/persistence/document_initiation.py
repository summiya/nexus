"""Dedicated short transaction for the verified clean-scan handoff."""

import asyncio
import hashlib
from dataclasses import replace
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.documents.application.initiation import initial_document
from nexus.documents.ports.initiation import (
    DocumentInitiationConflictError,
    DocumentInitiationError,
    DocumentInitiationPersistence,
)
from nexus.files.domain import FileStorageStatus, is_canonical_file_storage_key
from nexus.infrastructure.persistence import _document_initiation_queries as queries
from nexus.infrastructure.persistence import _file_queries
from nexus.infrastructure.persistence.document import _settle_cancelled_transaction
from nexus.logging import get_logger

logger = get_logger(__name__)


class SqlAlchemyDocumentInitiationPersistence(DocumentInitiationPersistence):
    """Atomically apply availability and initial ingestion under the File lock."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def apply_clean_scan(
        self,
        *,
        storage_key: str,
        source_entity_tag: str,
        expected_size_bytes: int,
        at: datetime,
    ) -> None:
        if (
            not is_canonical_file_storage_key(storage_key)
            or not isinstance(source_entity_tag, str)
            or not source_entity_tag.strip()
            or len(source_entity_tag) > 1024
            or isinstance(expected_size_bytes, bool)
            or not isinstance(expected_size_bytes, int)
            or expected_size_bytes < 0
            or at.tzinfo is None
            or at.utcoffset() is None
        ):
            raise DocumentInitiationConflictError("Document initiation conflicts")
        transaction = asyncio.create_task(
            self._execute(
                storage_key=storage_key,
                source_entity_tag=source_entity_tag,
                expected_size_bytes=expected_size_bytes,
                at=at,
            )
        )
        try:
            outcome = await asyncio.shield(transaction)
        except asyncio.CancelledError:
            await _settle_cancelled_transaction(transaction)
            raise
        logger.info(
            "document_initiation_settled",
            outcome=outcome,
            correlation=hashlib.sha256(storage_key.encode()).hexdigest()[:16],
        )

    async def _execute(
        self,
        *,
        storage_key: str,
        source_entity_tag: str,
        expected_size_bytes: int,
        at: datetime,
    ) -> str:
        try:
            async with self._session_factory.begin() as session:
                return await self._initiate(
                    session,
                    storage_key=storage_key,
                    source_entity_tag=source_entity_tag,
                    expected_size_bytes=expected_size_bytes,
                    at=at,
                )
        except SQLAlchemyError as exc:
            raise DocumentInitiationError("Document initiation failed") from exc

    async def _initiate(
        self,
        session: AsyncSession,
        *,
        storage_key: str,
        source_entity_tag: str,
        expected_size_bytes: int,
        at: datetime,
    ) -> str:
        file = await _file_queries.file_for_update(session, storage_key=storage_key)
        if file is None:
            # Malware results can arrive before upload registration commits.
            raise DocumentInitiationError("File is not ready for document initiation")
        if file.storage_status is FileStorageStatus.DELETING:
            return "deleting"
        request = await queries.request_for_file(session, file)
        if file.storage_status is FileStorageStatus.AVAILABLE:
            if request is None:
                return "historical_or_ineligible"
            if (
                request.source_entity_tag != source_entity_tag
                or request.expected_size_bytes != expected_size_bytes
                or file.size_bytes != expected_size_bytes
            ):
                raise DocumentInitiationConflictError("Document initiation conflicts")
            return "duplicate"
        if file.storage_status is not FileStorageStatus.PENDING:
            raise DocumentInitiationConflictError("Document initiation conflicts")
        if (
            request is not None
            or file.size_bytes != expected_size_bytes
            or await queries.has_document(session, file)
        ):
            raise DocumentInitiationConflictError("Document initiation conflicts")
        await _file_queries.update_file_storage_status(
            session,
            storage_key=storage_key,
            target_status=FileStorageStatus.AVAILABLE,
            updated_at=at,
        )
        document = initial_document(
            replace(file, storage_status=FileStorageStatus.AVAILABLE, updated_at=at),
            at=at,
        )
        if document is None:
            return "ineligible"
        await queries.insert_initial_request(
            session,
            document=document,
            source_entity_tag=source_entity_tag,
            expected_size_bytes=expected_size_bytes,
            at=at,
        )
        return "created"
