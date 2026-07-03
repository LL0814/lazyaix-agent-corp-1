# Kafka 多智能体协作 Event Bus 设计文档

## 1. 背景与目标

### 1.1 背景

构建一个面向 1000 万用户生产环境的多智能体（Multi-Agent）协作调度中心。系统以 Kafka 作为事件总线，支持一个主管 Agent（Supervisor）和无数个 Sub Agent 的协作模式，所有 Agent 执行链路需要完整持久化并支持时间回溯。

### 1.2 目标

- **高可用**：调度器多实例运行，单点故障自动切换。
- **高扩展**：Sub Agent 可无限水平扩展，按能力标签动态发现。
- **可追踪**：基于 Event Sourcing 持久化所有事件，支持按 trace_id / aggregate_id / 时间范围回溯。
- **可干预**：支持 Checkpoint 断点续作和人工介入。
- **安全**：Sub Agent 运行在沙箱中，无网络权限，外部访问由 Supervisor 代理。
- **可观测**：集成 Langfuse 业务链路可视化 + OpenTelemetry 技术链路追踪 + Prometheus 监控。

## 2. 需求总结

| 维度 | 决策 |
|------|------|
| 开发语言 | Python |
| 项目目录 | `event-bus-agent/` |
| Kafka 环境 | Docker Compose（Kafka + ZooKeeper + Redis + PostgreSQL + MinIO） |
| 架构模式 | 中心化调度器 + Supervisor-Agent + Sub-Agent |
| 调度策略 | 优先级队列 + FIFO，按能力标签匹配 Agent |
| Agent 注册 | 通过 Kafka `agent.registry` topic 发送心跳与能力声明 |
| 辅助存储 | Redis（分布式锁、运行时状态、幂等、缓存） |
| 持久化 | PostgreSQL（Event Store、Execution State、Checkpoint、DLQ） |
| 顺序性 | 同一 `aggregate_id` 内有序（Kafka partition key） |
| 失败处理 | 指数退避重试 + DLQ + 人工介入 |
| 事件格式 | JSON Schema |
| 记忆系统 | mem0 云平台 + Redis 缓存 + pgvector 本地降级 |
| 可观测性 | REST 管理 API + Prometheus + 结构化日志 + Langfuse + OpenTelemetry |
| 数据保留 | 热数据 30 天，温数据 90 天，之后归档对象存储 |

## 3. 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                          外部系统 / 用户                            │
└──────────────────┬────────────────────────────────┬─────────────────┘
                   │ REST / gRPC                    │ Kafka Producer
                   ▼                                ▼
        ┌─────────────────────┐          ┌─────────────────────┐
        │   REST API Service  │          │   events.ingress    │
        │  (查询 / 管理 / DLQ) │          │   (Kafka Topic)     │
        └─────────────────────┘          └──────────┬──────────┘
                                                    │
        ┌───────────────────────────────────────────┼──────────────┐
        │                                           │              │
        ▼                                           ▼              │
┌─────────────────────┐                  ┌─────────────────────┐   │
│ Event Store Writer  │                  │     Scheduler       │   │
│  (写入 PostgreSQL)   │                  │  (多实例 + Redis锁)  │   │
└─────────────────────┘                  └──────────┬──────────┘   │
        ▲                                           │              │
        │                                           ▼              │
        │                              ┌─────────────────────┐     │
        │                              │  events.agent.{id}  │     │
        │                              │   (Agent 任务队列)   │     │
        │                              └──────────┬──────────┘     │
        │                                         │                │
        │         ┌───────────────────────────────┼────────────────┘
        │         │                               │
        │         ▼                               ▼
        │  ┌─────────────────────┐      ┌─────────────────────┐
        │  │    Supervisor       │      │    Sub Agent        │
        │  │   (主管 Agent)       │      │   (沙箱 / 无网络)    │
        │  │  - 任务拆解          │      │  - 纯本地计算        │
        │  │  - 工具网关          │      │  - 请求工具          │
        │  │  - 结果聚合          │      │  - 上报状态          │
        │  └─────────────────────┘      └─────────────────────┘
        │         │                               │
        │         └───────────────┬───────────────┘
        │                         ▼
        │              ┌─────────────────────┐
        │              │     agent_core      │
        │              │  - context          │
        │              │  - memory           │
        │              │  - tools / skills   │
        │              │  - llm / prompts    │
        │              │  - security         │
        │              └─────────────────────┘
        │                         │
        │                         ▼
        │              ┌─────────────────────┐
        │              │   events.status     │
        │              │   events.retry      │
        │              │   events.dlq        │
        │              │   events.memory.add │
        │              └─────────────────────┘
        │                         │
        └─────────────────────────┘
                                  ▼
                   ┌─────────────────────────────┐
                   │         PostgreSQL          │
                   │  - event_store (事件溯源)    │
                   │  - execution_state (状态机)  │
                   │  - checkpoints (检查点)      │
                   │  - agent_registry           │
                   │  - dlq                      │
                   └─────────────────────────────┘

辅助组件：
- Redis：分布式锁、agent 状态、幂等、负载缓存、记忆缓存
- MinIO/S3：30/90 天后的事件归档
- Langfuse：Agent 业务链路可视化
- OpenTelemetry + Jaeger/Tempo：技术链路追踪
- Prometheus + Grafana：监控告警
```

## 4. 核心组件

### 4.1 Scheduler（调度器）

多实例运行，负责从 Kafka 消费事件并按策略分配给 Agent。

职责：
- 消费 `events.ingress` 和重试 topic
- 通过 Redis 锁竞选 Kafka partition ownership
- 按优先级分层 topic 顺序处理
- 根据 Agent 能力标签和负载选择目标 Agent
- 写入 `events.agent.{agent_id}`
- 更新 execution_state 和 checkpoint

### 4.2 Agent SDK

Agent 接入框架，提供：
- Agent 基类（心跳、注册、消费、状态上报）
- Supervisor 抽象
- Sub Agent 抽象
- Tool Client（Sub Agent 向 Supervisor 请求工具）
- Checkpoint Client

### 4.3 agent_core

Agent 运行时基础设施：
- `context.py`：执行上下文管理
- `memory/`：记忆管理（短期、长期、mem0 适配）
- `tools/`：工具注册表、执行器、schema、沙箱
- `skills/`：Skill 注册、加载、基类
- `llm/`：LLM 调用抽象
- `prompts/`：Prompt 模板管理
- `security/`：权限与沙箱策略

### 4.4 Event Store Writer

监听 Kafka 事件并写入 PostgreSQL，是事件溯源的核心。

### 4.5 Memory Sync Worker

异步消费 `events.memory.add`，调用 mem0 API，并写入本地 pgvector 作为降级备份。

### 4.6 Archiver Service

把超过保留周期的事件从 PostgreSQL 归档到 MinIO/S3。

### 4.7 REST API Service

提供管理接口：
- 查询事件历史
- 查询任务状态
- 查询 Agent 列表
- Checkpoint 人工审批
- DLQ 管理（重试、忽略、标记已处理）
- 事件回放

## 5. Kafka Topic 设计

| Topic | 用途 | 分区策略 |
|-------|------|----------|
| `events.ingress.high` | 高优先级入站事件 | `aggregate_id` |
| `events.ingress.normal` | 普通优先级入站事件 | `aggregate_id` |
| `events.ingress.low` | 低优先级入站事件 | `aggregate_id` |
| `events.assigned` | 已分配事件日志 | `aggregate_id` |
| `events.agent.{agent_id}` | Agent 专属任务队列 | 按 `agent_id` 一个 topic，多实例时该 topic 可多分区竞争消费 |
| `events.status` | Agent 处理状态上报 | `aggregate_id` |
| `events.retry` | 重试事件 | `aggregate_id` |
| `events.dlq` | 死信事件 | `aggregate_id` |
| `events.memory.add` | 记忆写入事件 | `user_id` |
| `agent.registry` | Agent 注册、心跳、能力声明 | `agent_id` |
| `agent.commands` | 对 Agent 的管理命令 | `agent_id` |

## 6. 数据模型

### 6.1 Event Schema

```json
{
  "event_id": "evt_xxx",
  "trace_id": "trace_xxx",
  "parent_event_id": "evt_yyy",
  "aggregate_id": "user_42",
  "event_type": "travel.itinerary.request",
  "priority": "high",
  "timestamp": "2026-07-01T10:00:00Z",
  "source": "api_gateway",
  "target_agent": null,
  "payload": {},
  "metadata": {
    "retry_count": 0,
    "checkpoint_id": null
  }
}
```

### 6.2 PostgreSQL 表

```sql
-- 事件溯源主表
CREATE TABLE event_store (
    id UUID PRIMARY KEY,
    event_id VARCHAR(64) UNIQUE NOT NULL,
    trace_id VARCHAR(64) NOT NULL,
    parent_event_id VARCHAR(64),
    aggregate_id VARCHAR(64) NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    priority VARCHAR(16) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    source VARCHAR(128),
    target_agent VARCHAR(128),
    payload JSONB NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 执行状态机
CREATE TABLE execution_state (
    execution_id UUID PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    aggregate_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL, -- created / assigned / processing / completed / failed / manual_review
    current_agent_id VARCHAR(128),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_info JSONB,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Checkpoint 表
CREATE TABLE execution_checkpoints (
    id UUID PRIMARY KEY,
    execution_id UUID NOT NULL,
    checkpoint_id VARCHAR(128) NOT NULL,
    step_type VARCHAR(32), -- supervisor / sub_agent / manual
    status VARCHAR(32) NOT NULL, -- pending / completed / failed / manual_review
    input_payload JSONB,
    output_payload JSONB,
    error_info JSONB,
    created_at TIMESTAMP,
    completed_at TIMESTAMP,
    UNIQUE(execution_id, checkpoint_id)
);

-- Agent 注册表
CREATE TABLE agent_registry (
    agent_id VARCHAR(128) PRIMARY KEY,
    agent_type VARCHAR(64) NOT NULL,
    capabilities JSONB NOT NULL,
    labels JSONB,
    status VARCHAR(32) NOT NULL, -- online / offline / busy
    last_heartbeat TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 死信队列
CREATE TABLE dlq (
    id UUID PRIMARY KEY,
    event_id VARCHAR(64) NOT NULL,
    trace_id VARCHAR(64) NOT NULL,
    reason VARCHAR(256) NOT NULL,
    error_info JSONB,
    payload JSONB NOT NULL,
    status VARCHAR(32) DEFAULT 'pending', -- pending / retried / ignored
    created_at TIMESTAMP DEFAULT NOW()
);
```

## 7. 数据流

以「制定 3 天北京旅游攻略」为例：

1. 用户请求生成事件，写入 `events.ingress.high`
2. Event Store Writer 持久化到 `event_store`
3. Scheduler 消费事件，匹配 `travel-agent-01`（Supervisor）
4. Supervisor 上报 `started`，生成 Langfuse trace
5. Supervisor 拆解子任务：weather、attraction、restaurant、hotel
6. 每个子任务作为新事件进入 `events.ingress.high`
7. Scheduler 分配给对应 Sub Agent
8. Sub Agent 执行到需要网络时，发送 `tool.request` 给 Supervisor
9. Supervisor 调用外部 API，返回结果，写入 checkpoint
10. Sub Agent 完成，上报 `completed`
11. Supervisor 聚合结果，生成攻略，上报 `completed`
12. 所有状态变更写入 PostgreSQL

## 8. 调度策略

### 8.1 优先级分层

使用多个 ingress topic 实现优先级：
- Scheduler 优先消费 `events.ingress.high`
- 当 high topic 为空时，消费 normal
- 最后消费 low

### 8.2 Agent 选择

1. 根据事件要求的 `capabilities` 筛选可用 Agent
2. 在候选 Agent 中按负载最低选择
3. 支持 Circuit Breaker，失败率过高的 Agent 被临时剔除

### 8.3 顺序性

同一 `aggregate_id` 的事件使用相同 partition key，保证 Kafka 分区内顺序。

## 9. Agent 注册与发现

Agent 启动后向 `agent.registry` 发送注册消息：

```json
{
  "agent_id": "travel-agent-01",
  "agent_type": "supervisor",
  "capabilities": ["itinerary_planner"],
  "labels": {"team": "travel"},
  "event_type": "agent.register"
}
```

每 10 秒发送心跳：

```json
{
  "agent_id": "travel-agent-01",
  "event_type": "agent.heartbeat",
  "load": 3,
  "status": "online"
}
```

Scheduler 通过 Redis 和 PostgreSQL 维护 Agent 状态，心跳丢失 30 秒标记为 offline。

## 10. Checkpoint 机制

### 10.1 触发方式

- **自动 checkpoint**：每个 sub task 完成后自动生成
- **显式 checkpoint**：Supervisor 在关键业务节点主动调用

### 10.2 状态

- `pending`：检查点待完成
- `completed`：已完成
- `failed`：失败
- `manual_review`：需要人工介入

### 10.3 断点重试

失败时 Scheduler 查询 `execution_checkpoints`，找到最后一个 `completed` checkpoint，从 `output_payload` 恢复上下文，重新调度失败步骤。

### 10.4 人工介入

REST API 提供：
- `GET /checkpoints/pending`：列出待人工确认的检查点
- `POST /checkpoints/{id}/approve`：通过并继续
- `POST /checkpoints/{id}/reject`：拒绝并终止
- `POST /checkpoints/{id}/modify`：修改 output_payload 后继续

## 11. 权限与安全模型

| 角色 | 权限 |
|------|------|
| Supervisor Agent | 可访问网络、外部 API、工具、数据库、文件系统 |
| Sub Agent | 仅沙箱内本地计算，无网络权限 |
| Tool 调用 | Sub Agent 通过 event bus 请求 Supervisor 执行 |

工具调用流程：

```
Sub Agent -> tool.request event -> Scheduler -> Supervisor
Supervisor -> 执行工具 -> 返回 tool.response -> Sub Agent
```

`agent_core.security` 实现：
- RBAC：基于角色的工具权限
- ABAC：基于数据敏感度二次授权
- 沙箱策略：进程级资源限制

## 12. 记忆系统

### 12.1 架构

- **mem0 Cloud**：长期语义记忆权威来源
- **Redis**：本地热缓存
- **PostgreSQL pgvector**：降级备份
- **Kafka `events.memory.add`**：异步写入

### 12.2 召回流程

1. 读取 short_term（当前 execution 上下文）
2. 查询 Redis 缓存
3. 缓存未命中则调用 mem0 API
4. mem0 失败则降级到 pgvector
5. 合并短期和长期记忆返回

### 12.3 写入流程

1. Agent 声明需要记忆化的事件
2. 写入 `events.memory.add`
3. Memory Sync Worker 异步调用 mem0 API
4. 同时写入本地 pgvector 作为备份

### 12.4 降级策略

| 场景 | 行为 |
|------|------|
| mem0 正常 | 召回走 mem0，写入异步同步 |
| mem0 延迟高 | 走 Redis 缓存 + 本地 pgvector |
| mem0 不可用 | 完全切换到本地 pgvector |

## 13. 异常处理

### 13.1 异常分级

- **可重试**：网络超时、依赖服务 503、Kafka 临时不可用
- **不可重试**：参数非法、业务规则冲突、权限不足
- **需人工介入**：数据不一致、需要审批

### 13.2 处理策略

| 异常类型 | 策略 |
|----------|------|
| 可重试 | 指数退避写入 `events.retry` |
| 不可重试 | 直接进入 `events.dlq` |
| 重试超限 | 进入 `events.dlq` 并标记 `manual_review` |

### 13.3 Circuit Breaker

- 记录每个 Agent 的失败率
- 超过阈值进入 `open` 状态，停止分配
- 一段时间后进入 `half-open` 试探恢复

### 13.4 超时与 SLA

- 每个任务带 `timeout_ms` 或 `deadline`
- 超时未完成的 `started` 任务自动重调度
- 不同优先级设置不同 SLA

### 13.5 隔离舱

- 每类 Agent 独立 consumer group 或独立 topic
- 某类 Sub Agent 卡死不影响其他 Agent

## 14. 可观测性

### 14.1 Langfuse

- Agent 业务链路：trace → span → observation
- 记录 LLM 调用、工具调用、耗时、token 成本

### 14.2 OpenTelemetry

- Scheduler、Agent SDK、REST API 接入 OTel
- 追踪 Kafka 消费、DB 写入、Redis 操作
- 通过 Jaeger/Tempo 查看技术链路

### 14.3 Prometheus 指标

- `events_ingress_total`
- `events_assigned_total`
- `events_completed_total`
- `events_failed_total`
- `retry_events_total`
- `dlq_events_total`
- `agent_online_count`
- `scheduler_partition_owned`
- `scheduler_latency_seconds`
- `mem0_api_latency_seconds`
- `mem0_fallback_total`

### 14.4 日志

- 结构化 JSON 日志
- 每个日志带 `trace_id`、`execution_id`、`agent_id`
- 错误日志自动上报 Sentry

## 15. 模块划分

```
event-bus-agent/
├── docker-compose.yml
├── pyproject.toml
├── README.md
├── src/
│   └── event_bus_agent/
│       ├── config.py
│       ├── models/
│       │   ├── events.py
│       │   ├── agents.py
│       │   └── checkpoints.py
│       ├── bus/
│       │   ├── producer.py
│       │   ├── consumer.py
│       │   ├── admin.py
│       │   └── topics.py
│       ├── core/
│       │   ├── scheduler.py
│       │   ├── dispatcher.py
│       │   ├── priority.py
│       │   ├── circuit_breaker.py
│       │   └── retry.py
│       ├── runtime/
│       │   ├── redis_client.py
│       │   ├── lock_manager.py
│       │   ├── agent_state.py
│       │   └── idempotency.py
│       ├── store/
│       │   ├── event_store.py
│       │   ├── execution_store.py
│       │   ├── agent_store.py
│       │   ├── dlq_store.py
│       │   └── archiver.py
│       ├── agent_sdk/
│       │   ├── base_agent.py
│       │   ├── supervisor.py
│       │   ├── sub_agent.py
│       │   ├── tool_client.py
│       │   └── checkpoint.py
│       ├── agent_core/
│       │   ├── context.py
│       │   ├── memory/
│       │   │   ├── short_term.py
│       │   │   ├── long_term.py
│       │   │   ├── cache.py
│       │   │   └── adapters/
│       │   │       ├── mem0_cloud_adapter.py
│       │   │       └── pgvector_adapter.py
│       │   ├── tools/
│       │   ├── skills/
│       │   ├── llm/
│       │   ├── prompts/
│       │   └── security/
│       ├── services/
│       │   ├── scheduler_service.py
│       │   ├── event_store_writer.py
│       │   ├── memory_sync_worker.py
│       │   ├── archiver_service.py
│       │   └── api_service.py
│       ├── api/
│       │   ├── main.py
│       │   ├── dependencies.py
│       │   └── routers/
│       │       ├── events.py
│       │       ├── agents.py
│       │       ├── checkpoints.py
│       │       ├── dlq.py
│       │       └── replays.py
│       ├── observability/
│       │   ├── tracing.py
│       │   ├── langfuse_tracer.py
│       │   ├── metrics.py
│       │   └── logging.py
│       └── cli.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── docs/
```

## 16. 部署架构

### 16.1 本地开发

使用 Docker Compose 一键启动：
- Kafka + ZooKeeper
- Redis
- PostgreSQL（启用 pgvector）
- MinIO

### 16.2 生产部署

- Scheduler：3+ 实例
- Event Store Writer：2+ 实例
- API Service：2+ 实例
- Memory Sync Worker：2+ 实例
- Archiver：1 实例
- Agent：业务方独立部署，通过 Kafka 接入

## 17. 缺陷与优化方向

### 17.1 已知缺陷

1. **Scheduler 瓶颈**：所有事件经过 Scheduler，极高 QPS 下可能受限。
2. **Redis 锁可靠性**：Redis 锁基于 TTL，故障时可能等待 TTL 过期。
3. **PostgreSQL 写入压力**：所有事件写 PG，量大时可能瓶颈。
4. **状态一致性**：Kafka offset、PG 写入、Redis 状态三者难保证原子性。
5. **Supervisor 单点**：某类 Supervisor 可能成为瓶颈。
6. **子任务延迟**：每次子任务往返都经过 Kafka + Scheduler。
7. **复杂 Workflow**：纯代码编排难以维护。

### 17.2 优化方向

1. 按事件类型拆分多个 Scheduler Consumer Group
2. 用 ETCD 替代 Redis 做分布式锁
3. PostgreSQL 批量写入、分区表、读写分离
4. 引入工作流 DSL 或 Temporal/Cadence
5. 同 Supervisor 内子任务允许进程内调用
6. Supervisor 多实例按 aggregate_id 分片

## 18. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| Kafka 集群故障 | 多副本、跨可用区部署、监控告警 |
| Redis 故障 | 降级为仅依赖 Kafka rebalance，Scheduler 仍可工作 |
| PostgreSQL 故障 | 读写分离、连接池、降级为只读模式 |
| mem0 Cloud 不可用 | Redis 缓存 + 本地 pgvector 降级 |
| Agent 大规模故障 | Circuit Breaker + DLQ + 人工介入 |
| 数据隐私泄露 | 敏感字段脱敏、用户级记忆开关、审计日志 |
