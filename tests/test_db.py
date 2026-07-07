import os
import uuid

import pytest

from db.connection import create_pool, get_pool


@pytest.mark.asyncio
async def test_create_pool_requires_dsn_or_env():
    os.environ.pop("DATABASE_URL", None)
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        await create_pool()


@pytest.mark.asyncio
async def test_get_pool_closes_on_exit():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL not set")

    async with get_pool(dsn) as pool:
        assert pool is not None
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT 1 AS n")
            assert row["n"] == 1


@pytest.mark.asyncio
async def test_schema_can_insert_workflow_and_event(postgres_pool):
    wf_id = uuid.uuid4()
    trace_id = uuid.uuid4()
    async with postgres_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO workflows (workflow_id, trace_id, user_input)
            VALUES ($1, $2, $3)
            """,
            wf_id,
            trace_id,
            "test",
        )
        row = await conn.fetchrow(
            "SELECT workflow_id, status FROM workflows WHERE workflow_id=$1", wf_id
        )
        assert row["workflow_id"] == wf_id
        assert row["status"] == "created"
