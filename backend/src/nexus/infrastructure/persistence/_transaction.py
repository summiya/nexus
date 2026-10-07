"""Cancellation settlement for shielded persistence transactions."""

import asyncio


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
