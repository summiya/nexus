"""SQLAlchemy implementation of the Document persistence boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TypeVar
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.documents.domain import Document
from nexus.documents.ports import (
    DocumentConflictError,
    DocumentPersistence,
    DocumentPersistenceError,
)
from nexus.infrastructure.persistence import _document_queries as queries

T = TypeVar("T")

_DOCUMENT_CONFLICT_CONSTRAINTS = frozenset(
    {
        "uq_documents_public_id",
        "uq_documents_active_source_file_id",
    }
)


class SqlAlchemyDocumentPersistence(DocumentPersistence):
    """Run each Document persistence operation in a fresh async session."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_document(self, document: Document) -> None:
        await self._run_transaction(
            lambda session: queries.insert_document(session, document)
        )

    async def get_document(
        self,
        *,
        organization_public_id: UUID,
        document_public_id: UUID,
    ) -> Document | None:
        return await self._run_read(
            lambda session: queries.get_document(
                session,
                organization_public_id=organization_public_id,
                document_public_id=document_public_id,
            )
        )

    async def update_document(
        self,
        *,
        expected: Document,
        document: Document,
    ) -> None:
        await self._run_transaction(
            lambda session: self._replace_snapshot(
                session,
                expected=expected,
                document=document,
            )
        )

    async def _replace_snapshot(
        self,
        session: AsyncSession,
        *,
        expected: Document,
        document: Document,
    ) -> None:
        locked = await queries.document_for_update(
            session,
            organization_public_id=expected.organization_public_id,
            document_public_id=expected.public_id,
        )
        if locked is None:
            raise DocumentConflictError("Document persistence conflict")
        model, current = locked
        if (
            current != expected
            or _identity(document) != _identity(expected)
            or not expected.is_immediate_successor(document)
        ):
            raise DocumentConflictError("Document persistence conflict")
        await queries.replace_document_snapshot(
            session,
            model=model,
            document=document,
        )

    async def _run_read(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
    ) -> T:
        try:
            async with self._session_factory() as session:
                return await operation(session)
        except SQLAlchemyError as exc:
            raise DocumentPersistenceError("Document persistence failed") from exc

    async def _run_transaction(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
    ) -> T:
        transaction = asyncio.create_task(self._execute_transaction(operation))
        try:
            return await asyncio.shield(transaction)
        except asyncio.CancelledError:
            await _settle_cancelled_transaction(transaction)
            raise

    async def _execute_transaction(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
    ) -> T:
        try:
            async with self._session_factory.begin() as session:
                return await operation(session)
        except IntegrityError as exc:
            if _constraint_name(exc) in _DOCUMENT_CONFLICT_CONSTRAINTS:
                raise DocumentConflictError("Document persistence conflict") from exc
            raise DocumentPersistenceError("Document persistence failed") from exc
        except SQLAlchemyError as exc:
            raise DocumentPersistenceError("Document persistence failed") from exc


def _identity(document: Document) -> tuple[UUID, UUID, UUID, datetime]:
    return (
        document.public_id,
        document.organization_public_id,
        document.source_file_public_id,
        document.created_at,
    )


def _constraint_name(exc: IntegrityError) -> str | None:
    diagnostic = getattr(exc.orig, "diag", None)
    name = getattr(diagnostic, "constraint_name", None)
    return name if isinstance(name, str) else None


async def _settle_cancelled_transaction(transaction: asyncio.Task[object]) -> None:
    """Wait until a shielded transaction has committed or rolled back."""
    while not transaction.done():
        try:
            await asyncio.shield(transaction)
        except asyncio.CancelledError:
            continue
        except BaseException:  # noqa: BLE001 - cancellation remains authoritative
            return

    if transaction.cancelled():
        return
    transaction.exception()
