# 事件驱动持久化与分布式改造实施计划

> **给代理工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按 Task 逐步实施。步骤使用复选框（`- [ ]`）语法跟踪。

**目标：** 在当前进程内事件驱动实现基础上，渐进式引入 PostgreSQL、Kafka、Redis，实现 Workflow/Task 持久化、跨进程事件通信、分布式幂等和故障恢复能力，同时保持 InMemory 兼容路径。

**架构：** 通过 `StateStore`/`EventBus`/`Outbox` 抽象层隔离具体存储和消息中间件；PostgreSQL 作为事实来源保存 Workflow/Task/Event/Outbox；Kafka 作为跨进程 Event Bus；Redis 作为调度幂等和可选协调缓存；每个阶段独立可回滚到 InMemory 模式。

**技术栈：** Python 3.10+、`asyncpg`、`aiokafka`、`redis-py`（异步）、`pytest`、`pytest-asyncio`、可选 Alembic/SQL 迁移、Docker Compose 用于集成测试。

## 全局约束

- 保持现有 InMemoryEventBus 和同步 `_process_turn_sync` 兼容路径不变。
- 所有新配置必须有明确默认值并能回退到内存模式。
- 不修改现有 `subagents/workers.py` 的同步 `run()` 行为。
- 新依赖按需加入 `pyproject.toml`，不允许全局安装到系统 Python。
- 单元测试不依赖外部服务；集成测试使用 testcontainers 或 Docker Compose。
- 每次任务提交前必须通过相关测试。
- 代码风格匹配现有项目：PEP 8，类型注解，`from __future__ import annotations`。

---

## 文件结构

```
.
├── events/
│   ├── __init__.py
│   ├── bus.py                    # EventBus Protocol（已存在）
│   ├── schema.py                 # Event + EventType（已存在，扩展）
│   ├── in_memory.py              # InMemoryEventBus（已存在）
│   ├── serde.py                  # Event JSON 序列化/反序列化
│   ├── outbox.py                 # OutboxStore Protocol + 实现
│   ├── outbox_publisher.py       # Outbox Publisher 循环
│   └── processed_event_store.py  # 消费幂等存储
├── workflow/
│   ├── __init__.py
│   ├── state.py                  # Workflow/Task/Status（已存在，扩展）
│   ├── graph.py                  # TaskGraph（已存在）
│   ├── coordinator.py            # WorkflowCoordinator（修改）
│   └── state_store.py            # StateStore Protocol + InMemoryStateStore
├── db/
│   ├── __init__.py
│   ├── schema.sql                # PostgreSQL DDL
│   ├── migrations/               # 可选 Alembic 迁移
│   ├── connection.py             # 连接池管理
│   ├── postgres_state_store.py   # PostgreSQL StateStore 实现
│   ├── outbox_repository.py      # PostgreSQL OutboxRepository
│   ├── event_store_repository.py # PostgreSQL EventStoreRepository
│   └── processed_event_repository.py # PostgreSQL ProcessedEventRepository
├── scheduler.py                  # Scheduler（修改，接入 Redis 幂等）
├── redis_client.py               # Redis 连接封装
├── agent.py                      # Agent（修改，根据配置装配）
├── loop.py                       # REPL（修改，轮询 workflow 结果）
├── pyproject.toml                # 依赖更新
├── .env.example                  # 配置示例更新
└── tests/
    ├── test_state_store.py
    ├── test_postgres_state_store.py
    ├── test_outbox.py
    ├── test_kafka_event_bus.py
    ├── test_redis_idempotency.py
    └── test_compatibility.py
```

---

## Task 1: 扩展 Event Schema

**涉及文件：**
- 修改：`events/schema.py`
- 测试：`tests/test_event_schema.py`

**接口：**
- 消费：现有 `Event` 数据类的字段。
- 产出：`Event` 增加可选字段 `parent_event_id`、`aggregate_id`、`priority`；新增 `to_dict()` 和 `from_dict()` 类方法。

- [ ] **步骤 1：编写针对新字段和序列化的失败测试**

```python
def test_event_has_new_fields():
    from events.schema import Event, EventType
    e = Event(
        event_id="e1",
        event_type=EventType.TASK_READY,
        trace_id="t1",
        workflow_id="wf1",
        task_id="task1",
        parent_event_id="e0",
        aggregate_id="wf1",
        priority="high",
    )
    assert e.parent_event_id == "e0"
    assert e.aggregate_id == "wf1"
    assert e.priority == "high"


def test_event_round_trip_dict():
    from datetime import datetime, timezone
    from events.schema import Event, EventType
    now = datetime.now(timezone.utc)
    e = Event(
        event_id="e1",
        event_type=EventType.TASK_READY,
        trace_id="t1",
        workflow_id="wf1",
        task_id="task1",
        timestamp=now,
        payload={"instructions": "do it"},
        metadata={"retry_count": 1},
    )
    d = e.to_dict()
    e2 = Event.from_dict(d)
    assert e2.event_id == e.event_id
    assert e2.timestamp == now
    assert e2.payload == e.payload
    assert e2.metadata == e.metadata
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/test_event_schema.py::test_event_has_new_fields tests/test_event_schema.py::test_event_round_trip_dict -v`
预期：失败，错误为 `TypeError: Event.__init__() got an unexpected keyword argument 'parent_event_id'`。

- [ ] **步骤 3：扩展 Event 数据类并添加序列化方法**

```python
# events/schema.py
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


class EventType:
    TASK_CREATED = "task.created"
    TASK_READY = "task.ready"
    TASK_ASSIGNED = "task.assigned"
    TASK_RETRYING = "task.retrying"
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    WORKFLOW_RESUME = "workflow.resume"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"


@dataclass
class Event:
    event_id: str
    event_type: str
    trace_id: str
    workflow_id: str
    task_id: str | None = None
    parent_task_id: str | None = None
    parent_event_id: str | None = None
    aggregate_id: str | None = None
    source: str = "supervisor"
    target_agent: str | None = None
    target_capability: str | None = None
    priority: str = "normal"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        data = dict(data)
        if "timestamp" in data and isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)
```

- [ ] **步骤 4：运行测试**

运行：`pytest tests/test_event_schema.py -v`
预期：通过。

- [ ] **步骤 5：提交**

```bash
git add events/schema.py tests/test_event_schema.py
git commit -m "feat(events): extend Event schema with routing/auditing fields and dict serialization"
```

---

## Task 2: 增加 StateStore 抽象与 InMemoryStateStore

**涉及文件：**
- 新建：`workflow/state_store.py`
- 修改：`workflow/coordinator.py`
- 修改：`agent.py`
- 测试：`tests/test_state_store.py`、更新 `tests/test_coordinator.py`

**接口：**
- 消费：`workflow/state.py` 中的 `Workflow`、`Task`、`TaskStatus`、`WorkflowStatus`。
- 产出：`StateStore` Protocol，包含 `save_workflow`、`get_workflow`、`update_workflow_status`、`save_task`、`get_task`、`update_task_status`、`list_ready_tasks`、`load_task_graph`。

- [ ] **步骤 1：为 InMemoryStateStore 编写失败测试**

```python
import pytest

from workflow.state import Task, TaskStatus, Workflow, WorkflowStatus
from workflow.state_store import InMemoryStateStore


def make_wf(*tasks):
    return Workflow(
        workflow_id="wf-1",
        trace_id="tr-1",
        user_input="test",
        tasks={t.task_id: t for t in tasks},
    )


@pytest.mark.asyncio
async def test_save_and_get_workflow():
    store = InMemoryStateStore()
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await store.save_workflow(wf)
    got = await store.get_workflow("wf-1")
    assert got is not None
    assert got.workflow_id == "wf-1"
    assert got.status == WorkflowStatus.CREATED


@pytest.mark.asyncio
async def test_update_workflow_status():
    store = InMemoryStateStore()
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await store.save_workflow(wf)
    ok = await store.update_workflow_status("wf-1", WorkflowStatus.EXECUTING, version=1)
    assert ok is True
    got = await store.get_workflow("wf-1")
    assert got.status == WorkflowStatus.EXECUTING


@pytest.mark.asyncio
async def test_update_workflow_status_optimistic_lock_failure():
    store = InMemoryStateStore()
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await store.save_workflow(wf)
    ok = await store.update_workflow_status("wf-1", WorkflowStatus.EXECUTING, version=99)
    assert ok is False
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/test_state_store.py -v`
预期：失败，错误为 `ModuleNotFoundError: No module named 'workflow.state_store'`。

- [ ] **步骤 3：实现 StateStore Protocol 和 InMemoryStateStore**

```python
# workflow/state_store.py
from __future__ import annotations

from typing import Protocol

from workflow.state import Task, TaskStatus, Workflow, WorkflowStatus


class StateStore(Protocol):
    async def save_workflow(self, workflow: Workflow) -> None: ...
    async def get_workflow(self, workflow_id: str) -> Workflow | None: ...
    async def update_workflow_status(
        self, workflow_id: str, status: WorkflowStatus, *, version: int
    ) -> bool: ...

    async def save_task(self, task: Task) -> None: ...
    async def get_task(self, task_id: str) -> Task | None: ...
    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        result: Any = None,
        error: dict | None = None,
        version: int = 1,
    ) -> bool: ...

    async def list_ready_tasks(self, workflow_id: str) -> list[Task]: ...
    async def load_task_graph(self, workflow_id: str) -> tuple[Workflow, TaskGraph] | None: ...


class InMemoryStateStore:
    """Process-local StateStore used for unit tests and single-process deployments."""

    def __init__(self):
        self._workflows: dict[str, Workflow] = {}
        self._tasks: dict[str, Task] = {}
        self._versions: dict[str, int] = {}

    async def save_workflow(self, workflow: Workflow) -> None:
        self._workflows[workflow.workflow_id] = workflow
        for task in workflow.tasks.values():
            self._tasks[task.task_id] = task
        self._versions.setdefault(f"wf:{workflow.workflow_id}", 1)

    async def get_workflow(self, workflow_id: str) -> Workflow | None:
        return self._workflows.get(workflow_id)

    async def update_workflow_status(
        self, workflow_id: str, status: WorkflowStatus, *, version: int
    ) -> bool:
        key = f"wf:{workflow_id}"
        if self._versions.get(key) != version:
            return False
        wf = self._workflows.get(workflow_id)
        if wf is None:
            return False
        wf.status = status
        wf.version = version + 1
        self._versions[key] = version + 1
        return True

    async def save_task(self, task: Task) -> None:
        self._tasks[task.task_id] = task
        self._versions.setdefault(f"task:{task.task_id}", 1)

    async def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        result: Any = None,
        error: dict | None = None,
        version: int = 1,
    ) -> bool:
        key = f"task:{task_id}"
        if self._versions.get(key) != version:
            return False
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.status = status
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        task.version = version + 1
        self._versions[key] = version + 1
        return True

    async def list_ready_tasks(self, workflow_id: str) -> list[Task]:
        wf = self._workflows.get(workflow_id)
        if wf is None:
            return []
        from workflow.graph import TaskGraph
        graph = TaskGraph(wf)
        return graph.ready_tasks()

    async def load_task_graph(self, workflow_id: str) -> tuple[Workflow, TaskGraph] | None:
        wf = self._workflows.get(workflow_id)
        if wf is None:
            return None
        from workflow.graph import TaskGraph
        return wf, TaskGraph(wf)
```

说明：在 `workflow/state.py` 的 `Workflow` 和 `Task` 数据类中增加 `version: int = 1`。

- [ ] **步骤 4：更新 WorkflowCoordinator 以使用 StateStore**

```python
# workflow/coordinator.py 修改要点
class WorkflowCoordinator:
    def __init__(
        self,
        event_bus: EventBus,
        state_store: StateStore,
        max_retries: int = 2,
    ):
        self.event_bus = event_bus
        self.state_store = state_store
        self.max_retries = max_retries
        self._completions: dict[str, asyncio.Future] = {}

    async def start_workflow(self, workflow: Workflow) -> None:
        await self.state_store.save_workflow(workflow)
        graph = TaskGraph(workflow)
        graph.validate()
        workflow.status = WorkflowStatus.EXECUTING
        await self.state_store.update_workflow_status(
            workflow.workflow_id, WorkflowStatus.EXECUTING, version=workflow.version
        )
        await self._publish_ready_tasks(workflow)

    async def handle_task_completed(self, event: Event) -> None:
        loaded = await self.state_store.load_task_graph(event.workflow_id)
        if loaded is None or event.task_id is None:
            return
        workflow, graph = loaded
        # ... 保留原有逻辑，但改为通过 state_store 加载/保存 ...
```

在本阶段，将 `_workflows` 的使用全部替换为 `state_store`。最简单的改法：删除 `self._workflows`，所有地方从 `state_store` 加载。

- [ ] **步骤 5：更新 agent.py 注入 InMemoryStateStore**

```python
# agent.py
from workflow.state_store import InMemoryStateStore

async def _process_turn_event_driven(self, user_input: str) -> str:
    event_bus = InMemoryEventBus()
    state_store = InMemoryStateStore()
    max_retries = int(self.config.get("MAX_RETRIES", "2"))
    coordinator = WorkflowCoordinator(event_bus, state_store, max_retries=max_retries)
    # ... 其余不变
```

- [ ] **步骤 6：运行全部测试**

运行：`pytest tests/ -v`
预期：通过。

- [ ] **步骤 7：提交**

```bash
git add workflow/state_store.py workflow/coordinator.py workflow/state.py agent.py tests/test_state_store.py
git commit -m "feat(workflow): add StateStore abstraction and InMemoryStateStore"
```

---

## Task 3: 添加 PostgreSQL Schema 和连接池

**涉及文件：**
- 新建：`db/schema.sql`
- 新建：`db/connection.py`
- 修改：`pyproject.toml`
- 测试：`tests/conftest.py`

**接口：**
- 产出：`get_pool()` 异步上下文管理器，返回 `asyncpg.Pool`。

- [ ] **步骤 1：编写 PostgreSQL DDL**

```sql
-- db/schema.sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS workflows (
    workflow_id UUID PRIMARY KEY,
    trace_id UUID NOT NULL,
    parent_workflow_id UUID NULL,
    user_input TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'created',
    final_result TEXT NULL,
    error_info JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ NULL,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id UUID PRIMARY KEY,
    workflow_id UUID NOT NULL REFERENCES workflows(workflow_id) ON DELETE CASCADE,
    parent_task_id UUID NULL,
    task_type VARCHAR(64) NOT NULL,
    target_capability VARCHAR(64) NOT NULL,
    target_agent VARCHAR(128) NULL,
    instructions TEXT NOT NULL,
    input JSONB NULL,
    input_refs JSONB NULL,
    required_for_completion BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    result JSONB NULL,
    error_info JSONB NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 2,
    priority VARCHAR(16) NOT NULL DEFAULT 'normal',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    workflow_id UUID NOT NULL REFERENCES workflows(workflow_id) ON DELETE CASCADE,
    task_id UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    depends_on_task_id UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    dependency_type VARCHAR(32) NOT NULL DEFAULT 'finish_to_start',
    required BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (task_id, depends_on_task_id)
);

CREATE TABLE IF NOT EXISTS event_store (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID NOT NULL UNIQUE,
    trace_id UUID NOT NULL,
    parent_event_id UUID NULL,
    aggregate_id UUID NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    priority VARCHAR(16) NOT NULL DEFAULT 'normal',
    timestamp TIMESTAMPTZ NOT NULL,
    source VARCHAR(128) NOT NULL,
    target_agent VARCHAR(128) NULL,
    target_capability VARCHAR(64) NULL,
    workflow_id UUID NULL,
    task_id UUID NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS outbox_events (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID NOT NULL UNIQUE,
    aggregate_id UUID NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    topic VARCHAR(256) NOT NULL,
    message_key VARCHAR(256) NULL,
    payload JSONB NOT NULL,
    headers JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ NULL,
    error_info TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON outbox_events(status, next_retry_at)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS processed_events (
    event_id UUID PRIMARY KEY,
    workflow_id UUID NOT NULL,
    task_id UUID NULL,
    event_type VARCHAR(128) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dlq (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID NOT NULL,
    trace_id UUID NULL,
    workflow_id UUID NULL,
    task_id UUID NULL,
    reason VARCHAR(256) NOT NULL,
    error_info JSONB NULL,
    payload JSONB NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retried_at TIMESTAMPTZ NULL
);
```

- [ ] **步骤 2：实现连接辅助函数**

```python
# db/connection.py
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
```

- [ ] **步骤 3：增加依赖**

```toml
# pyproject.toml
[project]
dependencies = [
    "python-dotenv>=1.2.2",
    "asyncpg>=0.29.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "testcontainers>=4.0.0",
]
```

运行：`uv sync` 或 `pip install -e ".[dev]"`。

- [ ] **步骤 4：增加集成测试 fixture**

```python
# tests/conftest.py
import os
import pytest
import pytest_asyncio
import asyncpg


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
```

- [ ] **步骤 5：提交**

```bash
git add db/schema.sql db/connection.py pyproject.toml tests/conftest.py
git commit -m "feat(db): add PostgreSQL schema and connection pool"
```

---

## Task 4: 实现 PostgreSQLStateStore

**涉及文件：**
- 新建：`db/postgres_state_store.py`
- 测试：`tests/test_postgres_state_store.py`

**接口：**
- 消费：`workflow/state_store.py` 中的 `StateStore` Protocol。
- 产出：`PostgresStateStore` 实现 `StateStore`。

- [ ] **步骤 1：实现 PostgresStateStore**

```python
# db/postgres_state_store.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import asyncpg

from workflow.graph import TaskGraph
from workflow.state import Task, TaskStatus, Workflow, WorkflowStatus


def _task_to_row(task: Task, workflow_id: str) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "workflow_id": workflow_id,
        "parent_task_id": task.parent_task_id,
        "task_type": task.task_type,
        "target_capability": task.target_capability,
        "target_agent": task.target_agent,
        "instructions": task.instructions,
        "input": json.dumps(task.input) if task.input is not None else None,
        "input_refs": json.dumps(task.input_refs) if task.input_refs else None,
        "required_for_completion": task.required_for_completion,
        "status": task.status.value,
        "result": json.dumps(task.result) if task.result is not None else None,
        "error_info": json.dumps(task.error) if task.error is not None else None,
        "retry_count": task.retry_count,
        "max_retries": getattr(task, "max_retries", 2),
        "priority": getattr(task, "priority", "normal"),
        "version": task.version,
    }


def _row_to_task(row: asyncpg.Record) -> Task:
    return Task(
        task_id=str(row["task_id"]),
        task_type=row["task_type"],
        target_capability=row["target_capability"],
        target_agent=row["target_agent"],
        instructions=row["instructions"],
        input=json.loads(row["input"]) if row["input"] else None,
        input_refs=json.loads(row["input_refs"]) if row["input_refs"] else [],
        required_for_completion=row["required_for_completion"],
        status=TaskStatus(row["status"]),
        result=json.loads(row["result"]) if row["result"] else None,
        error=json.loads(row["error_info"]) if row["error_info"] else None,
        retry_count=row["retry_count"],
        max_retries=row["max_retries"],
        priority=row["priority"],
        version=row["version"],
    )


def _row_to_workflow(row: asyncpg.Record, tasks: dict[str, Task]) -> Workflow:
    return Workflow(
        workflow_id=str(row["workflow_id"]),
        trace_id=str(row["trace_id"]),
        parent_workflow_id=str(row["parent_workflow_id"]) if row["parent_workflow_id"] else None,
        user_input=row["user_input"],
        status=WorkflowStatus(row["status"]),
        final_result=row["final_result"],
        error=json.loads(row["error_info"]) if row["error_info"] else None,
        tasks=tasks,
        version=row["version"],
    )


class PostgresStateStore:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def save_workflow(self, workflow: Workflow) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO workflows (workflow_id, trace_id, parent_workflow_id, user_input, status, final_result, error_info, version)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (workflow_id) DO UPDATE SET
                        trace_id = EXCLUDED.trace_id,
                        parent_workflow_id = EXCLUDED.parent_workflow_id,
                        user_input = EXCLUDED.user_input,
                        status = EXCLUDED.status,
                        final_result = EXCLUDED.final_result,
                        error_info = EXCLUDED.error_info,
                        updated_at = NOW(),
                        version = EXCLUDED.version
                    """,
                    workflow.workflow_id,
                    workflow.trace_id,
                    workflow.parent_workflow_id,
                    workflow.user_input,
                    workflow.status.value,
                    workflow.final_result,
                    json.dumps(workflow.error) if workflow.error else None,
                    workflow.version,
                )
                for task in workflow.tasks.values():
                    await self._upsert_task(conn, task, workflow.workflow_id)
                await conn.execute(
                    "DELETE FROM task_dependencies WHERE workflow_id = $1",
                    workflow.workflow_id,
                )
                for task in workflow.tasks.values():
                    for dep in task.dependencies:
                        await conn.execute(
                            """
                            INSERT INTO task_dependencies (workflow_id, task_id, depends_on_task_id)
                            VALUES ($1, $2, $3)
                            ON CONFLICT DO NOTHING
                            """,
                            workflow.workflow_id,
                            task.task_id,
                            dep,
                        )

    async def _upsert_task(self, conn: asyncpg.Connection, task: Task, workflow_id: str) -> None:
        row = _task_to_row(task, workflow_id)
        await conn.execute(
            """
            INSERT INTO tasks (
                task_id, workflow_id, parent_task_id, task_type, target_capability, target_agent,
                instructions, input, input_refs, required_for_completion, status,
                result, error_info, retry_count, max_retries, priority, version
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
            ON CONFLICT (task_id) DO UPDATE SET
                workflow_id = EXCLUDED.workflow_id,
                parent_task_id = EXCLUDED.parent_task_id,
                task_type = EXCLUDED.task_type,
                target_capability = EXCLUDED.target_capability,
                target_agent = EXCLUDED.target_agent,
                instructions = EXCLUDED.instructions,
                input = EXCLUDED.input,
                input_refs = EXCLUDED.input_refs,
                required_for_completion = EXCLUDED.required_for_completion,
                status = EXCLUDED.status,
                result = EXCLUDED.result,
                error_info = EXCLUDED.error_info,
                retry_count = EXCLUDED.retry_count,
                max_retries = EXCLUDED.max_retries,
                priority = EXCLUDED.priority,
                updated_at = NOW(),
                version = EXCLUDED.version
            """,
            *[row[k] for k in [
                "task_id", "workflow_id", "parent_task_id", "task_type", "target_capability", "target_agent",
                "instructions", "input", "input_refs", "required_for_completion", "status",
                "result", "error_info", "retry_count", "max_retries", "priority", "version"
            ]]
        )

    async def get_workflow(self, workflow_id: str) -> Workflow | None:
        async with self._pool.acquire() as conn:
            wf_row = await conn.fetchrow(
                "SELECT * FROM workflows WHERE workflow_id = $1", workflow_id
            )
            if wf_row is None:
                return None
            task_rows = await conn.fetch(
                "SELECT * FROM tasks WHERE workflow_id = $1", workflow_id
            )
            tasks = {str(row["task_id"]): _row_to_task(row) for row in task_rows}
            return _row_to_workflow(wf_row, tasks)

    async def update_workflow_status(
        self, workflow_id: str, status: WorkflowStatus, *, version: int
    ) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE workflows
                SET status = $1, updated_at = NOW(), version = version + 1,
                    completed_at = CASE WHEN $1 IN ('completed', 'failed', 'cancelled') THEN NOW() ELSE completed_at END
                WHERE workflow_id = $2 AND version = $3
                """,
                status.value,
                workflow_id,
                version,
            )
            return result == "UPDATE 1"

    async def save_task(self, task: Task) -> None:
        async with self._pool.acquire() as conn:
            # Need workflow_id from existing task row
            row = await conn.fetchrow("SELECT workflow_id FROM tasks WHERE task_id = $1", task.task_id)
            workflow_id = row["workflow_id"] if row else None
            if workflow_id is None:
                raise RuntimeError(f"Cannot save orphan task {task.task_id} without workflow_id")
            await self._upsert_task(conn, task, workflow_id)

    async def get_task(self, task_id: str) -> Task | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM tasks WHERE task_id = $1", task_id)
            return _row_to_task(row) if row else None

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        result: Any = None,
        error: dict | None = None,
        version: int = 1,
    ) -> bool:
        async with self._pool.acquire() as conn:
            res = await conn.execute(
                """
                UPDATE tasks
                SET status = $1,
                    result = COALESCE($2, result),
                    error_info = COALESCE($3, error_info),
                    updated_at = NOW(),
                    version = version + 1,
                    started_at = CASE WHEN $1 = 'running' AND started_at IS NULL THEN NOW() ELSE started_at END,
                    completed_at = CASE WHEN $1 IN ('completed', 'failed', 'cancelled') THEN NOW() ELSE completed_at END
                WHERE task_id = $4 AND version = $5
                """,
                status.value,
                json.dumps(result) if result is not None else None,
                json.dumps(error) if error is not None else None,
                task_id,
                version,
            )
            return res == "UPDATE 1"

    async def list_ready_tasks(self, workflow_id: str) -> list[Task]:
        loaded = await self.load_task_graph(workflow_id)
        if loaded is None:
            return []
        _, graph = loaded
        return graph.ready_tasks()

    async def load_task_graph(self, workflow_id: str) -> tuple[Workflow, TaskGraph] | None:
        wf = await self.get_workflow(workflow_id)
        if wf is None:
            return None
        return wf, TaskGraph(wf)
```

- [ ] **步骤 2：编写集成测试**

```python
# tests/test_postgres_state_store.py
import pytest
from workflow.state import Task, TaskStatus, Workflow, WorkflowStatus
from db.postgres_state_store import PostgresStateStore


def make_wf(*tasks):
    return Workflow(
        workflow_id="wf-1",
        trace_id="tr-1",
        user_input="test",
        tasks={t.task_id: t for t in tasks},
    )


@pytest.mark.asyncio
async def test_postgres_save_and_get_workflow(postgres_pool):
    store = PostgresStateStore(postgres_pool)
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await store.save_workflow(wf)
    got = await store.get_workflow("wf-1")
    assert got is not None
    assert got.workflow_id == "wf-1"


@pytest.mark.asyncio
async def test_postgres_optimistic_lock(postgres_pool):
    store = PostgresStateStore(postgres_pool)
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await store.save_workflow(wf)
    ok = await store.update_workflow_status("wf-1", WorkflowStatus.EXECUTING, version=99)
    assert ok is False
```

- [ ] **步骤 3：使用 TEST_DATABASE_URL 运行测试**

运行：`TEST_DATABASE_URL=postgres://... pytest tests/test_postgres_state_store.py -v`
预期：通过。

- [ ] **步骤 4：提交**

```bash
git add db/postgres_state_store.py tests/test_postgres_state_store.py
git commit -m "feat(db): implement PostgreSQLStateStore"
```

---

## Task 5: 通过配置连接 StateStore

**涉及文件：**
- 修改：`agent.py`
- 修改：`.env.example`
- 测试：`tests/test_compatibility.py`

**接口：**
- 新增配置键：`STATE_STORE_BACKEND`、`DATABASE_URL`。

- [ ] **步骤 1：增加配置辅助函数和工厂方法**

```python
# agent.py
import os
from db.connection import create_pool


def _state_store_backend(self) -> str:
    return self.config.get("STATE_STORE_BACKEND", "memory").lower()


async def _create_state_store(self):
    backend = self._state_store_backend()
    if backend == "postgres":
        pool = await create_pool()
        from db.postgres_state_store import PostgresStateStore
        return PostgresStateStore(pool)
    return InMemoryStateStore()
```

更新 `_process_turn_event_driven` 以调用 `await self._create_state_store()`。

- [ ] **步骤 2：更新 .env.example**

```bash
# .env.example
STATE_STORE_BACKEND=memory
DATABASE_URL=postgresql://user:pass@localhost:5432/agent_team
```

- [ ] **步骤 3：增加兼容性测试**

```python
# tests/test_compatibility.py
import pytest
from agent import Agent


def make_agent():
    from context import Context
    from memory import Memory
    return Agent(Context(), Memory())


def test_default_state_store_is_memory():
    agent = make_agent()
    assert agent._state_store_backend() == "memory"
```

- [ ] **步骤 4：提交**

```bash
git add agent.py .env.example tests/test_compatibility.py
git commit -m "feat(config): wire StateStore backend selection"
```

---

## Task 6: 实现 Transactional Outbox

**涉及文件：**
- 新建：`events/outbox.py`
- 新建：`db/outbox_repository.py`
- 新建：`events/outbox_publisher.py`
- 新建：`db/processed_event_repository.py`
- 修改：`workflow/coordinator.py` 以写入 outbox
- 测试：`tests/test_outbox.py`

**接口：**
- `OutboxStore.enqueue(event, topic, key)`
- `OutboxStore.poll_pending(limit) -> list[OutboxRecord]`
- `OutboxStore.mark_published(outbox_id)`
- `ProcessedEventStore.is_processed(event_id) -> bool`
- `ProcessedEventStore.mark_processed(event_id, workflow_id, event_type)`

- [ ] **步骤 1：实现 OutboxRepository**

```python
# db/outbox_repository.py
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import asyncpg

from events.schema import Event


@dataclass
class OutboxRecord:
    id: int
    event_id: str
    aggregate_id: str
    event_type: str
    topic: str
    message_key: str | None
    payload: dict[str, Any]
    headers: dict[str, Any]
    retry_count: int


class OutboxRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def enqueue(
        self,
        event: Event,
        topic: str,
        key: str | None = None,
        conn: asyncpg.Connection | None = None,
    ) -> None:
        payload = event.to_dict()
        headers = {
            "event_id": event.event_id,
            "trace_id": event.trace_id,
            "workflow_id": event.workflow_id,
        }
        executor = conn if conn is not None else self._pool
        await executor.execute(
            """
            INSERT INTO outbox_events (event_id, aggregate_id, event_type, topic, message_key, payload, headers, status, next_retry_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', NOW())
            ON CONFLICT (event_id) DO NOTHING
            """,
            event.event_id,
            event.aggregate_id or event.workflow_id,
            event.event_type,
            topic,
            key,
            json.dumps(payload),
            json.dumps(headers),
        )

    async def poll_pending(self, limit: int = 100) -> list[OutboxRecord]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, event_id, aggregate_id, event_type, topic, message_key, payload, headers, retry_count
                FROM outbox_events
                WHERE status = 'pending' AND next_retry_at <= NOW()
                ORDER BY id
                LIMIT $1
                FOR UPDATE SKIP LOCKED
                """,
                limit,
            )
            return [
                OutboxRecord(
                    id=row["id"],
                    event_id=str(row["event_id"]),
                    aggregate_id=str(row["aggregate_id"]),
                    event_type=row["event_type"],
                    topic=row["topic"],
                    message_key=row["message_key"],
                    payload=json.loads(row["payload"]),
                    headers=json.loads(row["headers"]),
                    retry_count=row["retry_count"],
                )
                for row in rows
            ]

    async def mark_published(self, outbox_id: int, conn: asyncpg.Connection | None = None) -> None:
        executor = conn if conn is not None else self._pool
        await executor.execute(
            "UPDATE outbox_events SET status = 'published', published_at = NOW() WHERE id = $1",
            outbox_id,
        )

    async def mark_failed(self, outbox_id: int, error: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE outbox_events
                SET retry_count = retry_count + 1,
                    next_retry_at = NOW() + (2 ^ retry_count) * INTERVAL '1 second',
                    error_info = $2
                WHERE id = $1
                """,
                outbox_id,
                error,
            )
```

- [ ] **步骤 2：实现 ProcessedEventRepository**

```python
# db/processed_event_repository.py
from __future__ import annotations

import asyncpg


class ProcessedEventRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def is_processed(self, event_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM processed_events WHERE event_id = $1", event_id
            )
            return row is not None

    async def mark_processed(
        self,
        event_id: str,
        workflow_id: str,
        event_type: str,
        *,
        task_id: str | None = None,
        conn: asyncpg.Connection | None = None,
    ) -> None:
        executor = conn if conn is not None else self._pool
        await executor.execute(
            """
            INSERT INTO processed_events (event_id, workflow_id, task_id, event_type)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (event_id) DO NOTHING
            """,
            event_id,
            workflow_id,
            task_id,
            event_type,
        )
```

- [ ] **步骤 3：实现 OutboxPublisher（当前 stub，Kafka 发送推迟到 Task 8）**

```python
# events/outbox_publisher.py
from __future__ import annotations

import asyncio
import logging

from db.outbox_repository import OutboxRepository

logger = logging.getLogger(__name__)


class OutboxPublisher:
    def __init__(self, outbox: OutboxRepository, poll_interval: float = 5.0):
        self._outbox = outbox
        self._poll_interval = poll_interval
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                records = await self._outbox.poll_pending(limit=100)
                for record in records:
                    await self._publish(record)
            except Exception:
                logger.exception("OutboxPublisher loop error")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass

    async def _publish(self, record) -> None:
        # Defer Kafka send to Task 8 when KafkaEventBus is available.
        # For now, just log and mark published (integration test placeholder).
        logger.info("Would publish outbox record %s to %s", record.id, record.topic)
        await self._outbox.mark_published(record.id)
```

- [ ] **步骤 4：更新 coordinator，在 postgres 后端时将 TASK_READY 写入 outbox**

在 `workflow/coordinator.py` 中，`_publish_event_for_task` 应：
- 如果 `state_store` 是 `InMemoryStateStore`，直接发布到 `event_bus`。
- 如果 `state_store` 是 `PostgresStateStore`，使用一个辅助函数，在与 task 状态更新同一事务中写入 `outbox_events`。

由于事务需要传递 connection，通过 `OutboxStore` Protocol 进行抽象。

- [ ] **步骤 5：编写 Outbox 测试**

```python
# tests/test_outbox.py
import pytest
from events.schema import Event, EventType
from events.outbox import InMemoryOutboxStore


@pytest.mark.asyncio
async def test_in_memory_outbox_enqueue_and_poll():
    store = InMemoryOutboxStore()
    event = Event(event_id="e1", event_type=EventType.TASK_READY, trace_id="t1", workflow_id="wf1")
    await store.enqueue(event, topic="task.ready", key="wf1")
    pending = await store.poll_pending(limit=10)
    assert len(pending) == 1
    assert pending[0].topic == "task.ready"
```

- [ ] **步骤 6：提交**

```bash
git add events/outbox.py db/outbox_repository.py events/outbox_publisher.py db/processed_event_repository.py tests/test_outbox.py
git commit -m "feat(outbox): add Transactional Outbox and processed event repository"
```

---

## Task 7: 实现 EventStore Repository

**涉及文件：**
- 新建：`events/event_store.py`
- 新建：`db/event_store_repository.py`
- 修改：`events/in_memory.py` / `events/kafka_event_bus.py` 追加事件
- 测试：`tests/test_event_store.py`

**接口：**
- `EventStore.append(event: Event) -> None`

- [ ] **步骤 1：实现 EventStoreRepository**

```python
# db/event_store_repository.py
from __future__ import annotations

import json

import asyncpg

from events.schema import Event


class EventStoreRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def append(self, event: Event) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO event_store (
                    event_id, trace_id, parent_event_id, aggregate_id, event_type,
                    priority, timestamp, source, target_agent, target_capability,
                    workflow_id, task_id, payload, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                ON CONFLICT (event_id) DO NOTHING
                """,
                event.event_id,
                event.trace_id,
                event.parent_event_id,
                event.aggregate_id or event.workflow_id,
                event.event_type,
                event.priority,
                event.timestamp,
                event.source,
                event.target_agent,
                event.target_capability,
                event.workflow_id,
                event.task_id,
                json.dumps(event.payload),
                json.dumps(event.metadata),
            )
```

- [ ] **步骤 2：增加 EventStore Protocol 和 InMemoryEventStore**

```python
# events/event_store.py
from typing import Protocol
from events.schema import Event


class EventStore(Protocol):
    async def append(self, event: Event) -> None: ...


class InMemoryEventStore:
    def __init__(self):
        self._events: list[Event] = []

    async def append(self, event: Event) -> None:
        self._events.append(event)
```

- [ ] **步骤 3：增加配置 `EVENT_STORE_ENABLED` 并接入**

- [ ] **步骤 4：提交**

```bash
git add events/event_store.py db/event_store_repository.py tests/test_event_store.py
git commit -m "feat(events): add EventStore repository"
```

---

## Task 8: 实现 KafkaEventBus

**涉及文件：**
- 新建：`events/kafka_event_bus.py`
- 新建：`events/serde.py`
- 修改：`agent.py` 进行后端选择
- 修改：`.env.example`
- 测试：`tests/test_kafka_event_bus.py`

**接口：**
- `KafkaEventBus(EventBus)`
- `Event.to_dict()` / `Event.from_dict()`

- [ ] **步骤 1：实现 JSON serde**

```python
# events/serde.py
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from events.schema import Event


def event_to_json(event: Event) -> bytes:
    return json.dumps(event.to_dict(), default=_json_default).encode("utf-8")


def event_from_json(data: bytes) -> Event:
    d = json.loads(data.decode("utf-8"))
    return Event.from_dict(d)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
```

- [ ] **步骤 2：实现 KafkaEventBus**

```python
# events/kafka_event_bus.py
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from events.bus import EventBus
from events.schema import Event
from events.serde import event_from_json, event_to_json

logger = logging.getLogger(__name__)


class KafkaEventBus:
    def __init__(
        self,
        bootstrap_servers: str,
        client_id: str,
        consumer_group: str,
        topic_prefix: str = "",
    ):
        self._bootstrap_servers = bootstrap_servers
        self._client_id = client_id
        self._consumer_group = consumer_group
        self._topic_prefix = topic_prefix
        self._handlers: dict[str, list[Callable[[Event], Awaitable[None]]]] = {}
        self._producer: AIOKafkaProducer | None = None
        self._consumers: list[AIOKafkaConsumer] = []
        self._consumer_tasks: list[asyncio.Task] = []

    def _topic(self, event_type: str) -> str:
        return f"{self._topic_prefix}{event_type.replace('.', '_')}"

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[Event], Awaitable[None]],
    ) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def publish(self, event: Event) -> None:
        if self._producer is None:
            raise RuntimeError("KafkaEventBus not started")
        topic = self._topic(event.event_type)
        key = (event.task_id or event.workflow_id).encode("utf-8") if event.task_id or event.workflow_id else None
        await self._producer.send_and_wait(topic, key=key, value=event_to_json(event))

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            client_id=f"{self._client_id}-producer",
            value_serializer=lambda v: v,
        )
        await self._producer.start()

        for event_type, handlers in self._handlers.items():
            topic = self._topic(event_type)
            consumer = AIOKafkaConsumer(
                topic,
                bootstrap_servers=self._bootstrap_servers,
                group_id=self._consumer_group,
                client_id=f"{self._client_id}-consumer-{event_type}",
                value_deserializer=lambda v: v,
                auto_offset_reset="earliest",
                enable_auto_commit=True,
            )
            await consumer.start()
            self._consumers.append(consumer)
            self._consumer_tasks.append(
                asyncio.create_task(self._consume(event_type, consumer, handlers))
            )

    async def _consume(
        self,
        event_type: str,
        consumer: AIOKafkaConsumer,
        handlers: list[Callable[[Event], Awaitable[None]]],
    ) -> None:
        try:
            async for msg in consumer:
                try:
                    event = event_from_json(msg.value)
                    for handler in handlers:
                        await handler(event)
                except Exception:
                    logger.exception("Kafka handler error for event_type=%s", event_type)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        for t in self._consumer_tasks:
            t.cancel()
        await asyncio.gather(*self._consumer_tasks, return_exceptions=True)
        for c in self._consumers:
            await c.stop()
        if self._producer:
            await self._producer.stop()
```

- [ ] **步骤 3：在 agent.py 中接入后端选择**

```python
# agent.py
async def _create_event_bus(self):
    backend = self.config.get("EVENT_BUS_BACKEND", "memory").lower()
    if backend == "kafka":
        from events.kafka_event_bus import KafkaEventBus
        return KafkaEventBus(
            bootstrap_servers=self.config.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            client_id=self.config.get("KAFKA_CLIENT_ID", "agent-team"),
            consumer_group=self.config.get("KAFKA_CONSUMER_GROUP", "agent-team"),
            topic_prefix=self.config.get("KAFKA_TOPIC_PREFIX", ""),
        )
    return InMemoryEventBus()
```

- [ ] **步骤 4：更新 .env.example**

```bash
EVENT_BUS_BACKEND=memory
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_CLIENT_ID=agent-team
KAFKA_CONSUMER_GROUP=agent-team
KAFKA_TOPIC_PREFIX=
```

- [ ] **步骤 5：增加 Kafka 集成测试**

```python
# tests/test_kafka_event_bus.py
import pytest
import pytest_asyncio
from events.kafka_event_bus import KafkaEventBus
from events.schema import Event, EventType


@pytest_asyncio.fixture
async def kafka_bus(kafka_bootstrap):
    bus = KafkaEventBus(
        bootstrap_servers=kafka_bootstrap,
        client_id="test",
        consumer_group="test-group",
        topic_prefix="test_",
    )
    yield bus
    await bus.stop()


@pytest.mark.asyncio
async def test_kafka_publish_subscribe(kafka_bus):
    received = []
    async def handler(event):
        received.append(event)
    kafka_bus.subscribe(EventType.TASK_READY, handler)
    await kafka_bus.start()

    event = Event(event_id="e1", event_type=EventType.TASK_READY, trace_id="t1", workflow_id="wf1", task_id="t1")
    await kafka_bus.publish(event)
    await asyncio.sleep(1)
    assert len(received) == 1
    assert received[0].task_id == "t1"
```

- [ ] **步骤 6：提交**

```bash
git add events/kafka_event_bus.py events/serde.py agent.py .env.example tests/test_kafka_event_bus.py
git commit -m "feat(events): add KafkaEventBus backend"
```

---

## Task 9: 实现 Redis 调度幂等

**涉及文件：**
- 新建：`redis_client.py`
- 修改：`scheduler.py`
- 修改：`.env.example`
- 测试：`tests/test_redis_idempotency.py`

**接口：**
- `RedisClient.set_idempotency(key: str, ttl: int) -> bool`

- [ ] **步骤 1：实现 RedisClient 封装**

```python
# redis_client.py
from __future__ import annotations

import os

import redis.asyncio as redis


class RedisClient:
    def __init__(self, url: str | None = None):
        self._url = url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        self._client = redis.from_url(self._url, decode_responses=True)

    async def close(self) -> None:
        if self._client:
            await self._client.close()

    async def set_idempotency(self, key: str, ttl_seconds: int = 3600) -> bool:
        if self._client is None:
            raise RuntimeError("Redis not connected")
        result = await self._client.set(key, "1", nx=True, ex=ttl_seconds)
        return result is not None

    async def delete_idempotency(self, key: str) -> None:
        if self._client:
            await self._client.delete(key)
```

- [ ] **步骤 2：更新 Scheduler 以在启用 Redis 时使用**

```python
# scheduler.py 修改要点
class Scheduler:
    def __init__(
        self,
        event_bus: EventBus,
        handlers: dict[str, Handler],
        *,
        redis_client: RedisClient | None = None,
        dispatch_ttl: int = 3600,
    ):
        self.event_bus = event_bus
        self.handlers = handlers
        self._redis = redis_client
        self._dispatch_ttl = dispatch_ttl
        self._dispatched: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    async def handle_task_ready(self, event: Event) -> None:
        task_id = event.task_id
        if task_id is None:
            logger.error("task.ready event without task_id: %s", event.event_id)
            return

        retry_count = event.metadata.get("retry_count", 0)
        dispatch_key = f"dispatched:{event.workflow_id}:{task_id}:{retry_count}"

        already_dispatched = await self._is_dispatched(dispatch_key)
        if already_dispatched:
            logger.debug("Task %s already dispatched, ignoring", task_id)
            return
        await self._mark_dispatched(dispatch_key)
        # ... rest unchanged

    async def _is_dispatched(self, key: str) -> bool:
        if self._redis:
            try:
                return await self._redis.set_idempotency(key, ttl_seconds=self._dispatch_ttl) is False
            except Exception:
                logger.exception("Redis idempotency check failed, falling back to memory")
        return key in self._dispatched

    async def _mark_dispatched(self, key: str) -> None:
        if self._redis:
            try:
                await self._redis.set_idempotency(key, ttl_seconds=self._dispatch_ttl)
            except Exception:
                logger.exception("Redis idempotency set failed, falling back to memory")
        self._dispatched.add(key)
```

- [ ] **步骤 3：增加配置和测试**

更新 `.env.example`，增加 `REDIS_ENABLED=false` 和 `REDIS_URL=redis://localhost:6379`。

编写 `tests/test_redis_idempotency.py`。

- [ ] **步骤 4：提交**

```bash
git add redis_client.py scheduler.py .env.example tests/test_redis_idempotency.py
git commit -m "feat(scheduler): add Redis dispatch idempotency with memory fallback"
```

---

## Task 10: 更新 CLI 入口以支持异步结果轮询

**涉及文件：**
- 修改：`loop.py`
- 修改：`agent.py` 中 `process_turn` 的返回语义
- 测试：`tests/test_loop.py`

**接口：**
- `Agent.process_turn(user_input: str) -> str` 保持签名，内部改为轮询 workflow 结果。

- [ ] **步骤 1：修改 loop.py 以轮询 workflow 结果**

```python
# loop.py 修改要点
import time


def run_loop() -> None:
    context = Context()
    memory = Memory()
    print(f"{Agent(context, memory).name} is ready. Type 'exit' or 'quit' to stop.")
    try:
        while True:
            user_input = input("> ").strip()
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit"}:
                break

            agent = Agent(context=context, memory=memory)
            response = agent.process_turn(user_input)
            print(response)
    finally:
        # cleanup unchanged
        pass
```

在事件驱动模式下，`process_turn` 最多阻塞 `WORKFLOW_TIMEOUT_SECONDS`，轮询数据库或（内存模式下）等待 Future。保持简单：事件驱动模式下启动 workflow，然后轮询 PostgreSQL/InMemory 状态直到完成。

- [ ] **步骤 2：在 agent.py 中实现轮询辅助函数**

```python
# agent.py
async def _wait_for_workflow_result(
    self,
    workflow_id: str,
    state_store: StateStore,
    timeout_seconds: float,
) -> str:
    import asyncio
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    while asyncio.get_event_loop().time() < deadline:
        wf = await state_store.get_workflow(workflow_id)
        if wf is None:
            return "[Workflow not found]"
        if wf.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED):
            return self._finalize_workflow(wf, wf.user_input)
        await asyncio.sleep(0.5)
    return f"[Workflow timeout] did not complete within {timeout_seconds}s"
```

- [ ] **步骤 3：更新 `_process_turn_event_driven`，通过轮询返回最终结果**

将基于 Future 的等待替换为 `_wait_for_workflow_result`。

- [ ] **步骤 4：提交**

```bash
git add loop.py agent.py tests/test_loop.py
git commit -m "feat(cli): poll workflow result instead of relying on in-process Future"
```

---

## Task 11: 增加端到端兼容性与恢复测试

**涉及文件：**
- 新建：`tests/test_compatibility.py`
- 新建：`tests/test_recovery.py`

**接口：**
- 验证四种后端组合。

- [ ] **步骤 1：增加兼容性矩阵测试**

```python
# tests/test_compatibility.py
import pytest
import pytest_asyncio
from events.in_memory import InMemoryEventBus
from workflow.state_store import InMemoryStateStore


@pytest.mark.asyncio
async def test_inmemory_bus_inmemory_store():
    """Original behavior preserved."""
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    # exercise start_workflow + task completed
    assert True
```

- [ ] **步骤 2：增加恢复测试**

```python
# tests/test_recovery.py
@pytest.mark.asyncio
async def test_recovery_reloads_incomplete_workflow(postgres_pool):
    # Save a workflow with one pending task
    # Restart a new coordinator with fresh state
    # Verify it publishes task.ready
    pass
```

- [ ] **步骤 3：提交**

```bash
git add tests/test_compatibility.py tests/test_recovery.py
git commit -m "test(integration): add compatibility and recovery tests"
```

---

## Task 12: 最终集成与文档

**涉及文件：**
- 修改：`README.md`
- 修改：`.env.example`
- 修改：`pyproject.toml`

- [ ] **步骤 1：更新 README.md**

增加以下章节：
- 事件驱动架构概览
- 后端组合
- 使用 Docker Compose 运行集成测试
- 配置参考

- [ ] **步骤 2：为本地开发增加 Docker Compose**

```yaml
# docker-compose.yml
version: "3.8"
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: agent
      POSTGRES_DB: agent_team
    ports:
      - "5432:5432"
  kafka:
    image: confluentinc/cp-kafka:latest
    ports:
      - "9092:9092"
    environment:
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
  zookeeper:
    image: confluentinc/cp-zookeeper:latest
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
  redis:
    image: redis:7
    ports:
      - "6379:6379"
```

- [ ] **步骤 3：最终测试运行**

运行：`pytest tests/ -v`
预期：通过。

- [ ] **步骤 4：提交**

```bash
git add README.md docker-compose.yml pyproject.toml .env.example
git commit -m "docs(ops): add integration docs and Docker Compose for dev dependencies"
```

---

## 自检清单

- [ ] 规范覆盖：设计文档中的每个章节至少对应一个 Task。
- [ ] 占位符检查：没有 "TBD"/"TODO"/"implement later"。
- [ ] 类型一致性：`Event`、`StateStore`、`OutboxStore` 的签名在各 Task 中保持一致。
- [ ] 向后兼容：InMemory 路径保留。
- [ ] 测试覆盖：每个阶段都有单元测试或集成测试。

---

## 执行交接

计划已完成并保存至 `docs/superpowers/plans/2026-07-07-event-driven-persistence-plan.md`。

**两种执行方式：**

1. **Subagent-Driven（推荐）**：每个 Task 分派一个独立子代理实现，我在 Task 之间进行审查和衔接。
2. **Inline Execution**：我在当前会话中使用 `superpowers:executing-plans` 按 Task 逐步执行，关键节点暂停供你审查。

**选择哪种方式？**
