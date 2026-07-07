"""Redis-backed idempotency store for Scheduler dispatch deduplication."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RedisIdempotencyStore:
    """Distributed idempotency store using Redis SET NX EX.

    The store is designed to be an optimisation and coordination aid, not the
    single source of truth for dispatch state. If Redis is unavailable, callers
    should fall back to the database-level checks (e.g. task status and
    processed_events) before executing an agent task.
    """

    def __init__(self, redis: Any, key_prefix: str = "dispatched"):
        self._redis = redis
        self._key_prefix = key_prefix

    def _key(self, dispatch_key: str) -> str:
        return f"{self._key_prefix}:{dispatch_key}"

    async def acquire(self, key: str, ttl_seconds: int) -> bool:
        try:
            result = await self._redis.set(
                self._key(key),
                "1",
                nx=True,
                ex=ttl_seconds,
            )
            return result is True
        except Exception:
            logger.exception("Redis idempotency check failed for key %s", key)
            # Fail open: a missed dedup will be caught by the database state
            # and processed_events checks downstream.
            return True
