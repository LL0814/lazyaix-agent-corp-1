from __future__ import annotations

import os

import pytest

from db.redis_idempotency import RedisIdempotencyStore


@pytest.fixture
def redis_client():
    url = os.environ.get("REDIS_URL")
    if not url:
        pytest.skip("REDIS_URL not set")
    from redis.asyncio import Redis

    client = Redis.from_url(url, decode_responses=True)
    return client


@pytest.mark.asyncio
async def test_redis_idempotency_acquire(redis_client):
    try:
        await redis_client.ping()
    except Exception as exc:
        pytest.skip(f"Redis not reachable: {exc}")

    store = RedisIdempotencyStore(redis_client, key_prefix="test_dispatched")
    key = "wf:test:task:0"
    await redis_client.delete(store._key(key))

    assert await store.acquire(key, ttl_seconds=60) is True
    assert await store.acquire(key, ttl_seconds=60) is False
    await redis_client.aclose()


@pytest.mark.asyncio
async def test_redis_idempotency_fail_open_on_error():
    class BrokenRedis:
        async def set(self, *args, **kwargs):
            raise RuntimeError("redis down")

    store = RedisIdempotencyStore(BrokenRedis())
    assert await store.acquire("wf:test:task:0", ttl_seconds=60) is True
