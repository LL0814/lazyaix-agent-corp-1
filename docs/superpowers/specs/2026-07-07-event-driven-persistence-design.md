# 事件驱动架构持久化与分布式改造设计

> 日期：2026-07-07  
> 状态：已审核通过，待生成 Implementation Plan  
> 范围：在当前进程内事件驱动实现基础上，渐进式引入 PostgreSQL、Kafka、Redis，实现持久化、跨进程通信、分布式幂等和恢复能力。

---

## 1. 当前真实架构和调用链

### 1.1 核心文件与模型

| 文件 | 职责 |
|------|------|
| `events/schema.py` | `Event` 数据类、`EventType` 常量 |
| `events/bus.py` | `EventBus` Protocol |
| `events/in_memory.py` | `InMemoryEventBus` |
| `workflow/state.py` | `Workflow`、`Task`、`TaskStatus`、`WorkflowStatus` |
| `workflow/graph.py` | `TaskGraph`（DAG 验证、就绪判断、状态推进） |
| `workflow/coordinator.py` | `WorkflowCoordinator` |
| `scheduler.py` | `Scheduler` |
| `subagents/handlers.py` | `ResearcherHandler`、`WriterHandler` |
| `subagents/workers.py` | `Researcher`、`Writer`（同步 `run()`） |
| `agent.py` | `Agent` 组装、事件驱动入口 `_process_turn_event_driven`、同步兼容入口 `_process_turn_sync` |
| `loop.py` | REPL CLI 入口 |
| `pyproject.toml` | 仅依赖 `python-dotenv`、`pytest`、`pytest-asyncio` |
| `.env.example` | 环境变量示例 |

### 1.2 真实调用链

用户输入
→ `loop.py:run_loop()` 读取输入
→ `loop.py:76` `agent.process_turn(user_input)`
→ `agent.py:454` `process_turn()`
  → `agent.py:458` 若 `ENABLE_EVENT_DRIVEN=true` 则 `asyncio.run(self._process_turn_event_driven(user_input))`

事件驱动路径：
1. `agent.py:235` 创建 `InMemoryEventBus`
2. `agent.py:237` 创建 `WorkflowCoordinator(event_bus, max_retries=...)`
3. `agent.py:238` 创建 `Scheduler(event_bus, {researcher: ..., writer: ...})`
4. `agent.py:246-248` 订阅：
   - `TASK_READY → scheduler.handle_task_ready`
   - `AGENT_COMPLETED → coordinator.handle_task_completed`
   - `AGENT_FAILED → coordinator.handle_task_failed`
5. `agent.py:253` LLM 规划 `_build_planning_prompt_v2`
6. `agent.py:264` 创建 `Workflow` 和 `tasks`
7. `agent.py:267-268` 创建 `asyncio.Future` 并通过 `set_completion_future` 注册
8. `agent.py:269` `coordinator.start_workflow(workflow)`
9. `workflow/coordinator.py:40` 创建 `TaskGraph(workflow)` 并 `validate()`
10. `workflow/coordinator.py:45` `_publish_ready_tasks(workflow)` 发布 `TASK_READY`
11. `scheduler.py:43` `handle_task_ready` 根据 `target_capability` 路由
12. `scheduler.py:84` 发布 `TASK_ASSIGNED` 并 `spawn_handler`
13. `subagents/handlers.py:21/73` Agent Handler 执行：
    - 发布 `AGENT_STARTED`
    - `asyncio.to_thread(self.worker.run, instructions)`
    - 发布 `AGENT_COMPLETED` 或 `AGENT_FAILED`
14. `workflow/coordinator.py:47/65` Coordinator 消费完成/失败事件，更新状态，触发下游
15. `agent.py:277` `await asyncio.wait_for(future, timeout=...)`
16. `agent.py:308` `_finalize_workflow(workflow, user_input)` 生成最终回复

### 1.3 与参考描述的差异

| 参考描述 | 真实代码 |
|----------|----------|
| "Supervisor 生成 Workflow 和 TaskGraph" | `Agent._process_turn_event_driven` 生成 `Workflow` 和 `tasks`；`TaskGraph` 在 `WorkflowCoordinator.start_workflow` 中临时创建 |
| "EventBus Protocol" | 存在，位于 `events/bus.py` |
| "InMemoryEventBus 基于 asyncio.Queue" | 正确，每个 event_type/handler 有独立 `asyncio.Queue` |
| `_event_driven_enabled()` | 位于 `agent.py:153`，读取 `ENABLE_EVENT_DRIVEN` |
| "completion Future" | 在 `agent.py:267` 创建，`coordinator._completions` 在 `agent.py:268` 注册 |
| "Scheduler 重复调度记录" | `scheduler.py:24` `self._dispatched: set[str]` |
| "WorkflowCoordinator 中 Workflow 状态" | `workflow/coordinator.py:24` `self._workflows: dict[str, Workflow]` |
| 参考 Event Schema 含 `aggregate_id`、`priority`、`parent_event_id` | 当前 `events/schema.py` **没有**这些字段，只有 `parent_task_id` |
| Task 含 `max_retries`、`priority`、`target_agent` | 当前 `workflow/state.py` **没有**，只有 `retry_count` |
| Workflow 含 `version`、`parent_workflow_id`、`aggregate_id`、`final_result` | 当前 **没有** |

---

## 2. 当前内存实现存在的问题

结合真实代码，当前局限如下：

1. **Event 仅存进程内存**：`InMemoryEventBus._queues` 是进程内 `asyncio.Queue`。
2. **程序退出丢失未处理事件**：无持久化。
3. **Workflow 状态仅存内存**：`WorkflowCoordinator._workflows`。
4. **完成通知仅存内存**：`WorkflowCoordinator._completions` 是 `asyncio.Future`，不能跨进程。
5. **调度幂等仅存内存**：`Scheduler._dispatched` 是 `set`。
6. **重启无法恢复 Workflow**：`_workflows` 为空。
7. **无法拆分到多进程/服务**：事件总线和状态都在同一进程。
8. **多实例重复调度风险**：`_dispatched` 不共享。
9. **无可靠重试、死信、回放、审计**：依赖内存 set 和 Future。
10. **无持久化 Agent Registry/Checkpoint**：目前无此概念。

---

## 3. 对参考 Kafka Topic 设计的评估

参考设计建议的 Topic：

- `events.ingress.high/normal/low`
- `events.assigned`
- `events.agent.{agent_id}`
- `events.status`
- `events.retry`
- `events.dlq`
- `events.memory.add`
- `agent.registry`
- `agent.commands`

### 3.1 评估结论

| Topic | 是否适合当前项目 | 理由 |
|-------|------------------|------|
| `events.ingress.high/normal/low` | **第一版不需要** | Kafka 不保证严格优先级；当前只有两个 Agent 类型，一个 `task.ready` Topic 足够 |
| `events.assigned` | 可以考虑 | 用于审计和 Agent 消费确认，但第一版可合并到 `agent.status` 或直接省略 |
| `events.agent.{agent_id}` | **不推荐** | 动态 Topic 管理成本高，Agent 扩缩容需要创建/删除 Topic |
| `events.status` | 推荐，但建议拆分 | Agent 状态和 Workflow 状态消费方不同 |
| `events.retry` | 后续扩展 | 第一版可在业务内通过 metadata `retry_count` 重新发布 `task.ready` 实现 |
| `events.dlq` | 后续扩展 | 第一版可先用 PostgreSQL `dlq` 表 + Kafka DLQ Topic |
| `events.memory.add` | **不需要** | 当前项目无全局 Memory 服务化需求 |
| `agent.registry` | **第一版不需要** | 当前只有 Researcher 和 Writer，硬编码 capability 映射足够 |
| `agent.commands` | **第一版不需要** | 当前无动态 Agent 管理需求 |

### 3.2 关于入站 Topic 优先级

- Kafka 本身不支持消息优先级。
- 多个 Topic 模拟优先级可行，但 Consumer 需要优先拉取 high Topic，可能导致 normal/low 饥饿。
- 当前项目第一版只需要一个 **`task.ready`** Topic。
- `priority` 可以作为 Event 字段保留，但消费策略先按 FIFO。
- 只有当系统明确需要 SLA 分级（如实时任务 vs 批量任务）时才拆分为多个 Topic。

---

## 4. 推荐 Kafka Topic 方案

### 4.1 第一版最小 Topic 集合

| Topic | 用途 | Key |
|-------|------|-----|
| `task.ready` | Coordinator 发布就绪任务 | `task_id`（允许同一 Workflow 内多任务并行） |
| `task.assigned` | Scheduler 确认任务已分配（审计/追踪） | `task_id` |
| `agent.status` | Agent 上报 started/completed/failed | `task_id` |
| `workflow.status` | Workflow 完成/失败/恢复 | `workflow_id` |
| `outbox.events`（可选） | 若不用内嵌 Producer，可用此 Topic 中转 | `aggregate_id`/`workflow_id` |
| `dlq` | 死信 | `workflow_id` 或 `task_id` |

### 4.2 不推荐 per-agent Topic

- `events.agent.{agent_id}` 需要动态创建 Topic，增加运维成本。
- 当前只有两个 capability：researcher、writer。
- 推荐按 capability 划分消费者组，而不是按 Topic。

### 4.3 推荐方案：按 capability 消费组

方案 B 的变体：

- **一个 `task.ready` Topic**，所有 Coordinator 生产。
- **Capability Consumer Group**：
  - Group: `researcher-workers` 消费 `task.ready`，过滤 `target_capability=researcher`。
  - Group: `writer-workers` 消费 `task.ready`，过滤 `target_capability=writer`。

这样多个 Researcher/Writer 实例可以竞争消费，扩缩容无需改 Topic。

---

## 5. 推荐分区键和 Consumer Group 方案

### 5.1 aggregate_id 定义

- **当前项目不需要单独的 `aggregate_id` 字段**。
- 对 Workflow 级别事件，`aggregate_id` 等价于 `workflow_id`。
- 对 Task 级别事件，业务聚合仍是 Workflow，但分区键可用 `task_id` 以提高并行度。

### 5.2 分区策略

| 事件类型 | Topic | Key | 分区依据 | 理由 |
|----------|-------|-----|----------|------|
| `task.ready` | `task.ready` | `task_id` | 任务级 | 同一 Workflow 多个任务可并行执行 |
| `task.assigned` | `task.assigned` | `task_id` | 任务级 | 追踪单个任务 |
| `agent.started/completed/failed` | `agent.status` | `task_id` | 任务级 | Agent 任务并行 |
| `workflow.completed/failed/resume` | `workflow.status` | `workflow_id` | Workflow 级 | 保证 Workflow 状态事件有序 |
| Outbox 事件 | `outbox.events` 或直接 send | `workflow_id` | Workflow 级 | 同一 Workflow 事件顺序写入 |

### 5.3 Consumer Group

| 组件 | Consumer Group | 订阅 Topic | 说明 |
|------|----------------|------------|------|
| Scheduler/Agent Router | `agent-coordinators` | `task.ready` | 可多个实例，按 capability 过滤 |
| Researcher Workers | `researcher-workers` | `task.ready` | 竞争消费 researcher 任务 |
| Writer Workers | `writer-workers` | `task.ready` | 竞争消费 writer 任务 |
| WorkflowCoordinator | `workflow-coordinators` | `agent.status` + `workflow.status` | 推进 Workflow |
| Outbox Publisher | `outbox-publishers` | `outbox.events` 或轮询 DB | 发送待发布事件 |

### 5.4 取舍结论

- **工作流推进类事件使用 `workflow_id` 分区**（有序）。
- **Agent 独立执行任务使用 `task_id` 分区**（并行）。
- 不直接使用 `user_id` 作为分区键。

---

## 6. 优化后的 Event Schema

基于当前 `events/schema.py` 扩展：

```python
@dataclass
class Event:
    # 必要标识
    event_id: str
    event_type: str
    trace_id: str
    workflow_id: str
    task_id: str | None = None
    parent_task_id: str | None = None
    parent_event_id: str | None = None   # 新增
    aggregate_id: str | None = None       # 新增；默认等于 workflow_id

    # 路由字段
    source: str = "supervisor"
    target_agent: str | None = None
    target_capability: str | None = None
    priority: str = "normal"              # 新增

    # 时间
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # 数据
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 6.1 字段说明

| 字段 | 必要性 | 说明 |
|------|--------|------|
| `event_id` | 必须 | 全局唯一 |
| `trace_id` | 必须 | 调用链 |
| `workflow_id` | 必须 | 所属 Workflow |
| `task_id` | 任务事件必须 | 任务级事件 |
| `parent_event_id` | 可选 | 当前 Event 由哪条 Event 产生，建议保留 |
| `parent_task_id` | 可选 | 当前 Task 的父任务或拆分来源 |
| `aggregate_id` | 可选，默认=workflow_id | Kafka key/聚合标识 |

### 6.2 路由优先级

- `target_capability` 用于 Scheduler 路由。
- `target_agent` 用于指定具体 Agent 实例（第一版通常为空）。
- 若 `target_agent` 非空且 Agent 在线，优先路由到该 Agent；否则按 capability 路由。

### 6.3 Payload vs Metadata

| Payload 业务字段 | Metadata 系统字段 |
|------------------|-------------------|
| `instructions` | `retry_count` |
| `input` | `max_retries` |
| `input_refs` | `idempotency_key` |
| `result` | `correlation_id` |
| `error` | `schema_version` |
| `task_type` | `attempt` |
| | `original_event_id`（用于 retry） |
| | `checkpoint_id` |

### 6.4 序列化

- 第一阶段使用 **JSON**。
- `datetime` → ISO 8601 字符串。
- `Enum` → 字符串。
- `Any` 限制为 JSON 可序列化类型（str、int、float、bool、None、list、dict）。
- 后续可迁移到 Avro + Schema Registry。

---

## 7. ID 关系

| ID | 作用 | 关系 |
|----|------|------|
| `event_id` | 一条 Event 唯一标识 | 由生产者生成 UUID |
| `trace_id` | 端到端追踪 | 一个 User Request 一个 trace_id |
| `workflow_id` | Workflow 唯一标识 | 一个 trace_id 可对应多个 workflow（未来） |
| `task_id` | Task 唯一标识 | 属于一个 workflow_id |
| `parent_task_id` | 父任务/拆分来源 | 可选 |
| `aggregate_id` | Kafka 聚合键 | 默认等于 `workflow_id`；Kafka key 可为 `task_id` |

---

## 8. PostgreSQL 表结构

### 8.1 `workflows`

```sql
CREATE TABLE workflows (
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
```

### 8.2 `tasks`

```sql
CREATE TABLE tasks (
    task_id UUID PRIMARY KEY,
    workflow_id UUID NOT NULL REFERENCES workflows(workflow_id),
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
```

### 8.3 `task_dependencies`

推荐 **方案 B：独立表**。

```sql
CREATE TABLE task_dependencies (
    workflow_id UUID NOT NULL REFERENCES workflows(workflow_id),
    task_id UUID NOT NULL REFERENCES tasks(task_id),
    depends_on_task_id UUID NOT NULL REFERENCES tasks(task_id),
    dependency_type VARCHAR(32) NOT NULL DEFAULT 'finish_to_start',
    required BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (task_id, depends_on_task_id)
);
```

理由：
- 查询 READY Task 需要 JOIN 依赖并检查状态。
- 查找下游任务需要反向查询。
- 循环依赖验证可在应用层完成。
- JSONB 方案查询依赖时不够直观。

### 8.4 `event_store`

```sql
CREATE TABLE event_store (
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
```

职责：**审计日志 + 事件溯源支持**。当前状态事实来源仍是 `workflows`/`tasks`。`event_store` 可用于故障排查和手动回放，但**回放不应直接触发真实 Agent**。

### 8.5 `outbox_events`

```sql
CREATE TABLE outbox_events (
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

CREATE INDEX idx_outbox_pending ON outbox_events(status, next_retry_at) WHERE status = 'pending';
```

### 8.6 `processed_events`（Inbox 幂等）

```sql
CREATE TABLE processed_events (
    event_id UUID PRIMARY KEY,
    workflow_id UUID NOT NULL,
    task_id UUID NULL,
    event_type VARCHAR(128) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 8.7 `dlq`

```sql
CREATE TABLE dlq (
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

Kafka DLQ Topic 用于队列侧死信，PostgreSQL `dlq` 表用于**审计、人工处理记录、重投状态**。

### 8.8 `execution_checkpoints`

当前项目 **第一版可暂不实现**。因为：
- Task result 已保存在 `tasks.result`。
- Workflow 状态已保存在 `workflows.status`。
- Event 历史已保存在 `event_store`。
- Agent message history 可由 Agent 自行管理。

若未来需要保存 Supervisor 决策中间状态，再引入 `execution_checkpoints`。

### 8.9 `agent_registry`

第一版 **可暂不实现独立表**。当前 Researcher/Writer capability 映射硬编码在 `agent.py:241-243` 和 `scheduler.py` 中。

若未来需要动态注册，设计：

```sql
CREATE TABLE agent_registry (
    agent_id VARCHAR(128) PRIMARY KEY,
    agent_type VARCHAR(64) NOT NULL,
    capabilities JSONB NOT NULL,
    labels JSONB NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'offline',
    last_heartbeat TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

实时在线状态建议用 Redis，长期配置用 PostgreSQL。

---

## 9. 各组件职责

| 组件 | 职责 |
|------|------|
| `workflows` | Workflow 当前状态事实来源 |
| `tasks` | Task 当前状态、结果、错误、重试次数事实来源 |
| `task_dependencies` | Task DAG 依赖关系事实来源 |
| `event_store` | 事件审计日志，支持调试和有限回放 |
| `execution_checkpoints` | 暂不实现；未来保存中间决策状态 |
| `agent_registry` | 暂不实现；未来保存 Agent 长期配置 |
| `dlq` | 死信审计、人工处理、重投记录 |

---

## 10. Repository / StateStore 设计

### 10.1 抽象接口

```python
class WorkflowRepository(Protocol):
    async def save(self, workflow: Workflow) -> None: ...
    async def get(self, workflow_id: str) -> Workflow | None: ...
    async def update_status(self, workflow_id: str, status: WorkflowStatus, *, version: int) -> bool: ...

class TaskRepository(Protocol):
    async def save(self, task: Task) -> None: ...
    async def get(self, task_id: str) -> Task | None: ...
    async def update_status(self, task_id: str, status: TaskStatus, *, result=None, error=None, version: int) -> bool: ...
    async def list_ready_tasks(self, workflow_id: str) -> list[Task]: ...
    async def list_downstream_tasks(self, task_id: str) -> list[Task]: ...

class EventStoreRepository(Protocol):
    async def append(self, event: Event) -> None: ...

class OutboxRepository(Protocol):
    async def enqueue(self, event: Event, topic: str, key: str | None) -> None: ...
    async def poll_pending(self, limit: int) -> list[OutboxRecord]: ...
    async def mark_published(self, outbox_id: int) -> None: ...
    async def mark_failed(self, outbox_id: int, error: str) -> None: ...

class ProcessedEventRepository(Protocol):
    async def is_processed(self, event_id: str) -> bool: ...
    async def mark_processed(self, event_id: str, workflow_id: str, event_type: str) -> None: ...
```

### 10.2 第一版合并策略

第一版可合并为：

- `StateStore`：包含 Workflow、Task、依赖的读写。
- `OutboxStore`：Outbox 读写。
- `EventStore`：事件追加。
- `ProcessedEventStore`：消费幂等。

### 10.3 内存状态迁移

| 当前内存状态 | 迁移目标 |
|--------------|----------|
| `WorkflowCoordinator._workflows` | `WorkflowRepository` + `TaskRepository` |
| `WorkflowCoordinator._completions` | 外部查询/轮询 + 可选 Redis Pub/Sub；不依赖内存 Future |
| `Scheduler._dispatched` | Redis SET NX + PostgreSQL `tasks.status` 最终防线 |

---

## 11. Workflow 恢复设计

### 11.1 启动时恢复

1. 查询 `workflows` 中状态为 `EXECUTING`、`WAITING`、`PLANNING` 的 Workflow。
2. 对每个 Workflow：
   - 加载 `tasks`。
   - 加载 `task_dependencies` 重建 DAG。
   - 忽略 `COMPLETED`/`FAILED`/`CANCELLED`。
3. 对每个非终态 Workflow：
   - 若存在 `READY` 但未 `DISPATCHED` 的任务，发布 `task.ready`。
   - 若存在 `DISPATCHED`/`RUNNING` 的任务，需要超时或心跳机制判断是否需要重新发布。

### 11.2 DISPATCHED/RUNNING 恢复策略

- 为 Task 增加 `started_at` 和 `heartbeat_at`。
- 若 `RUNNING` 超过 `TASK_TIMEOUT` 无心跳，则视为失败，按重试策略处理。
- 若 `DISPATCHED` 超过一定时间未收到 `AGENT_STARTED`，可重新发布 `task.ready`（依赖幂等键防止重复执行）。

### 11.3 并发冲突

- 使用 **乐观锁 `version`** 更新 `workflows` 和 `tasks`。
- 多个 Coordinator 同时更新同一 Workflow 时，version 冲突则放弃当前处理。
- 对关键路径可用 `SELECT FOR UPDATE` 事务保证原子性。

---

## 12. Outbox / Inbox 和幂等设计

### 12.1 Transactional Outbox

流程：

1. Coordinator 更新 `tasks` 状态。
2. 同一事务写入 `outbox_events`。
3. 提交事务。
4. Outbox Publisher 轮询 `outbox_events`。
5. Publisher 发送 Kafka 成功后，标记 `published_at` 和 `status=published`。

### 12.2 Publisher 并发

- 使用 `SELECT ... FROM outbox_events WHERE status='pending' AND next_retry_at <= NOW() ORDER BY id FOR UPDATE SKIP LOCKED LIMIT n`。
- 多个 Publisher 实例可并发，互不阻塞。
- Kafka 发送成功后再标记 published。若 Publisher 在发送成功后、标记前崩溃，下次会重复发送，依赖消费端幂等。

### 12.3 Inbox 幂等

消费端流程：

1. 开始事务。
2. `INSERT INTO processed_events (event_id, ...)`，利用唯一约束检测重复。
3. 若重复，回滚或跳过（offset 仍需提交）。
4. 更新 `tasks`/`workflows`。
5. 写 `outbox_events`。
6. 提交事务。
7. 提交 Kafka offset。

### 12.4 Offset 提交时机

- 业务处理成功后提交 offset。
- 至少一次投递 + 业务幂等 = 效果不重复。

---

## 13. Kafka 重试和 DLQ 设计

### 13.1 重试策略

- `retry_count` 存在 `metadata` 和 `tasks.retry_count` 中。
- 最大重试次数 `MAX_RETRIES`。
- Backoff：指数退避，如 `2^retry_count * BASE_DELAY_MS`。
- 重试事件：Coordinator 收到 `AGENT_FAILED` 后，若 `retryable=True` 且 `retry_count < MAX_RETRIES`，重新发布 `task.ready`，`metadata.retry_count += 1`。

### 13.2 延迟重试

Kafka 不支持原生延迟队列。方案：

- 不单独使用 `events.retry` Topic。
- Coordinator 将重试任务重新发布到 `task.ready`。
- 若需要延迟，可在 `outbox_events.next_retry_at` 中控制 Publisher 发送时间。
- 或使用延迟 Topic 配合时间轮（后续扩展）。

### 13.3 DLQ

- 超过最大重试次数后，发布到 `dlq` Topic。
- 同时写入 PostgreSQL `dlq` 表。
- `original_event_id` 保存原始 event_id。
- 人工重投时，生成新的 `event_id` 并保留 `original_event_id`，消费端通过 `processed_events` 防止重复执行。

---

## 14. Redis 设计

Redis 定位为**性能优化和分布式协调**，不是事实来源。

### 14.1 调度幂等

替换 `Scheduler._dispatched`：

```python
key = f"dispatched:{workflow_id}:{task_id}:{attempt}"
```

- `SET key 1 NX EX <TTL>`。
- `attempt` 取自 `metadata.retry_count`。
- 重试时使用新的 attempt，因此会重新调度。
- COMPLETED 后 Key 自动过期。
- Redis 丢失时，PostgreSQL `tasks.status` 作为最终防线（若 status 已是 RUNNING/COMPLETED，则忽略）。

### 14.2 Workflow 并发推进锁

- 优先使用 PostgreSQL 行锁/乐观锁。
- Redis 分布式锁仅用于高频协调场景（如多个 Coordinator 同时抢占同一 Workflow）。
- 锁需设置 TTL、续期和 owner token，防止误释放。

### 14.3 Agent Registry 和心跳

第一版 **暂不实现**。

若未来实现：

```python
# Redis
key = f"agent:heartbeat:{agent_id}"
value = json.dumps({"capability": "...", "status": "online", "load": 0, "instance_id": "..."})
EX = 30  # TTL
```

心跳间隔 10s，TTL 30s。

### 14.4 缓存

第一版 **暂不实现**。因为：
- PostgreSQL 是事实来源。
- 当前流量不需要缓存。
- 缓存失效增加复杂度。

---

## 15. 外部请求获取最终结果

### 15.1 当前入口

当前入口是 `loop.py` REPL CLI。`Agent.process_turn` 同步等待 Future 返回。

### 15.2 推荐第一版方案

保持 CLI，但内部改为：

1. `process_turn` 启动 Workflow 后**立即返回 `workflow_id`**（异步）。
2. CLI 通过轮询 PostgreSQL `workflows.status` 等待完成。
3. 最大等待时间 `WORKFLOW_TIMEOUT_SECONDS`。
4. 用户断开后 Workflow 继续执行。
5. 最终结果写入 `workflows.final_result`。
6. 通过 `workflow_id` 查询 `workflows` 表获取结果。

### 15.3 为什么不继续用 Future

- `asyncio.Future` 不能跨进程。
- Kafka 模式下 Coordinator 和 CLI 可能在不同进程。
- Future 只能作为同进程内的优化通知机制。

### 15.4 后续扩展

- 增加 HTTP API：`POST /workflows` 返回 `workflow_id`；`GET /workflows/{id}` 查询状态。
- SSE/WebSocket 推送 `workflow.status` 事件。

---

## 16. 目标组件关系图

```
┌─────────────┐     ┌─────────────────┐     ┌──────────────────┐
│   CLI/API   │────▶│  Agent/Supervisor│────▶│  PostgreSQL      │
│ (loop.py)   │◀────│  (agent.py)      │     │  workflows/tasks │
└─────────────┘     └────────┬────────┘     └────────┬─────────┘
                             │                         │
                             ▼                         ▼
                    ┌─────────────────┐      ┌──────────────────┐
                    │  StateStore     │      │  OutboxStore     │
                    │  (Repository)   │      │                  │
                    └────────┬────────┘      └────────┬─────────┘
                             │                         │
                             ▼                         ▼
                    ┌─────────────────┐      ┌──────────────────┐
                    │ WorkflowCoordinator│◀───│ Outbox Publisher │
                    │  (workflow/coordinator)│   └──────────────────┘
                    └────────┬────────┘            │
                             │                     ▼
                             │            ┌──────────────────┐
                             │            │ Kafka /          │
                             │            │ InMemoryEventBus │
                             │            └────────┬─────────┘
                             │                     │
                             ▼                     ▼
                    ┌─────────────────┐   ┌──────────────────┐
                    │ Scheduler       │   │ Agent Consumers  │
                    │  (scheduler.py) │   │ Researcher/Writer│
                    └────────┬────────┘   └────────┬─────────┘
                             │                     │
                             ▼                     ▼
                    ┌─────────────────┐   ┌──────────────────┐
                    │ Redis Idempotency│   │ Agent Handlers   │
                    │ dispatched keys │   │ (handlers.py)    │
                    └─────────────────┘   └────────┬─────────┘
                                                   │
                                                   ▼
                                          ┌──────────────────┐
                                          │ Researcher/Writer│
                                          │ workers.run()    │
                                          └──────────────────┘
```

---

## 17. 关键场景时序图

### 17.1 只使用 Writer

```
CLI -> Agent: process_turn("write poem")
Agent -> PostgreSQL: save Workflow, Task
Agent -> Outbox: task.ready
Outbox Publisher -> Kafka: task.ready
Kafka -> Writer Worker: task.ready
Writer Worker -> Kafka: agent.started
Writer Worker -> Worker.run()
Writer Worker -> Kafka: agent.completed {result}
Kafka -> Coordinator: agent.completed
Coordinator -> PostgreSQL: update Task completed, Workflow completed
Coordinator -> Outbox: workflow.completed
CLI -> PostgreSQL: poll -> final_result
```

### 17.2 Researcher 完成后触发 Writer

```
Coordinator -> Kafka: task.ready (r1, researcher)
Researcher -> Kafka: agent.completed (r1)
Coordinator -> PostgreSQL: r1 completed
Coordinator -> Outbox: task.ready (w1, writer, depends_on r1)
Writer -> Kafka: agent.completed (w1)
Coordinator -> PostgreSQL: w1 completed, workflow completed
```

### 17.3 多个 Researcher 并行

```
Coordinator 发布：
- task.ready (r1, key=r1)
- task.ready (r2, key=r2)
多个 Researcher Worker 竞争消费，并行执行。
```

### 17.4 Agent 失败并重试

```
Writer -> Kafka: agent.failed {retryable=true}
Coordinator -> PostgreSQL: retry_count += 1
Coordinator -> Outbox: task.ready (retry_count=1)
Writer -> Kafka: agent.completed
```

### 17.5 超过重试次数进入 DLQ

```
Coordinator: retry_count >= MAX_RETRIES
Coordinator -> PostgreSQL: Task FAILED, Workflow FAILED
Coordinator -> Kafka: dlq
Coordinator -> PostgreSQL: dlq table
```

### 17.6 程序重启后恢复

```
启动：
- 查询 workflows EXECUTING/WAITING
- 加载 tasks + dependencies
- 重建 TaskGraph
- 对每个 READY 未 DISPATCHED 任务发布 task.ready
- 对 DISPATCHED/RUNNING 超时任务按失败处理
```

### 17.7 Kafka 重复投递但业务不重复执行

```
Kafka -> Coordinator: agent.completed (duplicate)
Coordinator -> PostgreSQL: BEGIN
PostgreSQL: INSERT processed_events -> 唯一约束冲突
Coordinator: 忽略/ROLLBACK
Coordinator -> Kafka: commit offset
```

---

## 18. 文件级修改清单

| 阶段 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 1 | `workflow/state_store.py` | 新增 | StateStore 抽象 + InMemoryStateStore |
| 1 | `workflow/coordinator.py` | 修改 | 注入 StateStore，替换 `_workflows` |
| 1 | `tests/test_state_store.py` | 新增 | StateStore 测试 |
| 2 | `db/models.py` 或 `db/schema.sql` | 新增 | PostgreSQL 表结构 |
| 2 | `db/postgres_state_store.py` | 新增 | PostgreSQLStateStore |
| 2 | `db/migrations/` | 新增 | Alembic/纯 SQL 迁移 |
| 2 | `pyproject.toml` | 修改 | 增加 asyncpg、alembic |
| 3 | `events/outbox.py` | 新增 | Outbox 抽象 |
| 3 | `events/outbox_publisher.py` | 新增 | Outbox Publisher |
| 3 | `events/processed_event_store.py` | 新增 | 消费幂等 |
| 4 | `events/kafka_event_bus.py` | 新增 | KafkaEventBus |
| 4 | `events/event_serde.py` | 新增 | Event JSON 序列化 |
| 5 | `scheduler.py` | 修改 | 接入 Redis 幂等 |
| 5 | `redis_client.py` | 新增 | Redis 连接 |
| 6 | `agent.py` | 修改 | 根据配置选择 EventBus/StateStore |
| 6 | `.env.example` | 修改 | 新增配置项 |
| 7 | `tests/` | 新增 | 集成测试、兼容性测试 |

---

## 19. 分阶段实施计划

> 原则：先抽象、再持久化、再分布式通信、最后优化。

### 阶段一：StateStore 抽象 + InMemoryStateStore

- **目标**：将 `WorkflowCoordinator._workflows` 抽象，保持 InMemory 行为不变。
- **文件**：
  - 新增 `workflow/state_store.py`
  - 修改 `workflow/coordinator.py`
- **新增接口**：`WorkflowStateStore`、`TaskStateStore`。
- **数据表**：无。
- **配置变化**：无。
- **测试**：新增 `tests/test_state_store.py`，现有测试继续通过。
- **验证**：`pytest tests/`
- **风险**：低。
- **回滚**：回退 coordinator.py。
- **独立上线**：是。

### 阶段二：PostgreSQL Workflow/Task 持久化

- **目标**：Workflow、Task、依赖持久化到 PostgreSQL。
- **文件**：
  - 新增 `db/schema.sql` 或 Alembic 迁移
  - 新增 `db/postgres_state_store.py`
  - 修改 `agent.py` 根据配置选择 StateStore
- **数据表**：`workflows`、`tasks`、`task_dependencies`。
- **配置变化**：`DATABASE_URL`、`STATE_STORE_BACKEND=memory|postgres`。
- **测试**：新增 PostgreSQL 容器集成测试。
- **验证**：`pytest tests/test_postgres_state_store.py`
- **风险**：中；需要 PostgreSQL 环境。
- **回滚**：切回 `STATE_STORE_BACKEND=memory`。
- **独立上线**：是。

### 阶段三：Event Store + Checkpoint（可选）

- **目标**：保存事件历史。
- **文件**：`events/event_store.py`、`db/event_store_repository.py`。
- **数据表**：`event_store`。
- **配置变化**：`EVENT_STORE_ENABLED`。
- **风险**：低。
- **回滚**：关闭开关。

### 阶段四：Transactional Outbox

- **目标**：状态更新与 Outbox 同事务。
- **文件**：
  - 新增 `events/outbox.py`
  - 新增 `events/outbox_publisher.py`
  - 新增 `events/processed_event_store.py`
- **数据表**：`outbox_events`、`processed_events`。
- **配置变化**：`OUTBOX_POLL_INTERVAL`。
- **测试**：Outbox 事务性、重试、幂等。
- **风险**：中；涉及事务和并发。
- **回滚**：切回 InMemoryEventBus。

### 阶段五：KafkaEventBus

- **目标**：保留 InMemoryEventBus，新增 KafkaEventBus。
- **文件**：
  - 新增 `events/kafka_event_bus.py`
  - 新增 `events/event_serde.py`
  - 修改 `agent.py` 根据配置选择 EventBus
- **Topic**：`task.ready`、`task.assigned`、`agent.status`、`workflow.status`、`dlq`。
- **配置变化**：`EVENT_BUS_BACKEND=memory|kafka`、`KAFKA_BOOTSTRAP_SERVERS` 等。
- **测试**：Kafka 容器集成测试。
- **风险**：高；需要 Kafka 环境。
- **回滚**：切回 `EVENT_BUS_BACKEND=memory`。
- **独立上线**：是。

### 阶段六：Kafka Retry + DLQ

- **目标**：可配置重试、指数退避、DLQ。
- **文件**：修改 `workflow/coordinator.py`、`events/kafka_event_bus.py`。
- **配置变化**：`MAX_RETRIES`、`DLQ_ENABLED`。
- **风险**：中。

### 阶段七：Redis 调度幂等

- **目标**：替换 `Scheduler._dispatched`。
- **文件**：
  - 新增 `redis_client.py`
  - 修改 `scheduler.py`
- **配置变化**：`REDIS_ENABLED`、`REDIS_URL`。
- **风险**：中；Redis 故障时需降级到 PostgreSQL。

### 阶段八：Redis Agent Registry + 缓存（可选）

- **目标**：Agent 心跳、在线状态、可选缓存。
- **文件**：新增 `agents/registry.py`。
- **配置变化**：`AGENT_REGISTRY_ENABLED`。
- **风险**：低。
- **建议**：当前只有 Researcher/Writer，**暂缓**。

---

## 20. 测试计划

### 20.1 PostgreSQL 测试

- Workflow 保存/读取
- Task 保存/读取
- TaskGraph 重建
- 依赖查询
- Task 状态更新
- 并发更新/乐观锁冲突
- 重启恢复未完成 Workflow
- COMPLETED Workflow 不重复恢复
- DISPATCHED/RUNNING 恢复策略

### 20.2 Event Store / Checkpoint 测试

- Event 写入
- event_id 唯一
- Checkpoint 保存/读取（若实现）
- 回放不调用真实 Agent
- 序列化正确

### 20.3 Outbox 测试

- 状态更新和 Outbox 同一事务
- Kafka 不可用时事件不丢失
- Outbox 重试
- 重复发布幂等
- 多 Publisher 并发
- Publisher 崩溃恢复

### 20.4 Kafka 测试

- task.ready 路由
- Researcher/Writer 消费
- 多实例竞争消费
- workflow_id/task_id 分区
- Consumer 重启/offset 提交
- Handler 失败
- 重试 + DLQ
- 重复 Event 幂等

### 20.5 Redis 测试

- SET NX 防重复
- TTL
- 重试 attempt
- 多 Scheduler 实例
- Redis 不可用降级
- PostgreSQL 最终幂等

### 20.6 兼容性测试

- InMemoryEventBus + InMemoryStateStore
- InMemoryEventBus + PostgreSQLStateStore
- KafkaEventBus + PostgreSQLStateStore
- KafkaEventBus + PostgreSQLStateStore + Redis

---

## 21. 风险和过度设计点

### 21.1 第一阶段必须解决

1. **同步 `worker.run()` 阻塞 Consumer**：当前 `asyncio.to_thread()` 已解决，Kafka 模式下继续。
2. **Agent 内部线程安全**：Researcher/Writer 是无状态同步函数，可并发。
3. **Outbox 与状态一致性**：核心。
4. **消费幂等**：核心。
5. **Workflow 恢复时不重复发布 READY**：通过 `tasks.status` 和幂等键保证。

### 21.2 可以暂时接受

1. 无 Schema Registry（用 JSON）。
2. 无 Agent Registry（硬编码 capability）。
3. 无 Checkpoint 表。
4. CLI 轮询而非 SSE/WebSocket。

### 21.3 后续扩展

1. Avro/Schema Registry。
2. Agent Registry 和动态扩缩容。
3. 延迟重试 Topic。
4. 缓存层。
5. HTTP API + SSE。

### 21.4 过度设计点

- 三个优先级 Topic（当前不需要）。
- 动态 per-agent Topic（运维复杂）。
- 完整 Event Sourcing 回放触发真实 Agent（危险）。
- Redis 作为 Workflow 状态事实来源（违反定位）。

---

## 22. 需要确认后才能实施的问题

1. **是否确认第一版最小范围**：StateStore 抽象 → PostgreSQL → Outbox → Kafka → Redis 幂等，暂不做 Agent Registry、Checkpoint、三优先级 Topic？
2. **数据库驱动选择**：推荐 `asyncpg` + 可选 `sqlalchemy`/`databases`，是否接受？
3. **Kafka 客户端**：推荐 `aiokafka`，是否接受？
4. **迁移工具**：推荐 Alembic 还是纯 SQL 脚本？
5. **CLI 入口改造**：`process_turn` 改为返回 `workflow_id` 后 CLI 轮询，是否接受？
6. **DLQ 实现**：先通过 PostgreSQL `dlq` 表 + 业务重试，Kafka DLQ Topic 后续加入，是否接受？
7. **Checkpoint 表**：第一版不实现，是否接受？
8. **Agent Registry**：第一版不实现，是否接受？
