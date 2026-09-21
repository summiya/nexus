"""Small rate-limit boundary for abuse-sensitive authentication endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from redis import Redis
from redis.exceptions import RedisError

from nexus.application.authentication.gateways import RateLimitError

_FIXED_WINDOW_RATE_LIMIT_SCRIPT = """
local current = redis.call("INCR", KEYS[1])
if current == 1 then
  redis.call("EXPIRE", KEYS[1], ARGV[2])
end
if current <= tonumber(ARGV[1]) then
  return 1
end
return 0
"""


@dataclass(frozen=True)
class RedisRateLimiter:
    """Application-scoped Redis-backed fixed-window rate limiter."""

    redis: Redis

    @classmethod
    def from_url(cls, redis_url: str) -> RedisRateLimiter:
        return cls(redis=Redis.from_url(redis_url, decode_responses=True))

    def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        try:
            allowed = cast(
                int,
                self.redis.eval(
                    _FIXED_WINDOW_RATE_LIMIT_SCRIPT,
                    1,
                    key,
                    str(limit),
                    str(window_seconds),
                ),
            )
            return allowed == 1
        except RedisError as exc:
            raise RateLimitError("Rate limiter is unavailable") from exc

    def close(self) -> None:
        self.redis.close()
