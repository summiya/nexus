"""SQLAlchemy implementation of the File persistence boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.files.domain import File
from nexus.files.ports import FilePersistence, FilePersistenceError
from nexus.infrastructure.persistence import _file_queries as queries

T = TypeVar("T")


class SqlAlchemyFilePersistence(FilePersistence):
    """Run each File persistence operation in a fresh async session."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def create_file(self, file: File) -> None:
        await self._run_transaction(lambda session: queries.insert_file(session, file))

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
        except SQLAlchemyError as exc:
            raise FilePersistenceError("File persistence failed") from exc


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
