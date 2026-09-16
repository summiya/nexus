"""Small rate-limit boundary for abuse-sensitive authentication endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from redis import Redis
from redis.exceptions import RedisError


class RateLimitError(Exception):
    """Raised when the rate limiter cannot make a safe decision."""


class RateLimiter(Protocol):
    """Focused rate-limiter contract."""

    def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        """Return whether the key is allowed within the configured window."""


@dataclass(frozen=True)
class RedisRateLimiter:
    """Redis-backed fixed-window rate limiter."""

    redis: Redis

    @classmethod
    def from_url(cls, redis_url: str) -> RedisRateLimiter:
        return cls(redis=Redis.from_url(redis_url, decode_responses=True))

    def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        try:
            value = cast(int, self.redis.incr(key))
            if value == 1:
                self.redis.expire(key, window_seconds)
            return value <= limit
        except RedisError as exc:
            raise RateLimitError("Rate limiter is unavailable") from exc
