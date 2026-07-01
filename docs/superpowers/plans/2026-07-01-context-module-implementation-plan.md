# Context 模块实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `agent-team-exercise` 项目中实现一个 Pydantic 类型化的实用对话版 Context 模块，使其能被 `loop.py` 自动导入并替换内联 Stub，支持最近 N 轮摘要、活跃主题/意图推断和 Token 利用率估算。

**Architecture:** 将 Context 模块拆分为 `models.py`（纯 Pydantic 数据模型）和 `state.py`（状态管理逻辑），通过 `__init__.py` 暴露 `Context` 类。`Context` 维护 `ContextState`，对外保持 `update(input) / get()` 契约；`loop.py` 的导入机制会自动使用真实实现替换 Stub。Token 估算采用字符启发式，主题推断采用关键词规则。

**Tech Stack:** Python 3.10+，Pydantic v2，pytest。

## Global Constraints

- 语言：Python 3.10+（项目 `pyproject.toml` 已声明 `requires-python = ">=3.10"`）
- 包管理：`uv`
- 必须保持 `Context.update(user_input: str)` 和 `Context.get() -> dict` 接口契约
- `Context.get()` 返回 dict，不强制其他模块引入 Pydantic
- `CONTEXT_LIMIT` 默认 4000，`MAX_RECENT_TURNS` 默认 5
- Token 估算公式：`ceil(total_chars / 4)`
- 主题推断：零依赖关键词匹配，不引入 LLM
- 本期不触发压缩、不做持久化

---

## File Structure

| 文件 | 职责 |
|------|------|
| `context/models.py` | Pydantic 数据模型：`ContextState`、`TurnSummary`、`TopicState`、`TokenStats`、`ToolCallRecord` |
| `context/state.py` | `Context` 类实现：状态管理、更新、主题推断、Token 估算 |
| `context/__init__.py` | 暴露 `Context` 类 |
| `pyproject.toml` | 添加 `pydantic` 依赖 |
| `tests/test_context.py` | Context 模块单元测试 |

---

### Task 1: 添加 Pydantic 依赖

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: 无
- Produces: `pyproject.toml` 的 `dependencies` 包含 `pydantic>=2.0`

- [ ] **Step 1: 修改 `pyproject.toml` 添加依赖**

  将：
  ```toml
  dependencies = []
  ```
  改为：
  ```toml
  dependencies = ["pydantic>=2.0"]
  ```

- [ ] **Step 2: 同步 uv 环境**

  Run:
  ```bash
  uv sync
  ```
  Expected: `uv.lock` 更新，无报错。

- [ ] **Step 3: Commit**

  Run:
  ```bash
  git add pyproject.toml uv.lock
  git commit -m "deps: add pydantic for Context module"
  ```

---

### Task 2: 实现 Pydantic 数据模型

**Files:**
- Create: `context/models.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `ToolCallRecord`
  - `TurnSummary`
  - `TopicState`
  - `TokenStats`
  - `ContextState`

- [ ] **Step 1: 创建 `context/models.py`**

  写入以下内容：
  ```python
  """Pydantic data models for the Context module."""

  from datetime import datetime
  from typing import Literal

  from pydantic import BaseModel, Field


  class ToolCallRecord(BaseModel):
      """A lightweight record of a tool call and its result."""

      tool_name: str
      params: dict
      result_preview: str | None = None


  class TurnSummary(BaseModel):
      """Summary of a single conversation turn."""

      turn_id: int
      role: Literal["user", "assistant", "tool"]
      content_preview: str
      tool_calls: list[ToolCallRecord] | None = None
      timestamp: datetime


  class TopicState(BaseModel):
      """Current active topic and intent."""

      primary_topic: str | None = None
      intent: str | None = None
      active_entities: list[str] = Field(default_factory=list)
      last_updated_turn: int = 0


  class TokenStats(BaseModel):
      """Estimated token usage and pressure level."""

      estimated_tokens: int = 0
      context_limit: int = 4000
      usage_pct: float = 0.0
      warning_level: Literal["ok", "high", "critical"] = "ok"


  class ContextState(BaseModel):
      """Aggregated conversation context state."""

      recent_turns: list[TurnSummary] = Field(default_factory=list)
      topic: TopicState = Field(default_factory=TopicState)
      token_stats: TokenStats = Field(default_factory=TokenStats)
      metadata: dict = Field(default_factory=dict)
  ```

- [ ] **Step 2: 验证语法**

  Run:
  ```bash
  uv run python -m py_compile context/models.py
  ```
  Expected: 无输出（成功）。

- [ ] **Step 3: Commit**

  Run:
  ```bash
  git add context/models.py
  git commit -m "feat(context): add Pydantic data models"
  ```

---

### Task 3: 实现 Context 类

**Files:**
- Create: `context/state.py`
- Modify: `context/__init__.py`（如果已存在则修改，否则创建）

**Interfaces:**
- Consumes: `context.models` 中所有模型
- Produces:
  - `class Context`：
    - `__init__(self, config: dict | None = None)`
    - `update(self, user_input: str) -> ContextState`
    - `update_with_result(self, result: dict | str) -> ContextState`
    - `get(self) -> dict`
    - `reset(self) -> None`
    - `snapshot(self) -> ContextState`

- [ ] **Step 1: 创建 `context/state.py`**

  实现要求：

  - `__init__`：
    - 接收可选 `config` dict。
    - `context_limit = int(config.get("CONTEXT_LIMIT", 4000))`，非法时回退 4000 并 warning。
    - `max_recent_turns = int(config.get("MAX_RECENT_TURNS", 5))`，非法时回退 5 并 warning。
    - 初始化 `_state = ContextState()`，`_turn_counter = 0`。

  - `_estimate_tokens(text: str) -> int`：
    - 计算所有 recent_turns 的 content_preview 字符总数（包含 tool_calls 的 result_preview）。
    - 返回 `ceil(total_chars / 4)`。

  - `_compute_token_stats() -> TokenStats`：
    - 调用 `_estimate_tokens`。
    - 计算 `usage_pct`。
    - 根据 usage_pct 返回 `warning_level`。

  - `_infer_topic(user_input: str, turn_id: int) -> TopicState`：
    - 根据关键词返回新的 `TopicState`。
    - 关键词规则：
      - `"weather"` / `"天气"` → `primary_topic="weather"`, `intent="query"`
      - `"calculate"` / `"计算"` → `primary_topic="math"`, `intent="compute"`
      - `"write"` / `"写文件"` / `"edit"` → `primary_topic="file_edit"`, `intent="request"`
    - 无匹配时保留当前 topic（或返回空 `TopicState`）。
    - 用正则提取 `"..."` 或 `'...'` 内的字符串作为 `active_entities`。

  - `update(user_input: str) -> ContextState`：
    - `_turn_counter += 1`。
    - 创建 `TurnSummary(turn_id=_turn_counter, role="user", content_preview=user_input[:120], timestamp=datetime.now())`。
    - 追加到 `_state.recent_turns`，保留最近 `max_recent_turns` 条。
    - 更新 `_state.topic = _infer_topic(...)`。
    - 更新 `_state.token_stats = _compute_token_stats()`。
    - 返回 `_state`。

  - `update_with_result(result: dict | str) -> ContextState`：
    - `_turn_counter += 1`。
    - 如果 `result` 是 dict，创建 `role="tool"` 的 turn，包含 `ToolCallRecord`。
    - 如果 `result` 是 str，创建 `role="assistant"` 的 turn。
    - 追加并裁剪，重新计算 token stats。
    - 返回 `_state`。

  - `get() -> dict`：
    - 返回 `_state.model_dump(mode="json")`。

  - `reset() -> None`：
    - 重置 `_state = ContextState()`，`_turn_counter = 0`。

  - `snapshot() -> ContextState`：
    - 返回 `_state.model_copy(deep=True)`。

- [ ] **Step 2: 创建/更新 `context/__init__.py`**

  写入：
  ```python
  """Context module for the agent team exercise."""

  from context.state import Context

  __all__ = ["Context"]
  ```

- [ ] **Step 3: 验证语法和导入**

  Run:
  ```bash
  uv run python -c "from context import Context; c = Context(); print(c.get())"
  ```
  Expected: 输出包含 `recent_turns`、`topic`、`token_stats` 的字典，无报错。

- [ ] **Step 4: Commit**

  Run:
  ```bash
  git add context/state.py context/__init__.py
  git commit -m "feat(context): implement Context class with topic inference and token estimation"
  ```

---

### Task 4: 编写单元测试

**Files:**
- Create: `tests/test_context.py`

**Interfaces:**
- Consumes: `Context` 类
- Produces: 通过 pytest 运行的测试文件

- [ ] **Step 1: 创建 `tests/test_context.py`**

  必须覆盖：

  1. `test_update_appends_user_turn`：
     - 创建 `Context()`，调用 `update("hello")`。
     - 断言 `recent_turns` 长度为 1，`role == "user"`，`content_preview == "hello"`，`turn_id == 1`。

  2. `test_update_truncates_old_turns`：
     - 创建 `Context(config={"MAX_RECENT_TURNS": 2})`。
     - 连续 update 3 次。
     - 断言 `recent_turns` 长度为 2，第一条的 `turn_id == 2`，最后一条的 `turn_id == 3`。

  3. `test_topic_inference_weather`：
     - `update("北京天气怎么样")`。
     - 断言 `topic.primary_topic == "weather"`，`topic.intent == "query"`。

  4. `test_topic_inference_math`：
     - `update("calculate 1 + 1")`。
     - 断言 `topic.primary_topic == "math"`，`topic.intent == "compute"`。

  5. `test_topic_inference_file_edit`：
     - `update("写文件 'test.txt' 内容为 hello")`。
     - 断言 `topic.primary_topic == "file_edit"`，`"test.txt" in topic.active_entities`。

  6. `test_token_estimation_and_warning_level`：
     - 创建 `Context(config={"CONTEXT_LIMIT": 100})`。
     - update 一段超过 200 字符的输入。
     - 断言 `token_stats.usage_pct >= 50` 且 `warning_level in ("high", "critical")`。

  7. `test_get_returns_dict`：
     - 调用 `get()`。
     - 断言返回类型为 `dict`，且包含 `recent_turns`、`topic`、`token_stats` 键。

  8. `test_reset_clears_state`：
     - update 后调用 `reset()`。
     - 断言 `recent_turns` 为空，`turn_id` 计数归零。

  9. `test_update_with_result_dict`：
     - 先 update 用户输入，再 `update_with_result({"tool_name": "weather", "params": {"city": "Beijing"}, "result_preview": "sunny"})`。
     - 断言最近一条 `role == "tool"`，且包含 tool record。

  10. `test_update_with_result_str`：
      - `update_with_result("The weather is sunny.")`。
      - 断言最近一条 `role == "assistant"`。

- [ ] **Step 2: 运行测试**

  Run:
  ```bash
  uv run pytest tests/test_context.py -v
  ```
  Expected: 10 tests passed。

- [ ] **Step 3: Commit**

  Run:
  ```bash
  git add tests/test_context.py
  git commit -m "test(context): add unit tests for Context module"
  ```

---

### Task 5: 验证与 loop.py 集成

**Files:**
- Test: `loop.py`
- Test: `agent.py`

**Interfaces:**
- Consumes: `Context` 类
- Produces: 通过 REPL 运行的集成验证

- [ ] **Step 1: 运行单次 REPL 回合**

  Run:
  ```bash
  printf 'hello\nquit\n' | uv run loop.py
  ```
  Expected output 包含：
  ```
  Agent is ready. Type 'exit' or 'quit' to stop.
  > [stub-llm] hello
  > Goodbye.
  ```

- [ ] **Step 2: 验证 Context 被真实导入**

  Run:
  ```bash
  uv run python -c "from context import Context; print(Context.__module__)"
  ```
  Expected: `context.state`

- [ ] **Step 3: 验证 Skill 能读取 Context**

  临时修改 `skills/__init__.py` 或 `skills.py`（如果已存在）中的 `Skill.decide`：
  - 读取 `context.get()["topic"]["primary_topic"]`。
  - 如果 topic 为 `"weather"`，返回特殊响应以验证通路。

  或者运行：
  ```bash
  uv run python -c "
  from context import Context
  from agent import Agent
  from memory import Memory
  c = Context()
  c.update('北京天气怎么样')
  m = Memory()
  a = Agent(c, m)
  print(a.context.get()['topic'])
  "
  ```
  Expected: `{'primary_topic': 'weather', 'intent': 'query', ...}`

- [ ] **Step 4: Commit（如做了临时修改则还原后 commit）**

  如无代码变更，跳过 commit。如有变更：
  ```bash
  git add agent.py loop.py
  git commit -m "chore(context): verify Context integration with agent loop"
  ```

---

## Self-Review

### Spec Coverage

| Spec 要求 | 对应任务 |
|-----------|----------|
| Pydantic 数据模型 | Task 2 |
| Context 类接口 | Task 3 |
| 最近 N 轮摘要 | Task 3 (`MAX_RECENT_TURNS`) |
| 活跃主题/意图推断 | Task 3 (`_infer_topic`) |
| Token 利用率估算 | Task 3 (`_compute_token_stats`) |
| 与 loop.py / agent.py 集成 | Task 5 |
| 错误处理与边界情况 | Task 3 + Task 4 边界测试 |
| 依赖 pydantic | Task 1 |

### Placeholder Scan

- 无 TBD/TODO。
- 所有步骤包含具体代码或命令。
- 无模糊描述如“适当处理错误”。

### Type Consistency

- `Context.update(user_input: str) -> ContextState`
- `Context.get() -> dict`
- `Context.update_with_result(result: dict | str) -> ContextState`
- 模型字段与 spec 完全一致。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-01-context-module-implementation-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
