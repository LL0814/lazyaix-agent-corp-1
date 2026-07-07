# Agent Team Exercise

一个用于团队合作练习的模块化 Agent 骨架项目。

老师负责初始化入口文件、核心组装逻辑和环境配置；学生分组实现 `models/`、`tools/`、`skills/`、`context/`、`memory/`、`subagents/`、`config/` 七个模块。

## 项目结构

```
.
├── loop.py              # REPL 入口：管理循环并持有 Context / Memory
├── agent.py             # Agent 组装与单次轮次逻辑
├── scheduler.py         # 任务调度器：按 target_capability 路由 TASK_READY
├── pyproject.toml       # uv 项目配置
├── .python-version      # Python 版本锁定
├── .env.example         # 环境变量示例
├── README.md            # 本文件
├── docker-compose.yml   # 本地 PostgreSQL / Kafka / Redis
├── config/              # Config 模块（学生实现）
├── models/              # Model 模块：加载配置，提供 LLM complete()（学生实现）
├── tools/               # Tool 模块：执行外部动作（学生实现）
├── skills/              # Skill 模块：决定直接回答还是调用工具（学生实现）
├── context/             # Context 模块：维护当前上下文（学生实现）
├── memory/              # Memory 模块：存储与检索记忆（学生实现）
├── subagents/           # Subagent 模块：子代理分发（学生实现）
├── events/              # 事件总线、Event Schema、Outbox、Kafka 实现
├── workflow/            # Workflow / Task / TaskGraph / Coordinator
├── db/                  # PostgreSQL Repository、连接池、Schema
└── tests/               # 测试
```

## 快速开始

```bash
# 使用 uv 运行本地内存模式
uv run loop.py

# 运行测试
uv run pytest tests/ -q

# 启动本地 PostgreSQL / Kafka / Redis
uv run docker compose up -d
```

## 单次轮次流程

`Agent.process_turn(user_input)` 的执行流程：

1. **更新 Context**（当 `ENABLE_CONTEXT=true` 时）
2. **构建 Prompt**（根据 `ENABLE_MEMORY` 决定是否拼入历史记忆）
3. **调用 Model.complete(prompt)** 获取原始 LLM 文本
4. **调用 Skill.decide(...)** 进行路由：
   - `action == "direct"：直接返回 LLM 文本
   - `action == "tool"：调用 `Tool.execute(tool, params)`
5. **写入 Memory**（当 `ENABLE_MEMORY=true` 时）
6. 返回结果

## 事件驱动工作流（Event-Driven Workflow）

当 `ENABLE_EVENT_DRIVEN=true` 时，Agent 使用事件驱动编排：

1. Supervisor 根据用户请求生成 `Workflow` 和 `TaskGraph`
2. `WorkflowCoordinator` 将工作流持久化到 `StateStore`
3. 就绪任务以 `TASK_READY` 事件发布到 `EventBus`
4. `Scheduler` 按 `target_capability` 把任务分配给 `ResearcherHandler` 或 `WriterHandler`
5. Agent Handler 执行真实任务并发布 `AGENT_COMPLETED` / `AGENT_FAILED`
6. `WorkflowCoordinator` 更新任务状态并触发下游任务
7. 工作流完成后通过 Future 或轮询返回结果

所有组件均可替换：

| 组件 | 内存模式 | 分布式模式 |
|------|----------|------------|
| Event Bus | `InMemoryEventBus` | `KafkaEventBus` |
| State Store | `InMemoryStateStore` | `PostgresStateStore` |
| Scheduler 幂等 | `InMemoryIdempotencyStore` | `RedisIdempotencyStore` |

## 环境变量

复制 `.env.example` 为 `.env` 并按需修改：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MODEL_API_KEY` | 模型提供商 API Key | `stub-key` |
| `MODEL_NAME` | 模型名称 | `stub-llm` |
| `AGENT_NAME` | REPL 中显示的 Agent 名称 | `Agent` |
| `ENABLE_CONTEXT` | 是否启用上下文更新 | `true` |
| `ENABLE_MEMORY` | 是否启用记忆存储 | `true` |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `ENABLE_EVENT_DRIVEN` | 是否启用事件驱动编排 | `false` |
| `MAX_RETRIES` | 子任务失败最大重试次数 | `2` |
| `WORKFLOW_TIMEOUT_SECONDS` | 工作流完成超时（秒） | `300` |
| `WORKFLOW_WAIT_MODE` | 等待完成方式：`future` 或 `poll` | `future` |
| `WORKFLOW_POLL_INTERVAL_SECONDS` | 轮询间隔（秒） | `0.5` |
| `STATE_STORE_BACKEND` | 状态存储后端：`memory` 或 `postgres` | `memory` |
| `DATABASE_URL` | PostgreSQL 连接 URL | `postgresql://user:pass@localhost:5432/agent_team` |
| `EVENT_BUS_BACKEND` | 事件总线后端：`memory` 或 `kafka` | `memory` |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka 地址 | `localhost:9092` |
| `KAFKA_CLIENT_ID` | Kafka 客户端 ID | `agent-team` |
| `KAFKA_CONSUMER_GROUP` | Kafka 消费组 | `agent-team` |
| `KAFKA_TOPIC_PREFIX` | Kafka Topic 前缀 | `` |
| `REDIS_ENABLED` | 是否启用 Redis | `false` |
| `REDIS_URL` | Redis 连接 URL | `redis://localhost:6379` |
| `SCHEDULER_DISPATCH_TTL_SECONDS` | 调度幂等 TTL（秒） | `3600` |

## 模块接口约定

| 模块 | 类名 | 核心方法 |
|------|------|----------|
| config | `Config` | `get(key, default=None)` |
| models | `Model` | `__init__()` 加载配置；`complete(prompt: str) -> str` |
| tools | `Tool` | `execute(action, params)` |
| skills | `Skill` | `decide(user_input, llm_response, context, memory) -> dict` |
| context | `Context` | `update(input)` / `get()` |
| memory | `Memory` | `store(key, value)` / `retrieve(key)` |
| subagents | `Subagent` | `dispatch(task_description)` |

## 设计要点

- **loop.py** 保持薄：只负责 I/O、持有 `Context` / `Memory`、每轮重新创建 `Agent`。
- **agent.py** 负责动态组装除 `Context` / `Memory` 外的所有模块，并实现单次轮次逻辑。
- **Model** 是纯 LLM 包装器，不处理业务路由。
- **Skill** 是路由层，决定直接回答或调用工具。
- 如果学生模块未实现，`agent.py` / `loop.py` 会回退到内联 Stub，保证项目初始即可运行。
- 事件驱动模式下，业务状态以 PostgreSQL 为事实来源，Kafka 负责跨进程事件传递，Redis 负责调度幂等与分布式协调。
