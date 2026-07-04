# 同步 Subagent 扩展设计

## 目标

在当前 `agent-team-exercise` 骨架基础上，使主 Agent 具备完整的 **Supervisor（监督者）** 能力，形成“规划 → 委派 → 执行 → 汇总 → 回复”的闭环：

1. 用户输入任务。
2. 主 Agent（Supervisor）调用 LLM 分析任务，决定是直接回答还是委派给 Subagent。
3. 如需委派，Supervisor 生成规划：`{"action": "delegate", "tasks": [{"agent": "researcher|writer", "description": "..."}, ...]}`，可选择一个或两个 Subagent。
4. 主 Agent 遍历 `tasks`，通过内置 `task` 工具依次把每个 `description` 交给对应 Subagent。
5. Subagent **调用 LLM 完成子任务**，同步返回结果。
6. 主 Agent（Supervisor）再次调用 LLM，基于 Subagent 返回的结果生成面向用户的最终回复；最终回复中应明确说明使用了哪些 Subagent。
7. 将最终回复返回给用户。

**临时方案**：当前在 `models/__init__.py` 中实现一个基于 `urllib` 的 OpenAI 兼容客户端，通过 `.env` 配置阿里云 DashScope（或其他 OpenAI 兼容服务）。当环境变量未配置时自动回退到 Stub 输出，保证项目始终可运行；后续同事替换 `Model` 模块后，Subagent 与 Supervisor 无需改动即可切换到新实现。

Subagent 以**同步阻塞**方式执行，执行完毕后立即把结果返回给主 Agent。

## 设计决策

- **实现位置**：
  - `agent.py` 负责 Supervisor 的核心流程：规划（Planning）、委派（Delegation）、汇总（Summarization）。
  - `subagents/` 负责 Subagent 执行：接收任务描述，调用 LLM 完成专业任务。
  - `tools/` 负责暴露 `task` 工具，把 Supervisor 的委派指令转发给 `Subagent`。
  - `skills/` 保留为 fallback：当 Supervisor 的规划 JSON 解析失败时，回退到基于关键词的规则路由。
  - `models/` 提供 LLM 调用能力。
- **同步模式**：Subagent 与主 Agent 同进程运行，`task()` 调用直接返回字符串结果，不引入队列、RPC、异步或并发。
- **两个内置 Subagent**：
  - `researcher`：擅长信息收集、分析、总结，适合处理需要背景知识或长上下文的任务。
  - `writer`：擅长文字创作、文档撰写、内容生成，适合处理与写作/文案相关的任务。
- **Supervisor 双阶段 LLM 调用**：
  - **Planning 阶段**：主 Agent 把用户输入、上下文、可用 Subagent 列表等信息拼成 prompt，调用 `Model.complete()`，要求模型输出 JSON 决策。
    - `{"action": "direct", "response": "..."}`：直接回答用户，无需 Subagent。
    - `{"action": "delegate", "tasks": [{"agent": "researcher|writer", "description": "..."}, ...]}`：委派给一个或多个 Subagent。Supervisor 根据任务复杂度自行判断是用 researcher、writer，还是两者都用。
  - **Execution 阶段**：如果 planning 结果是 `delegate`，主 Agent 遍历 `tasks` 数组，依次调用 `Tool.execute("task", {"agent": task["agent"], "description": task["description"]})`，同步收集所有 Subagent 结果。
  - **Summarization 阶段**：拿到一个或多个 Subagent 结果后，主 Agent 再次调用 `Model.complete()`，把原始请求、每个 Subagent 的名称及其结果拼成 prompt，要求模型生成面向用户的最终回复；最终回复中需明确说明本次使用了哪些 Subagent。
- **LLM 调用链路**：
  - `models/__init__.py` 实现 `Model` 类，优先读取 `.env` 中的 `MODEL_BASE_URL`、`MODEL_API_KEY`、`MODEL_NAME`。
  - 当 `MODEL_BASE_URL` 未配置或 `MODEL_API_KEY` 为默认值时，回退到 Stub 行为，输出 `[model-name] <prompt>`。
  - 当配置完整时，使用 Python 标准库 `urllib` 发送 OpenAI 兼容的 `/chat/completions` 请求，无需额外安装依赖。
  - Agent 负责创建并持有唯一的 `Model` 实例。
  - Agent 把 `model` 注入 `Tool`，`Tool` 再把 `model` 注入 `Subagent`。
  - `Subagent` 及其 `Researcher`/`Writer` workers 均持有 `model` 引用。
  - 每个 worker 的 `run(description)` 构造适合自身角色的 prompt，并调用 `self.model.complete(prompt)` 生成结果。
- **工具暴露**：`tools/` 模块新增 `task` 工具，参数为 `{"agent": "researcher|writer", "description": "..."}`；`Tool.execute()` 识别 `task` action 后调用 `Subagent.dispatch()`。
- **Skill Fallback**：当 Supervisor 的 planning JSON 无法解析或缺少必要字段时，主 Agent 调用 `Skill.decide()` 做基于关键词的规则路由，保证系统健壮性。
- **占位兼容**：如果 `subagents/`、`tools/` 或 `models/` 仍未实现，`agent.py` 继续沿用现有内联 Stub，确保项目初始即可运行。

## 项目结构变化

```
.
├── agent.py                     # 主流程：Supervisor 规划/委派/汇总
├── loop.py                      # 保持不变
├── models/
│   └── __init__.py              # 新增：Model 类（OpenAI 兼容客户端，可回退 Stub）
├── skills/
│   └── __init__.py              # 实现：规则路由 fallback
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

- `Researcher` 类：处理分析/总结类任务。`run(description)` 构造研究类 prompt 并调用 `self.model.complete(prompt)`，返回结果前保留 `[Researcher] Completed research:` 前缀。
- `Writer` 类：处理写作/文案类任务。`run(description)` 构造写作类 prompt 并调用 `self.model.complete(prompt)`，返回结果前保留 `[Writer] Completed writing task:` 前缀。
- 两个 worker 都实现 `__init__(self, model=None)` 和 `run(self, description: str) -> str`。
- 当 `model is None` 时，可回退到简单的格式化字符串，保证独立测试时不会崩溃。

### `tools/__init__.py`

- 实现 `Tool` 类。
- `__init__(self, model=None)`：接收 Agent 传入的 `Model` 实例，创建 `Subagent(model)`。
- `execute(self, action, params)`：
  - 当 `action == "task"` 时，调用 `Subagent.dispatch(params["agent"], params["description"])` 并返回结果。
  - 保留对其他工具的扩展能力（如 weather、math）。

### `skills/__init__.py`

- 实现 `Skill` 类，作为 Supervisor planning 失败时的 fallback。
- `decide(user_input, llm_response, context, memory)`：
  - 若输入中出现“复杂”、“分析”、“研究”、“总结”等关键词，返回调用 `researcher` 的 `task` 工具。
  - 若输入中出现“写”、“文章”、“文案”、“创作”等关键词，返回调用 `writer` 的 `task` 工具。
  - 否则返回直接回答。

### `agent.py`

- 在 `Agent.__init__()` 中先创建 `self.model = Model()`，再把 `self.model` 注入 `Tool` 和 `Subagent`：
  - `self.tool = Tool(self.model)`
  - `self.subagent = Subagent(self.model)`（保留组装，虽然当前主流程通过 Tool 间接使用 Subagent）
- 新增 `_plan(self, user_input, context, memory) -> dict`：
  - 构造 Supervisor planning prompt，调用 `self.model.complete()`。
  - 尝试解析返回文本为 JSON，得到 `{"action": "direct", ...}` 或 `{"action": "delegate", "tasks": [...]}`。
  - 解析失败或字段缺失时，调用 `self.skill.decide()` 作为 fallback；若 fallback 决定委派，则转换为单任务数组 `{"tasks": [{...}]}`。
  - 兼容旧版单 agent 格式 `{"action": "delegate", "agent": ..., "description": ...}`，内部自动转换为 tasks 数组。
- 新增 `_summarize(self, user_input, results, context, memory) -> str`：
  - 构造 Supervisor summarization prompt，把原始请求、每个 Subagent 的名称及其结果拼成 prompt，调用 `self.model.complete()` 生成最终回复。
  - `results` 是一个列表，每个元素形如 `{"agent": "...", "result": "..."}`。
  - 在 prompt 中明确要求模型在最终回复开头说明使用了哪些 Subagent，例如："我调用了 researcher 来帮你研究，并调用 writer 来撰写内容。"
  - 为进一步保证可见性，`process_turn()` 会在 Supervisor 汇总结果前拼接一个固定前缀 `[使用了子agent: xxx, yyy]`，确保用户一定能看到。
- 更新 `process_turn()` 流程：
  1. 更新 context（可选）。
  2. 调用 `_plan()` 获取决策。
  3. 若 `action == "direct"`，直接返回 `response`。
  4. 若 `action == "delegate"`，遍历 `tasks`：
     - 对每个 task 调用 `self.tool.execute("task", {"agent": task["agent"], "description": task["description"]})`
     - 收集 `{"agent": task["agent"], "result": ...}` 到 `results` 列表
  5. 调用 `_summarize()` 基于所有 Subagent 结果生成最终回复，并在回复前拼接 `[使用了子agent: xxx, yyy]` 前缀。
  6. 写入 memory（可选）。
  7. 返回最终回复。

## 模块接口约定

| 模块 | 类名 | 核心方法 |
|------|------|----------|
| models | `Model` | `__init__()` / `complete(prompt: str) -> str` |
| subagents | `Subagent` | `__init__(model=None)` / `dispatch(agent_name, task_description) -> str` |
| subagents | `Researcher` | `__init__(model=None)` / `run(description) -> str` |
| subagents | `Writer` | `__init__(model=None)` / `run(description) -> str` |
| tools | `Tool` | `__init__(model=None)` / `execute(action, params) -> str` |
| skills | `Skill` | `decide(user_input, llm_response, context, memory) -> dict` |
| agent | `Agent` | `_plan(...)` / `_summarize(...)` / `process_turn(user_input)` |

## 成功标准

- `models/__init__.py` 可被 `agent.py` 正常导入；未配置环境变量时输出 Stub，配置正确时真实调用 LLM。
- `subagents/` 模块可被 `agent.py` 正常导入，包含两个同步 Subagent。
- Subagent 及其 workers 能调用 `model.complete()` 生成结果，并保留身份前缀。
- 主 Agent 在 REPL 中接收到任务时，先由 Supervisor LLM 规划，再决定直接回答或委派给 Subagent。
- 委派场景下，主 Agent 可依次调用一个或多个 Subagent，收集结果后再次调用 LLM 汇总生成最终回复。
- 配置 `.env` 后，运行 `loop.py` 测试 Subagent 能看到来自阿里云模型的真实回复，且回复中会明确显示使用了哪些 Subagent。
- 项目仍可通过 `uv run loop.py` 或 `python3 loop.py` 直接运行（无配置时回退 Stub）。
- 当子模块未实现时，`agent.py` 的内联 Stub 继续生效，不影响骨架运行。
