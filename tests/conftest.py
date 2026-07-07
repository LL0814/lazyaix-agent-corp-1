import os

import asyncpg
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def postgres_pool():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL not set")
    pool = await asyncpg.create_pool(dsn)
    async with pool.acquire() as conn:
        with open("db/schema.sql") as f:
            await conn.execute(f.read())
    try:
        yield pool
    finally:
        await pool.close()
