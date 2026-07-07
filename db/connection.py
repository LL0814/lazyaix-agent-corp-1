from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg


async def create_pool(dsn: str | None = None) -> asyncpg.Pool:
    dsn = dsn or os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    return await asyncpg.create_pool(dsn)


@asynccontextmanager
async def get_pool(dsn: str | None = None) -> AsyncIterator[asyncpg.Pool]:
    pool = await create_pool(dsn)
    try:
        yield pool
    finally:
        await pool.close()
