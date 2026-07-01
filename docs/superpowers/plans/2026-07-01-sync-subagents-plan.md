# 同步 Subagent 扩展实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `agent-team-exercise` 骨架中实现两个同步 Subagent（`researcher` 和 `writer`），并通过内置 `task` 工具让主 Agent（Supervisor）按需委派任务、同步等待结果并返回给用户。

**Architecture:**
- `subagents/` 模块暴露 `Subagent` 类，内部维护 `Researcher` 和 `Writer` 两个 worker。
- `Subagent.dispatch(agent_name, task_description)` 以同步方式选择 worker 并返回结果。
- `tools/` 模块注册 `task` 工具，`Tool.execute("task", {"agent": "...", "description": "..."})` 调用 `Subagent.dispatch()`。
- `skills/` 模块通过关键词判断是否需要委派，返回 `{"action": "tool", "tool": "task", "params": {...}}`。
- `agent.py` 的 `process_turn()` 在 `action == "tool"` 时调用 `Tool.execute()`，并把结果返回给用户。
- 所有模块均遵循现有骨架的“真实实现优先、缺失时回退 Stub”的约定。

**Tech Stack:** Python 3（uv 管理），无额外依赖。

---

## File Structure

| File | Responsibility |
|------|----------------|
| `subagents/__init__.py` | 暴露 `Subagent` 类，提供 `dispatch()` / `task()` 入口 |
| `subagents/workers.py` | 实现 `Researcher` 和 `Writer` 两个同步 worker |
| `tools/tool.py` | 实现 `Tool` 类，注册 `task` 工具 |
| `skills/skill.py` | 实现 `Skill` 类，判断何时委派给 Subagent |
| `agent.py` | 调整 `process_turn()`，支持 `task` 工具调用（最小改动） |

---

## Task 1: 实现 Subagent 模块

**Files:**
- Create: `subagents/__init__.py`
- Create: `subagents/workers.py`

- [ ] **Step 1: 创建 `subagents/workers.py`**

  内容要求：
  - 定义 `Researcher` 类，含 `run(self, description: str) -> str`，返回带有 `[Researcher]` 前缀的结果。
  - 定义 `Writer` 类，含 `run(self, description: str) -> str`，返回带有 `[Writer]` 前缀的结果。
  - 当前为最小实现，可直接返回格式化字符串；无需真实 LLM 调用。

  预期代码结构：
  ```python
  class Researcher:
      def run(self, description: str) -> str:
          return f"[Researcher] Completed research: {description}"

  class Writer:
      def run(self, description: str) -> str:
          return f"[Writer] Completed writing task: {description}"
  ```

- [ ] **Step 2: 创建 `subagents/__init__.py`**

  内容要求：
  - 从 `.workers` 导入 `Researcher`、`Writer`。
  - 定义 `Subagent` 类：
    - `__init__()` 初始化 `self.workers = {"researcher": Researcher(), "writer": Writer()}`。
    - `dispatch(agent_name, task_description)` 选择对应 worker 并返回 `run()` 结果；若 `agent_name` 不存在则返回错误提示。
    - `task(name, description)` 作为 `dispatch()` 的别名。

  预期代码结构：
  ```python
  from .workers import Researcher, Writer

  class Subagent:
      def __init__(self):
          self.workers = {
              "researcher": Researcher(),
              "writer": Writer(),
          }

      def dispatch(self, agent_name: str, task_description: str) -> str:
          worker = self.workers.get(agent_name)
          if worker is None:
              return f"[Subagent] Unknown agent: {agent_name}"
          return worker.run(task_description)

      def task(self, name: str, description: str) -> str:
          return self.dispatch(name, description)
  ```

- [ ] **Step 3: 验证 Subagent 模块可独立导入并工作**

  Run:
  ```bash
  python3 -c "from subagents import Subagent; s = Subagent(); print(s.dispatch('researcher', 'analyze AI trends')); print(s.dispatch('writer', 'write a hello world intro'))"
  ```
  Expected:
  ```
  [Researcher] Completed research: analyze AI trends
  [Writer] Completed writing task: write a hello world intro
  ```

---

## Task 2: 实现 Task 工具

**Files:**
- Create: `tools/tool.py`

- [ ] **Step 1: 创建 `tools/tool.py`**

  内容要求：
  - 实现 `Tool` 类。
  - `execute(self, action, params)` 支持：
    - `action == "task"`：调用 `Subagent.dispatch(params["agent"], params["description"])`。
    - 保留简单的 `weather`、`math` 示例工具作为扩展占位。
  - 通过 `from subagents import Subagent` 导入 Subagent；如果导入失败则回退到最小占位行为。

  预期代码结构：
  ```python
  try:
      from subagents import Subagent
  except ImportError:
      class Subagent:
          def dispatch(self, agent_name, task_description):
              return f"[STUB] Subagent handled task: {task_description}"

  class Tool:
      def __init__(self):
          self.subagent = Subagent()

      def execute(self, action, params):
          if action == "task":
              return self.subagent.dispatch(params.get("agent"), params.get("description", ""))
          if action == "weather":
              return f"[Tool] Weather in {params.get('city', 'Unknown')} is sunny."
          if action == "math":
              return f"[Tool] Math result for {params.get('expression', '')}"
          return f"[Tool] Executed {action} with {params}"
  ```

- [ ] **Step 2: 验证 task 工具可调用 Subagent**

  Run:
  ```bash
  python3 -c "from tools.tool import Tool; t = Tool(); print(t.execute('task', {'agent': 'writer', 'description': 'write a blog post intro'}))"
  ```
  Expected:
  ```
  [Writer] Completed writing task: write a blog post intro
  ```

---

## Task 3: 实现 Skill 路由

**Files:**
- Create: `skills/skill.py`

- [ ] **Step 1: 创建 `skills/skill.py`**

  内容要求：
  - 实现 `Skill` 类。
  - `decide(user_input, llm_response, context, memory)`：
    - 若输入包含“研究/分析/总结/复杂/长”等关键词，返回调用 `researcher` 的 `task` 工具。
    - 若输入包含“写/文章/文案/创作/博客”等关键词，返回调用 `writer` 的 `task` 工具。
    - 若输入包含 `weather/天气` 或 `calculate/计算`，返回对应示例工具。
    - 否则直接返回 LLM 原文。

  预期返回格式：
  ```python
  {"action": "tool", "tool": "task", "params": {"agent": "researcher", "description": "..."}}
  ```

- [ ] **Step 2: 验证 Skill 路由决策**

  Run:
  ```bash
  python3 -c "from skills.skill import Skill; s = Skill(); print(s.decide('帮我研究一下 AI 趋势', '', {}, None)); print(s.decide('写一篇文章', '', {}, None))"
  ```
  Expected:
  ```
  {'action': 'tool', 'tool': 'task', 'params': {'agent': 'researcher', 'description': '帮我研究一下 AI 趋势'}}
  {'action': 'tool', 'tool': 'task', 'params': {'agent': 'writer', 'description': '写一篇文章'}}
  ```

---

## Task 4: 调整主 Agent 流程

**Files:**
- Modify: `agent.py`

- [ ] **Step 1: 让 `process_turn()` 支持 task 工具返回**

  当前 `agent.py` 的 `process_turn()` 已支持 `action == "tool"` 时调用 `Tool.execute()`，因此**逻辑上已兼容**。需要确认：
  - `Tool.execute()` 在 `action == "task"` 时能正确调用 `Subagent.dispatch()`。
  - 返回结果直接作为 `result` 存入 Memory 并展示给用户。

  如需最小改动，可保持现有流程不变；如需让 Supervisor 汇总，可让主 Agent 把 Subagent 结果拼入 prompt 再调用一次 `Model.complete()` 进行汇总，但这超出“最简单实现”范围，可选不做。

- [ ] **Step 2: 验证 Agent 能完整走通 Subagent 路径**

  Run:
  ```bash
  printf '帮我研究一下 AI 趋势\nquit\n' | python3 loop.py
  ```
  Expected output contains:
  ```
  Agent is ready. Type 'exit' or 'quit' to stop.
  > [Researcher] Completed research: 帮我研究一下 AI 趋势
  > Goodbye.
  ```

---

## Task 5: 端到端测试

**Files:**
- Test: `loop.py`

- [ ] **Step 1: 运行完整 REPL 验证 researcher 和 writer 两条路径**

  Run:
  ```bash
  printf '帮我研究一下市场趋势\n写一篇文章\nquit\n' | uv run loop.py
  ```
  Expected output contains:
  ```
  [Researcher] Completed research: 帮我研究一下市场趋势
  [Writer] Completed writing task: 写一篇文章
  ```

- [ ] **Step 2: 验证普通输入仍走直接回答路径**

  Run:
  ```bash
  printf '你好\nquit\n' | uv run loop.py
  ```
  Expected output contains 直接回答（当前为 LLM Stub 返回的 echo 文本）。

- [ ] **Step 3: 验证删除/未实现子模块时骨架仍可运行**

  Run（临时重命名测试，完成后恢复）：
  ```bash
  mv skills/skill.py /tmp/skill.py.bak && printf '你好\nquit\n' | uv run loop.py; mv /tmp/skill.py.bak skills/skill.py
  ```
  Expected: 程序正常结束，无崩溃。

---

## Self-Review

**Spec coverage:**
- 两个同步 Subagent 实现：Task 1。
- `task` 工具暴露：Task 2。
- 主 Agent 通过 Skill 判断并委派：Task 3。
- 主 Agent 汇总/返回 Subagent 结果：Task 4。
- 端到端可运行：Task 5。

**Placeholder scan:** 无 TBD/TODO 等未定义占位符。

**Type consistency:** 方法签名与接口约定表一致。
