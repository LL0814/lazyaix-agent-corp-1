import os

import asyncpg
import pytest
import pytest_asyncio


def _start_postgres_container():
    try:
        from testcontainers.postgres import PostgresContainer
    except Exception:
        return None, None

    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
        return container, container.get_connection_url()
    except Exception:
        return None, None


@pytest_asyncio.fixture
async def postgres_pool():
    container = None
    dsn = os.environ.get("TEST_DATABASE_URL")

    if not dsn:
        container, raw_dsn = _start_postgres_container()
        if raw_dsn:
            dsn = raw_dsn.replace("postgresql+psycopg2://", "postgresql://")

    if not dsn:
        pytest.skip("No PostgreSQL available: Docker not running and TEST_DATABASE_URL not set")

    pool = await asyncpg.create_pool(dsn)
    async with pool.acquire() as conn:
        with open("db/schema.sql") as f:
            await conn.execute(f.read())
    try:
        yield pool
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE TABLE processed_events, outbox_events, event_store, dlq, "
                "task_dependencies, tasks, workflows "
                "RESTART IDENTITY CASCADE;"
            )
        await pool.close()
        if container is not None:
            container.stop()
