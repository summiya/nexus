from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.infrastructure.persistence.transaction import SqlAlchemyTransactionManager


def test_commit_awaits_async_session() -> None:
    session = Mock(spec=AsyncSession)
    session.commit = AsyncMock()

    asyncio.run(SqlAlchemyTransactionManager(session).commit())

    session.commit.assert_awaited_once_with()


def test_rollback_awaits_async_session() -> None:
    session = Mock(spec=AsyncSession)
    session.rollback = AsyncMock()

    asyncio.run(SqlAlchemyTransactionManager(session).rollback())

    session.rollback.assert_awaited_once_with()


@pytest.mark.parametrize("operation_name", ["commit", "rollback"])
def test_cancellation_waits_for_finalization_to_settle_before_propagating(
    operation_name: str,
) -> None:
    async def run() -> None:
        finalization_started = asyncio.Event()
        release_finalization = asyncio.Event()
        finalization_finished = asyncio.Event()

        async def finalization() -> None:
            finalization_started.set()
            await release_finalization.wait()
            finalization_finished.set()

        session = Mock(spec=AsyncSession)
        operation = AsyncMock(side_effect=finalization)
        setattr(session, operation_name, operation)
        transaction = SqlAlchemyTransactionManager(session)

        transaction_operation = getattr(transaction, operation_name)
        finalization_task = asyncio.create_task(transaction_operation())
        await finalization_started.wait()
        finalization_task.cancel()
        await asyncio.sleep(0)

        assert not finalization_task.done()
        assert not finalization_finished.is_set()

        release_finalization.set()
        with pytest.raises(asyncio.CancelledError):
            await finalization_task

        assert finalization_finished.is_set()
        operation.assert_awaited_once_with()

    asyncio.run(run())
