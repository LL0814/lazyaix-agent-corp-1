# 事件驱动 Agent 调度实现计划

> **给执行代理看的说明：** 必须使用的子技能：superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按任务一步步实现。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将 `agent.py` 中当前的同步调用链 `Supervisor → Tool.execute("task") → Subagent → Worker` 改造为事件驱动架构，使用 `InMemoryEventBus`、动态 Task Graph、`Scheduler` 和异步 Agent Handler，同时保留由 `ENABLE_EVENT_DRIVEN` 控制的同步回退路径。

**架构说明：** Supervisor 生成 Task 的 DAG。`WorkflowCoordinator` 跟踪 Task 状态，在依赖满足时发布 `task.ready` 事件，并消费 `agent.completed`/`agent.failed` 事件推进工作流。`InMemoryEventBus` 负责事件路由。`Scheduler` 根据 `target_capability` 将任务路由到 `ResearcherHandler` 或 `WriterHandler`。Handler 通过 `asyncio.to_thread()` 执行现有的同步 `Researcher.run()` / `Writer.run()`，并发布状态和结果事件。当所有必要任务完成后，Coordinator 通知 Supervisor，由 Supervisor 将最终结果返回给 REPL。

**技术栈：** Python 3.11+、`asyncio`、`dataclasses`、`pytest`、`pytest-asyncio`。

## 全局约束

- 第一阶段不引入外部消息队列或数据库：不使用 Kafka、Redis、RabbitMQ 或 PostgreSQL。
- `Model.complete()` 保持同步；在 Handler 中通过 `asyncio.to_thread()` 包装。
- `subagents/workers.py` 中现有的 `Researcher.run(description: str) -> str` 和 `Writer.run(description: str) -> str` 必须保持当前签名和 prompt 不变。
- 当 `ENABLE_EVENT_DRIVEN=false` 时，原有的同步 `Tool.execute("task")` 路径（`tools/__init__.py`）和 `Subagent.dispatch()`（`subagents/__init__.py`）继续可用。
- 所有新模块放在项目根目录下，职责单一清晰。
- 每个 Task 都以可独立运行的测试和一次 git commit 结束。
- Writer 不固定依赖 Researcher；依赖关系仅由 Supervisor 生成的 Task Graph 表达。

## 文件结构

| 文件 | 职责 |
|---|---|
| `pyproject.toml` | 添加 `pytest` 和 `pytest-asyncio` 开发依赖。 |
| `workflow/state.py` | `TaskStatus`、`WorkflowStatus`、`Task`、`Workflow` 数据类。 |
| `workflow/graph.py` | Task Graph 校验、READY 计算、依赖检查。 |
| `events/schema.py` | `Event` 数据类和事件类型常量。 |
| `events/bus.py` | `EventBus` 抽象协议。 |
| `events/in_memory.py` | 基于 `asyncio.Queue` 的 `InMemoryEventBus` 实现。 |
| `subagents/handlers.py` | `ResearcherHandler` 和 `WriterHandler` 异步事件消费者。 |
| `scheduler.py` | `Scheduler`：按 capability 路由并保证幂等。 |
| `workflow/coordinator.py` | `WorkflowCoordinator`：状态推进、重试逻辑、完成检测。 |
| `agent.py` | 扩展 `Agent` 的事件驱动分支，保留同步回退。 |
| `loop.py` | 在 REPL 旁启动/关闭事件总线的事件循环。 |
| `.env.example` | 记录 `ENABLE_EVENT_DRIVEN` 等相关配置。 |
| `tests/test_graph.py` | Task Graph 校验测试。 |
| `tests/test_event_bus.py` | InMemoryEventBus 测试。 |
| `tests/test_handlers.py` | Researcher/Writer Handler 测试。 |
| `tests/test_scheduler.py` | Scheduler 路由和幂等测试。 |
| `tests/test_supervisor.py` | Supervisor 事件驱动端到端测试。 |
| `tests/test_sync_fallback.py` | 验证原有同步路径仍然可用。 |

---

### Task 1：添加 pytest 开发依赖

**涉及文件：**
- 修改：`pyproject.toml`

**接口约定：**
- 消费：现有的 `[dependency-groups] dev = []`
- 产出：`dev = ["pytest>=8.0.0", "pytest-asyncio>=0.23.0"]`

- [ ] **步骤 1：编辑 `pyproject.toml`**

将 dev 依赖组改为：

```toml
[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]
```

- [ ] **步骤 2：安装开发依赖**

运行：

```bash
uv sync
```

预期结果：lockfile 更新，依赖安装成功。

- [ ] **步骤 3：验证 pytest**

运行：

```bash
uv run pytest --version
```

预期输出包含 `pytest 8.`。

- [ ] **步骤 4：提交**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add pytest and pytest-asyncio dev dependencies"
```

---

### Task 2：定义 Task 和 Workflow 状态模型

**涉及文件：**
- 创建：`workflow/state.py`
- 创建：`tests/test_state.py`

**接口约定：**
- 产出：`TaskStatus`、`WorkflowStatus`、`Task`、`Workflow`

- [ ] **步骤 1：编写 `workflow/state.py`**

```python
"""Workflow and Task state models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    DISPATCHED = "dispatched"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class WorkflowStatus(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    task_id: str
    task_type: str
    target_capability: str
    instructions: str
    input: dict | None = None
    dependencies: list[str] = field(default_factory=list)
    input_refs: list[str] = field(default_factory=list)
    required_for_completion: bool = True
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: dict | None = None
    retry_count: int = 0


@dataclass
class Workflow:
    workflow_id: str
    trace_id: str
    user_input: str
    tasks: dict[str, Task] = field(default_factory=dict)
    status: WorkflowStatus = WorkflowStatus.CREATED
    final_result: str | None = None
    error: dict | None = None
```

- [ ] **步骤 2：编写 `tests/test_state.py`**

```python
from workflow.state import Task, TaskStatus, Workflow, WorkflowStatus


def test_task_defaults():
    task = Task(
        task_id="write_001",
        task_type="write",
        target_capability="writer",
        instructions="write a poem",
    )
    assert task.status == TaskStatus.PENDING
    assert task.dependencies == []
    assert task.required_for_completion is True


def test_workflow_defaults():
    wf = Workflow(workflow_id="wf-1", trace_id="tr-1", user_input="hello")
    assert wf.status == WorkflowStatus.CREATED
    assert wf.tasks == {}
```

- [ ] **步骤 3：运行测试**

```bash
uv run pytest tests/test_state.py -v
```

预期结果：2 passed。

- [ ] **步骤 4：提交**

```bash
git add workflow/state.py tests/test_state.py
git commit -m "feat: add Task and Workflow state models"
```

---

### Task 3：实现 Task Graph 校验和 READY 计算

**涉及文件：**
- 创建：`workflow/graph.py`
- 创建：`tests/test_graph.py`

**接口约定：**
- 消费：`workflow.state` 中的 `Task`、`TaskStatus`、`Workflow`
- 产出：`TaskGraph` 类，提供 `ready_tasks()`、`validate()`、`mark_completed()`、`mark_failed()`、`is_complete()`

- [ ] **步骤 1：编写 `workflow/graph.py`**

```python
"""Task Graph validation and state advancement."""

from __future__ import annotations

from workflow.state import Task, TaskStatus, Workflow


class TaskGraphError(Exception):
    """Raised when a Task Graph is invalid."""


class TaskGraph:
    """Manages a DAG of Tasks inside a Workflow."""

    def __init__(self, workflow: Workflow):
        self.workflow = workflow

    def validate(self) -> None:
        """Validate the task graph. Raises TaskGraphError on problems."""
        tasks = self.workflow.tasks
        seen_ids = set()
        for task in tasks.values():
            if task.task_id in seen_ids:
                raise TaskGraphError(f"Duplicate task_id: {task.task_id}")
            seen_ids.add(task.task_id)

        for task in tasks.values():
            for dep in task.dependencies:
                if dep not in tasks:
                    raise TaskGraphError(
                        f"Task {task.task_id} depends on unknown task {dep}"
                    )

        # Cycle detection using DFS.
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in tasks}
        stack: list[str] = []

        def dfs(tid: str) -> None:
            color[tid] = GRAY
            stack.append(tid)
            for dep in tasks[tid].dependencies:
                if color[dep] == GRAY:
                    cycle = " -> ".join(stack[stack.index(dep):] + [dep])
                    raise TaskGraphError(f"Cycle detected: {cycle}")
                if color[dep] == WHITE:
                    dfs(dep)
            stack.pop()
            color[tid] = BLACK

        for tid in tasks:
            if color[tid] == WHITE:
                dfs(tid)

    def ready_tasks(self) -> list[Task]:
        """Return tasks whose dependencies are all completed."""
        ready: list[Task] = []
        for task in self.workflow.tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            deps_satisfied = all(
                self.workflow.tasks[dep].status == TaskStatus.COMPLETED
                for dep in task.dependencies
            )
            if deps_satisfied:
                ready.append(task)
        return ready

    def mark_ready(self, task_id: str) -> None:
        task = self.workflow.tasks[task_id]
        if task.status == TaskStatus.PENDING:
            task.status = TaskStatus.READY

    def mark_dispatched(self, task_id: str) -> None:
        task = self.workflow.tasks[task_id]
        if task.status == TaskStatus.READY:
            task.status = TaskStatus.DISPATCHED

    def mark_completed(self, task_id: str, result) -> None:
        task = self.workflow.tasks[task_id]
        task.status = TaskStatus.COMPLETED
        task.result = result
        task.error = None

    def mark_failed(self, task_id: str, error: dict) -> None:
        task = self.workflow.tasks[task_id]
        task.status = TaskStatus.FAILED
        task.error = error

    def mark_blocked(self, task_id: str) -> None:
        task = self.workflow.tasks[task_id]
        if task.status == TaskStatus.PENDING:
            task.status = TaskStatus.BLOCKED

    def is_complete(self) -> bool:
        """True when all required tasks are completed."""
        return all(
            task.status == TaskStatus.COMPLETED
            for task in self.workflow.tasks.values()
            if task.required_for_completion
        )

    def has_failed_required(self) -> bool:
        """True when any required task is failed or blocked (terminal failure)."""
        return any(
            task.status in (TaskStatus.FAILED, TaskStatus.BLOCKED)
            for task in self.workflow.tasks.values()
            if task.required_for_completion
        )
```

- [ ] **步骤 2：编写 `tests/test_graph.py`**

```python
import pytest

from workflow.graph import TaskGraph, TaskGraphError
from workflow.state import Task, TaskStatus, Workflow


def make_wf(*tasks: Task) -> Workflow:
    return Workflow(
        workflow_id="wf-1",
        trace_id="tr-1",
        user_input="test",
        tasks={t.task_id: t for t in tasks},
    )


def test_ready_tasks_independent():
    t1 = Task("r1", "research", "researcher", "do research")
    t2 = Task("w1", "write", "writer", "write poem")
    graph = TaskGraph(make_wf(t1, t2))
    ready = graph.ready_tasks()
    assert {t.task_id for t in ready} == {"r1", "w1"}


def test_ready_tasks_with_dependency():
    r1 = Task("r1", "research", "researcher", "do research")
    w1 = Task("w1", "write", "writer", "write", dependencies=["r1"])
    graph = TaskGraph(make_wf(r1, w1))
    assert graph.ready_tasks() == [r1]
    graph.mark_completed("r1", "result")
    assert graph.ready_tasks() == [w1]


def test_unknown_dependency():
    t1 = Task("t1", "write", "writer", "x", dependencies=["missing"])
    graph = TaskGraph(make_wf(t1))
    with pytest.raises(TaskGraphError, match="unknown task"):
        graph.validate()


def test_duplicate_task_id():
    t1 = Task("t1", "write", "writer", "a")
    t2 = Task("t1", "research", "researcher", "b")
    graph = TaskGraph(make_wf(t1, t2))
    with pytest.raises(TaskGraphError, match="Duplicate"):
        graph.validate()


def test_cyclic_dependency():
    a = Task("a", "write", "writer", "a", dependencies=["b"])
    b = Task("b", "write", "writer", "b", dependencies=["a"])
    graph = TaskGraph(make_wf(a, b))
    with pytest.raises(TaskGraphError, match="Cycle"):
        graph.validate()


def test_is_complete():
    r1 = Task("r1", "research", "researcher", "r")
    w1 = Task("w1", "write", "writer", "w", dependencies=["r1"])
    graph = TaskGraph(make_wf(r1, w1))
    assert not graph.is_complete()
    graph.mark_completed("r1", "x")
    graph.mark_completed("w1", "y")
    assert graph.is_complete()
```

- [ ] **步骤 3：运行测试**

```bash
uv run pytest tests/test_graph.py -v
```

预期结果：6 passed。

- [ ] **步骤 4：提交**

```bash
git add workflow/graph.py tests/test_graph.py
git commit -m "feat: add TaskGraph validation and READY computation"
```

---

### Task 4：定义 Event 数据模型

**涉及文件：**
- 创建：`events/schema.py`
- 创建：`tests/test_event_schema.py`

**接口约定：**
- 产出：`Event` 数据类和 `EventType` 常量

- [ ] **步骤 1：编写 `events/schema.py`**

```python
"""Event data model and event type constants."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    source: str = "supervisor"
    target_agent: str | None = None
    target_capability: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
```

- [ ] **步骤 2：编写 `tests/test_event_schema.py`**

```python
from events.schema import Event, EventType


def test_event_creation():
    e = Event(
        event_id="e1",
        event_type=EventType.TASK_READY,
        trace_id="tr-1",
        workflow_id="wf-1",
        task_id="t1",
        target_capability="writer",
    )
    assert e.event_type == "task.ready"
    assert e.target_capability == "writer"
    assert e.payload == {}
```

- [ ] **步骤 3：运行测试**

```bash
uv run pytest tests/test_event_schema.py -v
```

预期结果：1 passed。

- [ ] **步骤 4：提交**

```bash
git add events/schema.py tests/test_event_schema.py
git commit -m "feat: add Event schema and event type constants"
```

---

### Task 5：定义 EventBus 抽象协议

**涉及文件：**
- 创建：`events/bus.py`
- 创建：`tests/test_bus_protocol.py`

**接口约定：**
- 产出：`EventBus` 协议

- [ ] **步骤 1：编写 `events/bus.py`**

```python
"""EventBus abstract protocol."""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol

from events.schema import Event


class EventBus(Protocol):
    """Abstract event bus: implementations may use queues, Redis, etc."""

    async def publish(self, event: Event) -> None:
        ...

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[Event], Awaitable[None]],
    ) -> None:
        ...

    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...
```

- [ ] **步骤 2：编写 `tests/test_bus_protocol.py`**

```python
import pytest

from events.bus import EventBus
from events.schema import Event


class DummyBus:
    async def publish(self, event: Event) -> None:
        pass

    def subscribe(self, event_type, handler):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass


def test_protocol_satisfied():
    bus: EventBus = DummyBus()
    assert bus is not None
```

- [ ] **步骤 3：运行测试**

```bash
uv run pytest tests/test_bus_protocol.py -v
```

预期结果：1 passed。

- [ ] **步骤 4：提交**

```bash
git add events/bus.py tests/test_bus_protocol.py
git commit -m "feat: add EventBus abstract protocol"
```

---

### Task 6：实现 InMemoryEventBus

**涉及文件：**
- 创建：`events/in_memory.py`
- 创建：`tests/test_event_bus.py`

**接口约定：**
- 消费：`EventBus` 协议、`Event`
- 产出：`InMemoryEventBus`

- [ ] **步骤 1：编写 `events/in_memory.py`**

```python
"""In-memory EventBus implementation using asyncio.Queue."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from events.schema import Event

logger = logging.getLogger(__name__)


class InMemoryEventBus:
    """Process-local event bus. Each event type has its own queue and consumer task."""

    def __init__(self):
        self._handlers: dict[str, list[Callable[[Event], Awaitable[None]]]] = {}
        self._queues: dict[str, asyncio.Queue[Event]] = {}
        self._tasks: list[asyncio.Task] = []

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[Event], Awaitable[None]],
    ) -> None:
        self._handlers.setdefault(event_type, []).append(handler)
        self._queues.setdefault(event_type, asyncio.Queue())

    async def publish(self, event: Event) -> None:
        queue = self._queues.setdefault(event.event_type, asyncio.Queue())
        await queue.put(event)

    async def start(self) -> None:
        for event_type, handlers in self._handlers.items():
            queue = self._queues[event_type]
            for handler in handlers:
                self._tasks.append(
                    asyncio.create_task(
                        self._consume(event_type, queue, handler),
                        name=f"consumer-{event_type}-{len(self._tasks)}",
                    )
                )

    async def _consume(
        self,
        event_type: str,
        queue: asyncio.Queue[Event],
        handler: Callable[[Event], Awaitable[None]],
    ) -> None:
        while True:
            try:
                event = await queue.get()
            except asyncio.CancelledError:
                break
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    "Handler error for event_type=%s event_id=%s",
                    event_type,
                    event.event_id,
                )
            finally:
                queue.task_done()

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
```

- [ ] **步骤 2：编写 `tests/test_event_bus.py`**

```python
import asyncio

import pytest

from events.in_memory import InMemoryEventBus
from events.schema import Event, EventType


@pytest.mark.asyncio
async def test_publish_consume():
    bus = InMemoryEventBus()
    received = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe(EventType.TASK_READY, handler)
    await bus.start()

    event = Event(
        event_id="e1",
        event_type=EventType.TASK_READY,
        trace_id="tr-1",
        workflow_id="wf-1",
        task_id="t1",
    )
    await bus.publish(event)
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].task_id == "t1"

    await bus.stop()


@pytest.mark.asyncio
async def test_handler_exception_not_crash_bus():
    bus = InMemoryEventBus()
    received = []

    async def failer(event: Event):
        raise RuntimeError("boom")

    async def keeper(event: Event):
        received.append(event)

    bus.subscribe(EventType.TASK_READY, failer)
    bus.subscribe(EventType.TASK_READY, keeper)
    await bus.start()

    await bus.publish(
        Event(
            event_id="e1",
            event_type=EventType.TASK_READY,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="t1",
        )
    )
    await asyncio.sleep(0.05)

    assert len(received) == 1
    await bus.stop()


@pytest.mark.asyncio
async def test_start_stop():
    bus = InMemoryEventBus()
    bus.subscribe(EventType.TASK_READY, lambda e: None)
    await bus.start()
    assert len(bus._tasks) == 1
    await bus.stop()
    assert len(bus._tasks) == 0
```

- [ ] **步骤 3：运行测试**

```bash
uv run pytest tests/test_event_bus.py -v
```

预期结果：3 passed。

- [ ] **步骤 4：提交**

```bash
git add events/in_memory.py tests/test_event_bus.py
git commit -m "feat: implement InMemoryEventBus with asyncio.Queue"
```

---

### Task 7：实现 Researcher 和 Writer Handler

**涉及文件：**
- 创建：`subagents/handlers.py`
- 修改：`subagents/__init__.py`（可选，用于重新导出）
- 创建：`tests/test_handlers.py`

**接口约定：**
- 消费：`Event`、`EventType`、`EventBus`、`Model`、`Researcher`、`Writer`
- 产出：`ResearcherHandler`、`WriterHandler`

- [ ] **步骤 1：编写 `subagents/handlers.py`**

```python
"""Async event handlers for Researcher and Writer workers."""

from __future__ import annotations

import asyncio
import logging
import uuid

from events.bus import EventBus
from events.schema import Event, EventType
from subagents.workers import Researcher, Writer

logger = logging.getLogger(__name__)


class ResearcherHandler:
    def __init__(self, model, event_bus: EventBus):
        self.worker = Researcher(model)
        self.event_bus = event_bus

    async def __call__(self, event: Event) -> None:
        await self.event_bus.publish(
            Event(
                event_id=str(uuid.uuid4()),
                event_type=EventType.AGENT_STARTED,
                trace_id=event.trace_id,
                workflow_id=event.workflow_id,
                task_id=event.task_id,
                source="researcher",
                target_capability="researcher",
            )
        )
        try:
            instructions = event.payload.get("instructions", "")
            result = await asyncio.to_thread(self.worker.run, instructions)
            await self.event_bus.publish(
                Event(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.AGENT_COMPLETED,
                    trace_id=event.trace_id,
                    workflow_id=event.workflow_id,
                    task_id=event.task_id,
                    source="researcher",
                    target_capability="researcher",
                    payload={"result": result},
                )
            )
        except Exception as exc:
            logger.exception("Researcher handler failed for task %s", event.task_id)
            await self.event_bus.publish(
                Event(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.AGENT_FAILED,
                    trace_id=event.trace_id,
                    workflow_id=event.workflow_id,
                    task_id=event.task_id,
                    source="researcher",
                    target_capability="researcher",
                    payload={
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "retryable": True,
                    },
                )
            )


class WriterHandler:
    def __init__(self, model, event_bus: EventBus):
        self.worker = Writer(model)
        self.event_bus = event_bus

    async def __call__(self, event: Event) -> None:
        await self.event_bus.publish(
            Event(
                event_id=str(uuid.uuid4()),
                event_type=EventType.AGENT_STARTED,
                trace_id=event.trace_id,
                workflow_id=event.workflow_id,
                task_id=event.task_id,
                source="writer",
                target_capability="writer",
            )
        )
        try:
            instructions = event.payload.get("instructions", "")
            result = await asyncio.to_thread(self.worker.run, instructions)
            await self.event_bus.publish(
                Event(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.AGENT_COMPLETED,
                    trace_id=event.trace_id,
                    workflow_id=event.workflow_id,
                    task_id=event.task_id,
                    source="writer",
                    target_capability="writer",
                    payload={"result": result},
                )
            )
        except Exception as exc:
            logger.exception("Writer handler failed for task %s", event.task_id)
            await self.event_bus.publish(
                Event(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.AGENT_FAILED,
                    trace_id=event.trace_id,
                    workflow_id=event.workflow_id,
                    task_id=event.task_id,
                    source="writer",
                    target_capability="writer",
                    payload={
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "retryable": True,
                    },
                )
            )
```

- [ ] **步骤 2：编写 `tests/test_handlers.py`**

```python
import asyncio

import pytest

from events.in_memory import InMemoryEventBus
from events.schema import Event, EventType
from models import Model
from subagents.handlers import ResearcherHandler, WriterHandler


@pytest.mark.asyncio
async def test_researcher_handler_publishes_completed():
    bus = InMemoryEventBus()
    received = []
    bus.subscribe(EventType.AGENT_COMPLETED, lambda e: received.append(e))
    bus.subscribe(EventType.AGENT_STARTED, lambda e: None)
    await bus.start()

    handler = ResearcherHandler(Model(), bus)
    await handler(
        Event(
            event_id="e1",
            event_type=EventType.TASK_READY,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="r1",
            target_capability="researcher",
            payload={"instructions": "research AI"},
        )
    )
    await asyncio.sleep(0.05)

    completed = [e for e in received if e.event_type == EventType.AGENT_COMPLETED]
    assert len(completed) == 1
    assert completed[0].task_id == "r1"
    assert "[Researcher]" in completed[0].payload["result"]

    await bus.stop()


@pytest.mark.asyncio
async def test_writer_handler_publishes_completed():
    bus = InMemoryEventBus()
    received = []
    bus.subscribe(EventType.AGENT_COMPLETED, lambda e: received.append(e))
    bus.subscribe(EventType.AGENT_STARTED, lambda e: None)
    await bus.start()

    handler = WriterHandler(Model(), bus)
    await handler(
        Event(
            event_id="e1",
            event_type=EventType.TASK_READY,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="w1",
            target_capability="writer",
            payload={"instructions": "write poem"},
        )
    )
    await asyncio.sleep(0.05)

    completed = [e for e in received if e.event_type == EventType.AGENT_COMPLETED]
    assert len(completed) == 1
    assert "[Writer]" in completed[0].payload["result"]

    await bus.stop()
```

- [ ] **步骤 3：运行测试**

```bash
uv run pytest tests/test_handlers.py -v
```

预期结果：2 passed。

- [ ] **步骤 4：提交**

```bash
git add subagents/handlers.py tests/test_handlers.py
git commit -m "feat: add async ResearcherHandler and WriterHandler"
```

---

### Task 8：实现 Scheduler

**涉及文件：**
- 创建：`scheduler.py`
- 创建：`tests/test_scheduler.py`

**接口约定：**
- 消费：`EventBus`、`Event`、`EventType`、`ResearcherHandler`、`WriterHandler`
- 产出：`Scheduler`

- [ ] **步骤 1：编写 `scheduler.py`**

```python
"""Deterministic scheduler: routes task.ready events to agent handlers by capability."""

from __future__ import annotations

import logging
import uuid
from typing import Awaitable, Callable

from events.bus import EventBus
from events.schema import Event, EventType

logger = logging.getLogger(__name__)

Handler = Callable[[Event], Awaitable[None]]


class Scheduler:
    """Routes ready tasks to handlers based on target_capability."""

    def __init__(self, event_bus: EventBus, handlers: dict[str, Handler]):
        self.event_bus = event_bus
        self.handlers = handlers
        self._dispatched: set[str] = set()

    async def handle_task_ready(self, event: Event) -> None:
        task_id = event.task_id
        if task_id is None:
            logger.error("task.ready event without task_id: %s", event.event_id)
            return

        dispatch_key = f"{event.workflow_id}:{task_id}"
        if dispatch_key in self._dispatched:
            logger.debug("Task %s already dispatched, ignoring", task_id)
            return
        self._dispatched.add(dispatch_key)

        capability = event.target_capability
        handler = self.handlers.get(capability)
        if handler is None:
            await self.event_bus.publish(
                Event(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.AGENT_FAILED,
                    trace_id=event.trace_id,
                    workflow_id=event.workflow_id,
                    task_id=task_id,
                    source="scheduler",
                    target_capability=capability,
                    payload={"error": f"Unknown capability: {capability}"},
                )
            )
            return

        await self.event_bus.publish(
            Event(
                event_id=str(uuid.uuid4()),
                event_type=EventType.TASK_ASSIGNED,
                trace_id=event.trace_id,
                workflow_id=event.workflow_id,
                task_id=task_id,
                source="scheduler",
                target_capability=capability,
            )
        )
        await handler(event)
```

- [ ] **步骤 2：编写 `tests/test_scheduler.py`**

```python
import asyncio

import pytest

from events.in_memory import InMemoryEventBus
from events.schema import Event, EventType
from scheduler import Scheduler


@pytest.mark.asyncio
async def test_scheduler_routes_researcher():
    bus = InMemoryEventBus()
    calls = []

    async def researcher_handler(event: Event):
        calls.append(("researcher", event.task_id))

    async def writer_handler(event: Event):
        calls.append(("writer", event.task_id))

    scheduler = Scheduler(
        bus, {"researcher": researcher_handler, "writer": writer_handler}
    )
    bus.subscribe(EventType.TASK_READY, scheduler.handle_task_ready)
    bus.subscribe(EventType.TASK_ASSIGNED, lambda e: None)
    await bus.start()

    await bus.publish(
        Event(
            event_id="e1",
            event_type=EventType.TASK_READY,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="r1",
            target_capability="researcher",
        )
    )
    await asyncio.sleep(0.05)

    assert calls == [("researcher", "r1")]
    await bus.stop()


@pytest.mark.asyncio
async def test_scheduler_no_duplicate_dispatch():
    bus = InMemoryEventBus()
    calls = []

    async def researcher_handler(event: Event):
        calls.append(event.task_id)

    scheduler = Scheduler(bus, {"researcher": researcher_handler})
    bus.subscribe(EventType.TASK_READY, scheduler.handle_task_ready)
    bus.subscribe(EventType.TASK_ASSIGNED, lambda e: None)
    await bus.start()

    event = Event(
        event_id="e1",
        event_type=EventType.TASK_READY,
        trace_id="tr-1",
        workflow_id="wf-1",
        task_id="r1",
        target_capability="researcher",
    )
    await bus.publish(event)
    await bus.publish(event)
    await asyncio.sleep(0.05)

    assert calls == ["r1"]
    await bus.stop()


@pytest.mark.asyncio
async def test_scheduler_unknown_capability():
    bus = InMemoryEventBus()
    failed = []
    bus.subscribe(EventType.TASK_READY, Scheduler(bus, {}).handle_task_ready)
    bus.subscribe(EventType.AGENT_FAILED, lambda e: failed.append(e))
    await bus.start()

    await bus.publish(
        Event(
            event_id="e1",
            event_type=EventType.TASK_READY,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="t1",
            target_capability="unknown",
        )
    )
    await asyncio.sleep(0.05)

    assert len(failed) == 1
    assert "Unknown capability" in failed[0].payload["error"]
    await bus.stop()
```

- [ ] **步骤 3：运行测试**

```bash
uv run pytest tests/test_scheduler.py -v
```

预期结果：3 passed。

- [ ] **步骤 4：提交**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: add capability-based Scheduler with idempotency guard"
```

---

### Task 9：实现 WorkflowCoordinator

**涉及文件：**
- 创建：`workflow/coordinator.py`
- 创建：`tests/test_coordinator.py`

**接口约定：**
- 消费：`Workflow`、`TaskGraph`、`EventBus`、`Event`、`EventType`
- 产出：`WorkflowCoordinator`

- [ ] **步骤 1：编写 `workflow/coordinator.py`**

```python
"""WorkflowCoordinator advances Task Graph state based on events."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from events.bus import EventBus
from events.schema import Event, EventType
from workflow.graph import TaskGraph
from workflow.state import TaskStatus, Workflow, WorkflowStatus

logger = logging.getLogger(__name__)


class WorkflowCoordinator:
    """Owns workflow state, publishes ready tasks, and resumes on completed/failed events."""

    def __init__(
        self,
        event_bus: EventBus,
        max_retries: int = 2,
    ):
        self.event_bus = event_bus
        self.max_retries = max_retries
        self._workflows: dict[str, Workflow] = {}
        self._completions: dict[str, asyncio.Future] = {}

    def register(self, workflow: Workflow) -> None:
        self._workflows[workflow.workflow_id] = workflow

    def create_future(self, workflow_id: str) -> asyncio.Future:
        return asyncio.get_event_loop().create_future()

    def set_completion_future(
        self, workflow_id: str, future: asyncio.Future
    ) -> None:
        self._completions[workflow_id] = future

    async def start_workflow(self, workflow: Workflow) -> None:
        graph = TaskGraph(workflow)
        graph.validate()
        workflow.status = WorkflowStatus.EXECUTING
        self.register(workflow)
        await self._publish_ready_tasks(workflow)

    async def handle_task_completed(self, event: Event) -> None:
        workflow = self._workflows.get(event.workflow_id)
        if workflow is None or event.task_id is None:
            return
        graph = TaskGraph(workflow)

        task = workflow.tasks.get(event.task_id)
        if task is None:
            return
        if task.status == TaskStatus.COMPLETED:
            return  # idempotent

        graph.mark_completed(event.task_id, event.payload.get("result"))
        await self._publish_ready_tasks(workflow)
        await self._check_completion(workflow)

    async def handle_task_failed(self, event: Event) -> None:
        workflow = self._workflows.get(event.workflow_id)
        if workflow is None or event.task_id is None:
            return
        graph = TaskGraph(workflow)

        task = workflow.tasks.get(event.task_id)
        if task is None:
            return

        retryable = event.payload.get("retryable", False)
        if retryable and task.retry_count < self.max_retries:
            task.retry_count += 1
            task.status = TaskStatus.RETRYING
            task.status = TaskStatus.READY
            await self._publish_event_for_task(task, workflow)
            return

        graph.mark_failed(event.task_id, event.payload)
        self._block_downstream(workflow, event.task_id)
        await self._check_completion(workflow)

    def _block_downstream(self, workflow: Workflow, failed_task_id: str) -> None:
        graph = TaskGraph(workflow)
        for task in workflow.tasks.values():
            if failed_task_id in task.dependencies and task.status == TaskStatus.PENDING:
                graph.mark_blocked(task.task_id)

    async def _publish_ready_tasks(self, workflow: Workflow) -> None:
        graph = TaskGraph(workflow)
        for task in graph.ready_tasks():
            graph.mark_ready(task.task_id)
            await self._publish_event_for_task(task, workflow)

    async def _publish_event_for_task(self, task, workflow: Workflow) -> None:
        if task.status not in (TaskStatus.READY, TaskStatus.RETRYING):
            return
        task.status = TaskStatus.DISPATCHED
        await self.event_bus.publish(
            Event(
                event_id=str(uuid.uuid4()),
                event_type=EventType.TASK_READY,
                trace_id=workflow.trace_id,
                workflow_id=workflow.workflow_id,
                task_id=task.task_id,
                source="coordinator",
                target_capability=task.target_capability,
                payload={
                    "instructions": task.instructions,
                    "input": task.input,
                    "input_refs": task.input_refs,
                },
                metadata={"retry_count": task.retry_count},
            )
        )

    async def _check_completion(self, workflow: Workflow) -> None:
        graph = TaskGraph(workflow)
        if graph.is_complete():
            workflow.status = WorkflowStatus.COMPLETED
            await self.event_bus.publish(
                Event(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.WORKFLOW_COMPLETED,
                    trace_id=workflow.trace_id,
                    workflow_id=workflow.workflow_id,
                    source="coordinator",
                    payload={"workflow_id": workflow.workflow_id},
                )
            )
            self._resolve_completion_future(workflow.workflow_id)
        elif graph.has_failed_required():
            workflow.status = WorkflowStatus.FAILED
            await self.event_bus.publish(
                Event(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.WORKFLOW_FAILED,
                    trace_id=workflow.trace_id,
                    workflow_id=workflow.workflow_id,
                    source="coordinator",
                )
            )
            self._resolve_completion_future(workflow.workflow_id)
        elif not graph.ready_tasks():
            workflow.status = WorkflowStatus.WAITING

    def _resolve_completion_future(self, workflow_id: str) -> None:
        future = self._completions.pop(workflow_id, None)
        if future is not None and not future.done():
            future.set_result(None)
```

- [ ] **步骤 2：编写 `tests/test_coordinator.py`**

```python
import asyncio

import pytest

from events.in_memory import InMemoryEventBus
from events.schema import Event, EventType
from workflow.coordinator import WorkflowCoordinator
from workflow.state import Task, TaskStatus, Workflow


def make_wf(*tasks: Task) -> Workflow:
    return Workflow(
        workflow_id="wf-1",
        trace_id="tr-1",
        user_input="test",
        tasks={t.task_id: t for t in tasks},
    )


@pytest.mark.asyncio
async def test_coordinator_publishes_ready_tasks():
    bus = InMemoryEventBus()
    ready_events = []
    bus.subscribe(EventType.TASK_READY, lambda e: ready_events.append(e))
    await bus.start()

    coord = WorkflowCoordinator(bus)
    wf = make_wf(Task("r1", "research", "researcher", "do research"))
    await coord.start_workflow(wf)
    await asyncio.sleep(0.05)

    assert len(ready_events) == 1
    assert ready_events[0].task_id == "r1"
    await bus.stop()


@pytest.mark.asyncio
async def test_coordinator_triggers_downstream():
    bus = InMemoryEventBus()
    ready_events = []
    completed_events = []
    bus.subscribe(EventType.TASK_READY, lambda e: ready_events.append(e))
    bus.subscribe(EventType.WORKFLOW_COMPLETED, lambda e: completed_events.append(e))
    await bus.start()

    coord = WorkflowCoordinator(bus)
    r1 = Task("r1", "research", "researcher", "do research")
    w1 = Task("w1", "write", "writer", "write", dependencies=["r1"])
    wf = make_wf(r1, w1)
    await coord.start_workflow(wf)

    # 模拟 Researcher 完成。
    await coord.handle_task_completed(
        Event(
            event_id="e1",
            event_type=EventType.AGENT_COMPLETED,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="r1",
            source="researcher",
            payload={"result": "research result"},
        )
    )
    await asyncio.sleep(0.05)

    assert any(e.task_id == "w1" for e in ready_events)
    await bus.stop()


@pytest.mark.asyncio
async def test_coordinator_workflow_completed():
    bus = InMemoryEventBus()
    completed = []
    bus.subscribe(EventType.WORKFLOW_COMPLETED, lambda e: completed.append(e))
    await bus.start()

    coord = WorkflowCoordinator(bus)
    wf = make_wf(Task("w1", "write", "writer", "write"))
    await coord.start_workflow(wf)
    await coord.handle_task_completed(
        Event(
            event_id="e1",
            event_type=EventType.AGENT_COMPLETED,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="w1",
            source="writer",
            payload={"result": "done"},
        )
    )
    await asyncio.sleep(0.05)

    assert len(completed) == 1
    assert wf.status.name == "COMPLETED"
    await bus.stop()
```

- [ ] **步骤 3：运行测试**

```bash
uv run pytest tests/test_coordinator.py -v
```

预期结果：3 passed。

- [ ] **步骤 4：提交**

```bash
git add workflow/coordinator.py tests/test_coordinator.py
git commit -m "feat: add WorkflowCoordinator for state advancement"
```

---

### Task 10：扩展 Supervisor 支持事件驱动分支

**涉及文件：**
- 修改：`agent.py`
- 创建：`tests/test_supervisor.py`

**接口约定：**
- 消费：`Workflow`、`TaskGraph`、`EventBus`、`WorkflowCoordinator`、`Scheduler`
- 产出：当 `ENABLE_EVENT_DRIVEN=true` 时，`Agent.process_turn` 可运行事件驱动分支

- [ ] **步骤 1：在 `agent.py` 顶部添加导入和辅助方法**

在现有导入之后添加：

```python
import asyncio
import uuid

from events.bus import EventBus
from events.in_memory import InMemoryEventBus
from events.schema import Event, EventType
from scheduler import Scheduler
from subagents.handlers import ResearcherHandler, WriterHandler
from workflow.coordinator import WorkflowCoordinator
from workflow.graph import TaskGraph, TaskGraphError
from workflow.state import Task, TaskStatus, Workflow, WorkflowStatus
```

在 `Agent` 类中添加将 LLM 计划 JSON 转换为 `Task` 对象的方法：

```python
    def _build_tasks_from_plan(self, tasks_data: list[dict]) -> dict[str, Task]:
        """Convert LLM task plan into Task objects."""
        tasks: dict[str, Task] = {}
        for item in tasks_data:
            task = Task(
                task_id=item["task_id"],
                task_type=item.get("task_type", "generic"),
                target_capability=item["target_capability"],
                instructions=item["instructions"],
                input=item.get("input"),
                dependencies=item.get("dependencies", []),
                input_refs=item.get("input_refs", []),
                required_for_completion=item.get("required_for_completion", True),
            )
            tasks[task.task_id] = task
        return tasks
```

添加生成新规划 prompt 的方法：

```python
    def _build_planning_prompt_v2(self, user_input: str) -> str:
        return (
            "You are a supervisor agent. You can delegate tasks to two capabilities:\n"
            "- researcher: good at research, analysis, and summarization\n"
            "- writer: good at writing, copywriting, and content generation\n\n"
            "Based on the user's request, decide whether to answer directly or "
            "delegate to one or more tasks. Tasks may run in parallel if they have "
            "no dependencies. A writer task may depend on researcher results.\n\n"
            "Respond with a JSON object in one of these forms:\n"
            '{"action": "direct", "response": "your direct answer"}\n'
            'or\n'
            '{"action": "delegate", "tasks": [{"task_id": "research_001", "task_type": "research", "target_capability": "researcher", "instructions": "...", "dependencies": [], "input_refs": [], "required_for_completion": true}, ...]}\n\n'
            f"User request: {user_input}\n"
            "Decision:"
        )
```

- [ ] **步骤 2：在 `Agent` 中添加事件驱动处理方法**

```python
    def _event_driven_enabled(self):
        return self.config.get("ENABLE_EVENT_DRIVEN", "false").lower() == "true"

    async def _process_turn_event_driven(self, user_input: str) -> str:
        """Run the turn using event-driven task scheduling."""
        event_bus = InMemoryEventBus()
        coordinator = WorkflowCoordinator(event_bus)
        scheduler = Scheduler(
            event_bus,
            {
                "researcher": ResearcherHandler(self.model, event_bus),
                "writer": WriterHandler(self.model, event_bus),
            },
        )

        event_bus.subscribe(EventType.TASK_READY, scheduler.handle_task_ready)
        event_bus.subscribe(EventType.AGENT_COMPLETED, coordinator.handle_task_completed)
        event_bus.subscribe(EventType.AGENT_FAILED, coordinator.handle_task_failed)
        await event_bus.start()

        try:
            prompt = self._build_planning_prompt_v2(user_input)
            raw = self.model.complete(prompt)
            decision = self._parse_plan_v2(raw)

            if decision.get("action") == "direct":
                return decision.get("response", "")

            workflow = Workflow(
                workflow_id=str(uuid.uuid4()),
                trace_id=str(uuid.uuid4()),
                user_input=user_input,
                tasks=self._build_tasks_from_plan(decision.get("tasks", [])),
            )

            loop = asyncio.get_event_loop()
            future = loop.create_future()
            coordinator.set_completion_future(workflow.workflow_id, future)
            await coordinator.start_workflow(workflow)
            await future

            return self._finalize_workflow(workflow, user_input)
        finally:
            await event_bus.stop()

    def _parse_plan_v2(self, raw: str) -> dict:
        """Parse LLM output; on failure fall back to direct response."""
        raw = raw.strip()
        try:
            decision = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return {"action": "direct", "response": raw}
            try:
                decision = json.loads(match.group(0))
            except json.JSONDecodeError:
                return {"action": "direct", "response": raw}

        action = decision.get("action")
        if action == "direct" and "response" in decision:
            return decision
        if action == "delegate":
            tasks = decision.get("tasks", [])
            if isinstance(tasks, list):
                return decision
        return {"action": "direct", "response": raw}

    def _finalize_workflow(self, workflow: Workflow, user_input: str) -> str:
        """Produce final response from completed workflow."""
        if workflow.status == WorkflowStatus.FAILED:
            return f"[Workflow failed] {workflow.error or 'unknown error'}"

        completed = [
            t for t in workflow.tasks.values() if t.status == TaskStatus.COMPLETED
        ]
        if not completed:
            return "[No tasks completed]"

        # 如果只有一个必需的已完成任务，直接返回其结果。
        required_completed = [t for t in completed if t.required_for_completion]
        if len(required_completed) == 1:
            return str(required_completed[0].result)

        # 否则进行汇总。
        results = [
            {"agent": t.target_capability, "result": t.result} for t in completed
        ]
        return self._summarize(user_input, results, self.context.get(), self.memory)
```

- [ ] **步骤 3：修改 `Agent.process_turn` 增加分支判断**

将现有的 `process_turn` 方法替换为分发器：

```python
    def process_turn(self, user_input: str) -> str:
        if self._context_enabled():
            self.context.update(user_input)

        if self._event_driven_enabled():
            result = asyncio.run(self._process_turn_event_driven(user_input))
        else:
            result = self._process_turn_sync(user_input)

        if self._memory_enabled():
            self._remember(user_input, result)

        return str(result)

    def _process_turn_sync(self, user_input: str) -> str:
        """Original synchronous implementation (preserved)."""
        plan = self._plan(user_input, self.context.get(), self.memory)

        if plan.get("action") == "delegate":
            results = []
            for task in plan.get("tasks", []):
                agent_result = self.tool.execute(
                    "task",
                    {"agent": task["agent"], "description": task["description"]},
                )
                results.append({"agent": task["agent"], "result": agent_result})
            used_agents = ", ".join(r["agent"] for r in results)
            prefix = f"[使用了子agent: {used_agents}]\n\n"
            summary = self._summarize(
                user_input, results, self.context.get(), self.memory
            )
            result = prefix + summary
        else:
            result = plan.get("response", "")

        return str(result)
```

- [ ] **步骤 4：编写 `tests/test_supervisor.py`**

使用一个 stub model 返回确定性的规划 JSON，这样测试不需要网络访问。

```python
import pytest

from agent import Agent


class StubMemory:
    def retrieve(self, key):
        return None

    def store(self, key, value):
        pass


class StubContext:
    def update(self, user_input):
        pass

    def get(self):
        return {}


class StubModel:
    def __init__(self, response: str):
        self._response = response

    def complete(self, prompt: str) -> str:
        return self._response


def make_agent(model_response: str) -> Agent:
    agent = Agent(StubContext(), StubMemory())
    agent.model = StubModel(model_response)
    return agent


def test_supervisor_direct_answer():
    agent = make_agent('{"action": "direct", "response": "hello"}')
    assert agent.process_turn("hi") == "hello"


def test_supervisor_event_driven_writer_only():
    plan = (
        '{"action": "delegate", "tasks": ['
        '{"task_id": "write_001", "task_type": "write", "target_capability": "writer", '
        '"instructions": "write poem", "dependencies": [], "input_refs": [], "required_for_completion": true}'
        ']}'
    )
    agent = make_agent(plan)
    response = agent.process_turn("write a poem")
    assert "[Writer]" in response


def test_supervisor_event_driven_researcher_then_writer():
    plan = (
        '{"action": "delegate", "tasks": ['
        '{"task_id": "research_001", "task_type": "research", "target_capability": "researcher", '
        '"instructions": "research AI", "dependencies": [], "input_refs": [], "required_for_completion": true},'
        '{"task_id": "write_001", "task_type": "write", "target_capability": "writer", '
        '"instructions": "write report", "dependencies": ["research_001"], "input_refs": ["research_001.result"], "required_for_completion": true}'
        ']}'
    )
    agent = make_agent(plan)
    response = agent.process_turn("research and report")
    assert "[Writer]" in response
```

- [ ] **步骤 5：运行测试**

```bash
uv run pytest tests/test_supervisor.py -v
```

预期结果：3 passed。

- [ ] **步骤 6：提交**

```bash
git add agent.py tests/test_supervisor.py
git commit -m "feat: add event-driven Supervisor branch with sync fallback"
```

---

### Task 11：更新 loop.py 以支持异步事件循环生命周期

**涉及文件：**
- 修改：`loop.py`

**接口约定：**
- 没有新的公共接口；REPL 继续同步调用 `agent.process_turn()`。

- [ ] **步骤 1：修改 `loop.py`，在启用事件驱动模式时添加共享 EventBus 的启动/关闭**

由于当前 `agent.py` 每轮会创建一个新的 EventBus，因此 `loop.py` 的改动很小。我们只需要添加一个可选的共享 EventBus 占位符和退出时的清理钩子：

```python
import asyncio


def run_loop() -> None:
    """Run the synchronous CLI REPL loop."""
    context = Context()
    memory = Memory()
    # Use a throw-away Agent just to read the display name from config.
    print(f"{Agent(context, memory).name} is ready. Type 'exit' or 'quit' to stop.")
    try:
        while True:
            try:
                user_input = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit"}:
                print("Goodbye.")
                break

            # Recreate the Agent each turn with the current Context and Memory.
            agent = Agent(context=context, memory=memory)
            response = agent.process_turn(user_input)
            print(response)
    finally:
        # Ensure any lingering asyncio tasks from event-driven turns are cleaned up.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.stop()
        except RuntimeError:
            pass
```

因为 `agent.py` 每轮使用 `asyncio.run()`，所以这一阶段不需要共享的事件循环。此改动是防御性清理。

- [ ] **步骤 2：运行 REPL 冒烟测试**

```bash
printf 'hello\nquit\n' | uv run loop.py
```

预期结果：打印响应并干净退出。

- [ ] **步骤 3：提交**

```bash
git add loop.py
git commit -m "chore: add defensive asyncio cleanup in REPL exit"
```

---

### Task 12：更新环境配置文档

**涉及文件：**
- 修改：`.env.example`

**接口约定：**
- 记录 `ENABLE_EVENT_DRIVEN`。

- [ ] **步骤 1：在 `.env.example` 中追加配置**

在现有变量之后添加：

```bash
# Example: Enable event-driven agent orchestration (true/false)
# When false, the original synchronous task tool path is used.
ENABLE_EVENT_DRIVEN=false

# Example: Maximum retries for failed sub-agent tasks in event-driven mode
MAX_RETRIES=2
```

- [ ] **步骤 2：提交**

```bash
git add .env.example
git commit -m "docs: document ENABLE_EVENT_DRIVEN and MAX_RETRIES"
```

---

### Task 13：添加同步回退兼容性测试

**涉及文件：**
- 创建：`tests/test_sync_fallback.py`

**接口约定：**
- 消费：`Agent` 在 `ENABLE_EVENT_DRIVEN=false` 下的行为
- 产出：确认原有路径仍然可用

- [ ] **步骤 1：编写 `tests/test_sync_fallback.py`**

```python
import pytest

from agent import Agent


class StubMemory:
    def retrieve(self, key):
        return None

    def store(self, key, value):
        pass


class StubContext:
    def update(self, user_input):
        pass

    def get(self):
        return {}


class StubModel:
    def complete(self, prompt: str) -> str:
        return '{"action": "delegate", "tasks": [{"agent": "writer", "description": "write poem"}]}'


def test_sync_path_still_works(monkeypatch):
    monkeypatch.setenv("ENABLE_EVENT_DRIVEN", "false")
    agent = Agent(StubContext(), StubMemory())
    agent.model = StubModel()
    response = agent.process_turn("write a poem")
    assert "[Writer]" in response
    assert "[使用了子agent:" in response
```

- [ ] **步骤 2：运行测试**

```bash
uv run pytest tests/test_sync_fallback.py -v
```

预期结果：1 passed。

- [ ] **步骤 3：提交**

```bash
git add tests/test_sync_fallback.py
git commit -m "test: verify synchronous task tool path remains functional"
```

---

### Task 14：运行完整测试套件并修复回归

**涉及文件：**
- 所有测试文件

- [ ] **步骤 1：运行全部测试**

```bash
uv run pytest tests/ -v
```

预期结果：所有测试通过。

- [ ] **步骤 2：对两种模式运行 REPL 冒烟测试**

同步模式：

```bash
printf '帮我写一篇关于秋天的散文\nquit\n' | uv run loop.py
```

事件驱动模式：

```bash
ENABLE_EVENT_DRIVEN=true printf '帮我写一篇关于秋天的散文\nquit\n' | uv run loop.py
```

预期结果：两种模式都产生 Writer 结果并干净退出。

- [ ] **步骤 3：提交任何修复**

```bash
git add -A
git commit -m "fix: address regressions from full test suite run"
```

---

## 自检

### 1. 需求覆盖

| 设计需求 | 实现 Task |
|---|---|
| 动态 Task Graph，含 task_id、dependencies、input_refs、required_for_completion | Task 2、Task 3 |
| Task Graph 校验（重复 task_id、未知依赖、循环依赖） | Task 3 |
| READY 任务计算 | Task 3 |
| Event Schema，含 event_id、event_type、trace_id、workflow_id 等 | Task 4 |
| EventBus 抽象 + InMemoryEventBus | Task 5、Task 6 |
| Scheduler 按 capability 路由 | Task 8 |
| Researcher/Writer 异步 Handler | Task 7 |
| Workflow 状态推进和完成检测 | Task 9 |
| Supervisor 从调用工具改为生成执行计划 | Task 10 |
| 通过 ENABLE_EVENT_DRIVEN 保留同步回退 | Task 10、Task 13 |
| 重试和 BLOCKED 处理 | Task 9 |
| 幂等（不重复派发） | Task 8、Task 9 |
| 外部同步 REPL 仍能返回结果 | Task 10、Task 11 |

未发现遗漏。

### 2. 占位符检查

- 没有 `TBD`、`TODO` 或 "implement later"。
- 没有模糊的 "add error handling" 步骤而无代码。
- 所有 Task 都包含精确文件路径、代码块、命令和预期输出。

### 3. 类型一致性

- `Task.task_id` 在所有地方都是 `str`。
- `EventBus.publish` 统一接收 `Event` 并返回 `Awaitable[None]`。
- `Scheduler` 的 handler 统一为 `Callable[[Event], Awaitable[None]]`。
- `WorkflowCoordinator` 统一使用 `workflow.workflow_id` 作为字典键。

已修复：`workflow/coordinator.py` 原先把 `import asyncio` 内联在 `create_future` 中，已移至文件顶部。

---

## 执行交接

计划已完成并保存到 `docs/superpowers/plans/2026-07-02-event-driven-agents-plan.md`。

两种执行方式可选：

**1. Subagent-Driven（推荐）** —— 每个 Task 派一个独立子 Agent 实现，我在每个 Task 完成后检查再进入下一个。迭代快、边界清晰。

**2. Inline Execution** —— 在本会话中使用 `executing-plans` 技能连续执行多个 Task，按检查点批量推进。

你想用哪种方式开始实现？
