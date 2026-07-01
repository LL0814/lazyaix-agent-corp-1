# 同步 Subagent 扩展设计

## 目标

在当前 `agent-team-exercise` 骨架基础上，以**最简单的方式**引入两个同步 Subagent，使主 Agent 具备 `Supervisor` 能力：

- 主 Agent 理解用户目标、拆分任务并汇总结果。
- 当任务复杂、需要专业能力或需要更多上下文时，主 Agent 通过内置的 `task` 工具把子任务委派给指定 Subagent。
- Subagent **调用 LLM 完成子任务**。
- **临时方案**：当前在 `models/__init__.py` 中实现一个基于 `urllib` 的 OpenAI 兼容客户端，通过 `.env` 配置阿里云 DashScope（或其他 OpenAI 兼容服务）。当环境变量未配置时自动回退到 Stub 输出，保证项目始终可运行；后续同事替换 `Model` 模块后，Subagent 无需改动即可切换到新实现。
- Subagent 以**同步阻塞**方式执行，执行完毕后立即把结果返回给主 Agent。

## 设计决策

- **实现位置**：所有 Subagent 相关代码集中在 `subagents/` 模块；`tools/`、`skills/`、`models/`、`agent.py` 按需做最小改动，保持与现有骨架风格一致。
- **同步模式**：Subagent 与主 Agent 同进程运行，`task()` 调用直接返回字符串结果，不引入队列、RPC、异步或并发。
- **两个内置 Subagent**：
  - `researcher`：擅长信息收集、分析、总结，适合处理需要背景知识或长上下文的任务。
  - `writer`：擅长文字创作、文档撰写、内容生成，适合处理与写作/文案相关的任务。
- **LLM 调用链路**：
  - `models/__init__.py` 实现 `Model` 类，优先读取 `.env` 中的 `MODEL_BASE_URL`、`MODEL_API_KEY`、`MODEL_NAME`。
  - 当 `MODEL_BASE_URL` 未配置或 `MODEL_API_KEY` 为默认值时，回退到 Stub 行为，输出 `[model-name] <prompt>`。
  - 当配置完整时，使用 Python 标准库 `urllib` 发送 OpenAI 兼容的 `/chat/completions` 请求，无需额外安装依赖。
  - Agent 负责创建并持有唯一的 `Model` 实例。
  - Agent 把 `model` 注入 `Tool`，`Tool` 再把 `model` 注入 `Subagent`。
  - `Subagent` 及其 `Researcher`/`Writer` workers 均持有 `model` 引用。
  - 每个 worker 的 `run(description)` 构造适合自身角色的 prompt，并调用 `self.model.complete(prompt)` 生成结果。
- **工具暴露**：`tools/` 模块新增 `task` 工具，参数为 `{"agent": "researcher|writer", "description": "..."}`；`Tool.execute()` 识别 `task` action 后调用 `Subagent.dispatch()`。
- **路由决策**：`skills/` 模块的 `Skill.decide()` 在判断用户输入需要子任务能力时，返回 `{"action": "tool", "tool": "task", "params": {...}}`。
- **主 Agent 汇总**：当单次输入只需要一次子任务时，主 Agent 直接把 Subagent 结果作为最终回复；更复杂场景由 LLM/SKILL 决定再次拆分，但本次实现只保证“能委派、能返回”。
- **占位兼容**：如果 `subagents/`、`tools/` 或 `models/` 仍未实现，`agent.py` 继续沿用现有内联 Stub，确保项目初始即可运行。

## 项目结构变化

```
.
├── agent.py                     # 主流程：组装 Model 并注入 Tool/Subagent
├── loop.py                      # 保持不变
├── models/
│   └── __init__.py              # 新增：Model 类（OpenAI 兼容客户端，可回退 Stub）
├── skills/
│   └── __init__.py              # 实现：决定何时委派给 Subagent
├── tools/
│   └── __init__.py              # 实现：注册 task 工具
├── subagents/
│   ├── __init__.py              # 实现：暴露 Subagent 类，接收 model 并注入 workers
│   └── workers.py               # 实现：Researcher / Writer，调用 model.complete()
├── context/                     # 可继续使用 Stub 或后续实现
├── memory/                      # 可继续使用 Stub 或后续实现
└── docs/superpowers/specs/
    └── 2026-07-01-sync-subagents-design.md
```

## 模块职责

### `models/__init__.py`

- 实现 `Model` 类。
- `__init__()`：从环境变量读取 `MODEL_BASE_URL`、`MODEL_API_KEY`、`MODEL_NAME`。
- `complete(prompt: str) -> str`：
  - 若未配置真实 endpoint/key，回退到 Stub：`[model-name] <prompt>`。
  - 否则使用 `urllib` 发送 OpenAI 兼容 `/chat/completions` 请求，返回模型生成的文本。
- 不引入第三方依赖，便于后续被同事的正式 Model 模块替换。

### `subagents/__init__.py`

- 暴露 `Subagent` 类。
- `__init__(self, model=None)`：接收 Agent 传入的 `Model` 实例，初始化两个 worker 实例并把 model 注入它们。
- `dispatch(self, agent_name: str, task_description: str) -> str`：根据 `agent_name` 选择 worker 并同步执行任务，返回结果字符串。
- `task(self, name: str, description: str) -> str`：兼容工具调用风格的别名，内部调用 `dispatch(name, description)`。

### `subagents/workers.py`

- `Researcher` 类：处理分析/总结类任务。`run(description)` 构造研究类 prompt 并调用 `self.model.complete(prompt)`。
- `Writer` 类：处理写作/文案类任务。`run(description)` 构造写作类 prompt 并调用 `self.model.complete(prompt)`。
- 两个 worker 都实现 `__init__(self, model=None)` 和 `run(self, description: str) -> str`。
- 当 `model is None` 时，可回退到简单的格式化字符串，保证独立测试时不会崩溃。

### `tools/__init__.py`

- 实现 `Tool` 类。
- `__init__(self, model=None)`：接收 Agent 传入的 `Model` 实例，创建 `Subagent(model)`。
- `execute(self, action, params)`：
  - 当 `action == "task"` 时，调用 `Subagent.dispatch(params["agent"], params["description"])` 并返回结果。
  - 保留对其他工具的扩展能力（如 weather、math）。

### `skills/__init__.py`

- 实现 `Skill` 类。
- `decide(user_input, llm_response, context, memory)`：
  - 若输入中出现“复杂”、“分析”、“研究”、“总结”等关键词，返回调用 `researcher` 的 `task` 工具。
  - 若输入中出现“写”、“文章”、“文案”、“创作”等关键词，返回调用 `writer` 的 `task` 工具。
  - 否则返回直接回答。

### `agent.py`

- 在 `Agent.__init__()` 中先创建 `self.model = Model()`，再把 `self.model` 注入 `Tool` 和 `Subagent`：
  - `self.tool = Tool(self.model)`
  - `self.subagent = Subagent(self.model)`（保留组装，虽然当前主流程通过 Tool 间接使用 Subagent）
- 在 `process_turn()` 中，当 `decision.action == "tool"` 且 `decision.tool == "task"` 时，通过 `self.tool.execute()` 触发 Subagent。
- 将 Subagent 返回结果作为本轮结果（或交给 LLM 汇总后返回，取决于最简单实现策略）。

## 模块接口约定

| 模块 | 类名 | 核心方法 |
|------|------|----------|
| models | `Model` | `__init__()` / `complete(prompt: str) -> str` |
| subagents | `Subagent` | `__init__(model=None)` / `dispatch(agent_name, task_description) -> str` |
| subagents | `Researcher` | `__init__(model=None)` / `run(description) -> str` |
| subagents | `Writer` | `__init__(model=None)` / `run(description) -> str` |
| tools | `Tool` | `__init__(model=None)` / `execute(action, params) -> str` |
| skills | `Skill` | `decide(user_input, llm_response, context, memory) -> dict` |

## 成功标准

- `models/__init__.py` 可被 `agent.py` 正常导入；未配置环境变量时输出 Stub，配置正确时真实调用 LLM。
- `subagents/` 模块可被 `agent.py` 正常导入，包含两个同步 Subagent。
- Subagent 及其 workers 能调用 `model.complete()` 生成结果。
- 主 Agent 在 REPL 中接收到带有特定关键词的输入时，能调用 `task` 工具并把任务交给对应 Subagent。
- Subagent 同步执行任务并返回结果，主 Agent 将结果展示给用户。
- 配置 `.env` 后，运行 `loop.py` 测试 Subagent 能看到来自阿里云模型的真实回复。
- 项目仍可通过 `uv run loop.py` 或 `python3 loop.py` 直接运行（无配置时回退 Stub）。
- 当子模块未实现时，`agent.py` 的内联 Stub 继续生效，不影响骨架运行。
