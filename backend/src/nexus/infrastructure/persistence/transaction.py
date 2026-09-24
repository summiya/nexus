"""SQLAlchemy transaction boundary adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyTransactionManager:
    """Transaction manager backed by one SQLAlchemy async session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await _settle_finalization(self._session.commit())

    async def rollback(self) -> None:
        await _settle_finalization(self._session.rollback())


async def _settle_finalization(
    operation: Coroutine[Any, Any, None],
) -> None:
    """Do not abandon an in-progress commit or rollback on caller cancellation."""

    finalization: asyncio.Task[None] = asyncio.create_task(operation)
    try:
        await asyncio.shield(finalization)
    except asyncio.CancelledError:
        await _settle_cancelled_finalization(finalization)
        raise


async def _settle_cancelled_finalization(finalization: asyncio.Task[None]) -> None:
    while not finalization.done():
        try:
            await asyncio.shield(finalization)
        except asyncio.CancelledError:
            continue
        except BaseException:  # noqa: BLE001 - caller cancellation remains authoritative
            return

    if finalization.cancelled():
        return
    finalization.exception()
