"""Transaction boundary contracts."""

from __future__ import annotations

from typing import Protocol


class TransactionManager(Protocol):
    """Minimal transaction boundary owned by application use cases."""

    def commit(self) -> None:
        """Commit pending transaction state."""

    def rollback(self) -> None:
        """Roll back pending transaction state."""
