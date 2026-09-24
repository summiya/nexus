"""Transaction boundary contracts."""

from __future__ import annotations

from typing import Protocol


class TransactionManager(Protocol):
    """Minimal transaction boundary owned by application use cases."""

    async def commit(self) -> None:
        """Commit pending transaction state."""

    async def rollback(self) -> None:
        """Roll back pending transaction state."""
