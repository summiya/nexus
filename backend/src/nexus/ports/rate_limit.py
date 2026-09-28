"""Application-neutral rate-limit capability."""

from __future__ import annotations

from typing import Protocol


class RateLimitError(Exception):
    """Raised when the rate limiter cannot make a safe decision."""


class RateLimiter(Protocol):
    """Decide whether an action is allowed within a fixed window."""

    async def allow(self, *, key: str, limit: int, window_seconds: int) -> bool: ...


__all__ = ["RateLimitError", "RateLimiter"]
