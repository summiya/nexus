"""SQLAlchemy implementation of the File persistence boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TypeVar
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.files.domain import File, FileStorageStatus
from nexus.files.ports import (
    FileIdentityConflictError,
    FileNotReadyError,
    FilePersistence,
    FilePersistenceError,
    FileStateConflictError,
)
from nexus.infrastructure.persistence import _file_queries as queries

T = TypeVar("T")

_FILE_IDENTITY_CONSTRAINTS = frozenset(
    {
        "uq_files_public_id",
        "uq_files_storage_key",
    }
)


class _FileIdentityRace(Exception):
    """An expected File identity constraint lost a concurrent insert race."""


class SqlAlchemyFilePersistence(FilePersistence):
    """Run each File persistence operation in a fresh async session."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def create_file(self, file: File) -> None:
        await self._run_transaction(lambda session: queries.insert_file(session, file))

    async def register_completed_upload(self, file: File) -> None:
        try:
            await self._run_transaction(
                lambda session: self._register_or_classify(
                    session,
                    file,
                    insert_when_absent=True,
                ),
                identity_race_constraints=_FILE_IDENTITY_CONSTRAINTS,
            )
        except _FileIdentityRace:
            await self._run_transaction(
                lambda session: self._register_or_classify(
                    session,
                    file,
                    insert_when_absent=False,
                )
            )

    async def apply_malware_scan_result(
        self,
        *,
        storage_key: str,
        target_status: FileStorageStatus,
        updated_at: datetime,
    ) -> None:
        await self._run_transaction(
            lambda session: self._apply_malware_scan_result(
                session,
                storage_key=storage_key,
                target_status=target_status,
                updated_at=updated_at,
            )
        )

    async def get_file(
        self,
        *,
        organization_public_id: UUID,
        file_public_id: UUID,
    ) -> File | None:
        return await self._run_read(
            lambda session: queries.get_file(
                session,
                organization_public_id=organization_public_id,
                file_public_id=file_public_id,
            )
        )

    async def list_files(
        self,
        *,
        organization_public_id: UUID,
        before_created_at: datetime | None,
        before_public_id: UUID | None,
        limit: int,
    ) -> tuple[File, ...]:
        return await self._run_read(
            lambda session: queries.list_files(
                session,
                organization_public_id=organization_public_id,
                before_created_at=before_created_at,
                before_public_id=before_public_id,
                limit=limit,
            )
        )

    async def _run_read(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
    ) -> T:
        try:
            async with self._session_factory() as session:
                return await operation(session)
        except SQLAlchemyError as exc:
            raise FilePersistenceError("File persistence failed") from exc

    async def _run_transaction(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
        *,
        identity_race_constraints: frozenset[str] = frozenset(),
    ) -> T:
        transaction = asyncio.create_task(
            self._execute_transaction(
                operation,
                identity_race_constraints=identity_race_constraints,
            )
        )
        try:
            return await asyncio.shield(transaction)
        except asyncio.CancelledError:
            await _settle_cancelled_transaction(transaction)
            raise

    async def _execute_transaction(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
        *,
        identity_race_constraints: frozenset[str],
    ) -> T:
        try:
            async with self._session_factory.begin() as session:
                return await operation(session)
        except IntegrityError as exc:
            if _constraint_name(exc) in identity_race_constraints:
                raise _FileIdentityRace from exc
            raise FilePersistenceError("File persistence failed") from exc
        except SQLAlchemyError as exc:
            raise FilePersistenceError("File persistence failed") from exc

    async def _apply_malware_scan_result(
        self,
        session: AsyncSession,
        *,
        storage_key: str,
        target_status: FileStorageStatus,
        updated_at: datetime,
    ) -> None:
        current_status = await queries.file_storage_status_for_update(
            session,
            storage_key=storage_key,
        )
        if current_status is None:
            raise FileNotReadyError("File is not ready for malware result")
        if current_status is target_status:
            return
        if current_status is not FileStorageStatus.PENDING:
            raise FileStateConflictError("File malware state conflicts")
        await queries.update_file_storage_status(
            session,
            storage_key=storage_key,
            target_status=target_status,
            updated_at=updated_at,
        )

    async def _register_or_classify(
        self,
        session: AsyncSession,
        file: File,
        *,
        insert_when_absent: bool,
    ) -> None:
        matches = await queries.files_matching_identity(
            session,
            file_public_id=file.public_id,
            storage_key=file.storage_key,
        )
        if not matches:
            if not insert_when_absent:
                raise FilePersistenceError("File persistence failed")
            await queries.insert_file(session, file)
            return

        if len(matches) == 1:
            existing = matches[0]
            identities_match = (
                existing.public_id == file.public_id
                and existing.storage_key == file.storage_key
            )
            ownership_matches = (
                existing.organization_public_id == file.organization_public_id
                and existing.created_by_user_public_id == file.created_by_user_public_id
            )
            if identities_match and ownership_matches:
                return

        raise FileIdentityConflictError("File completion identity conflicts")


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
