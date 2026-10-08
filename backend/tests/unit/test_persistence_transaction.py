import asyncio

import pytest

from nexus.infrastructure.persistence._transaction import _settle_cancelled_transaction


@pytest.mark.parametrize("outcome", ["committed", "rolled_back", "cancelled"])
def test_settlement_waits_through_repeated_cancellation(outcome):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        async def transaction():
            entered.set()
            await release.wait()
            if outcome == "rolled_back":
                raise RuntimeError("rollback")
            if outcome == "cancelled":
                raise asyncio.CancelledError()

        task = asyncio.create_task(transaction())
        await entered.wait()
        waiter = asyncio.create_task(_settle_cancelled_transaction(task))
        await asyncio.sleep(0)
        for _ in range(2):
            waiter.cancel()
            await asyncio.sleep(0)
            assert not waiter.done()
            assert not task.done()
        release.set()
        await waiter
        assert task.done()
        assert task.cancelled() == (outcome == "cancelled")

    asyncio.run(run())
