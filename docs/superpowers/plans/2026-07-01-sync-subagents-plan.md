# 同步 Subagent 扩展实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `agent-team-exercise` 骨架中实现两个同步 Subagent（`researcher` 和 `writer`），并通过内置 `task` 工具让主 Agent（Supervisor）按需委派任务、同步等待结果并返回给用户。本次迭代要求 **Subagent 调用 LLM 完成子任务**；为便于临时测试，在 `models/__init__.py` 中实现一个基于 `urllib` 的 OpenAI 兼容客户端，通过 `.env` 配置阿里云 DashScope（或其他兼容服务），未配置时自动回退 Stub。

**Architecture:**
- `models/__init__.py` 实现 `Model` 类：读取 `MODEL_BASE_URL`、`MODEL_API_KEY`、`MODEL_NAME`，配置完整时调用真实 LLM，否则回退 Stub。
- `subagents/` 模块暴露 `Subagent` 类，内部维护 `Researcher` 和 `Writer` 两个 worker。
- Agent 在 `__init__()` 中创建唯一的 `Model` 实例，并将其注入 `Tool` 与 `Subagent`。
- `Subagent` 及其 workers 均持有 `model` 引用；worker 的 `run(description)` 构造角色化 prompt 后调用 `self.model.complete(prompt)`。
- `tools/` 模块注册 `task` 工具，`Tool.execute("task", {"agent": "...", "description": "..."})` 调用 `Subagent.dispatch()`。
- `skills/` 模块通过关键词判断是否需要委派，返回 `{"action": "tool", "tool": "task", "params": {...}}`。
- `agent.py` 的 `process_turn()` 在 `action == "tool"` 时调用 `Tool.execute()`，并把结果返回给用户。
- 所有模块均遵循现有骨架的“真实实现优先、缺失时回退 Stub”的约定。

**Tech Stack:** Python 3（uv 管理），仅使用标准库 `urllib`，无额外依赖。

---

## File Structure

| File | Responsibility |
|------|----------------|
| `models/__init__.py` | 实现 `Model` 类：OpenAI 兼容客户端，可回退 Stub |
| `subagents/__init__.py` | 暴露 `Subagent` 类，接收 model 并提供 `dispatch()` / `task()` 入口 |
| `subagents/workers.py` | 实现 `Researcher` 和 `Writer`，调用 `model.complete()` 生成结果 |
| `tools/__init__.py` | 实现 `Tool` 类，接收 model 并注册 `task` 工具 |
| `skills/__init__.py` | 实现 `Skill` 类，判断何时委派给 Subagent |
| `agent.py` | 调整组装顺序：先创建 Model，再将其注入 Tool 和 Subagent |
| `.env.example` | 增加 `MODEL_BASE_URL`、`MODEL_API_KEY`、`MODEL_NAME` 示例 |

---

## Task 0: 实现临时 Model 模块（OpenAI 兼容客户端）

**Files:**
- Create: `models/__init__.py`
- Modify: `.env.example`

- [ ] **Step 1: 创建 `models/__init__.py`**

  内容要求：
  - 实现 `Model` 类。
  - `__init__()` 从环境变量读取 `MODEL_BASE_URL`、`MODEL_API_KEY`、`MODEL_NAME`。
  - `complete(prompt: str) -> str`：
    - 若 `MODEL_BASE_URL` 为空或 `MODEL_API_KEY` 为默认值，返回 `[MODEL_NAME] <prompt>`（Stub 行为）。
    - 否则使用 `urllib.request` 发送 POST 请求到 `<MODEL_BASE_URL>/chat/completions`。
    - 请求体使用 OpenAI 兼容格式：`{"model": ..., "messages": [{"role": "user", "content": prompt}]}`。
    - 解析响应并返回 `choices[0].message.content`。
    - 出错时返回可读错误信息，不要抛异常导致程序崩溃。
  - 不引入 `openai`、`requests` 等第三方库。

  预期代码结构：
  ```python
  import json
  import os
  from urllib import error, request


  class Model:
      """Minimal OpenAI-compatible LLM client using only stdlib urllib."""

      def __init__(self):
          self.api_key = os.environ.get("MODEL_API_KEY", "stub-key")
          self.base_url = os.environ.get("MODEL_BASE_URL", "").rstrip("/")
          self.model_name = os.environ.get("MODEL_NAME", "stub-llm")

      def complete(self, prompt: str) -> str:
          """Call the LLM and return raw text output.

          Falls back to a stub echo when no real endpoint is configured.
          """
          if not self.base_url or self.api_key == "stub-key":
              return f"[{self.model_name}] {prompt}"

          url = f"{self.base_url}/chat/completions"
          headers = {
              "Content-Type": "application/json",
              "Authorization": f"Bearer {self.api_key}",
          }
          data = {
              "model": self.model_name,
              "messages": [{"role": "user", "content": prompt}],
          }

          req = request.Request(
              url,
              data=json.dumps(data).encode("utf-8"),
              headers=headers,
              method="POST",
          )
          try:
              with request.urlopen(req, timeout=60) as resp:
                  result = json.loads(resp.read().decode("utf-8"))
                  return result["choices"][0]["message"]["content"]
          except error.HTTPError as exc:
              return f"[Model HTTP {exc.code}] {exc.read().decode('utf-8', errors='replace')}"
          except Exception as exc:  # pragma: no cover - defensive
              return f"[Model Error] {exc}"
  ```

- [ ] **Step 2: 更新 `.env.example`**

  在原有环境变量基础上，增加：
  ```bash
  # OpenAI-compatible LLM endpoint (e.g. Aliyun DashScope)
  # MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
  # MODEL_API_KEY=your_api_key_here
  # MODEL_NAME=qwen-turbo
  ```

- [ ] **Step 3: 验证 Model 模块未配置时回退 Stub**

  Run:
  ```bash
  python3 -c "from models import Model; m = Model(); print(m.complete('hello'))"
  ```
  Expected:
  ```
  [stub-llm] hello
  ```

---

## Task 1: 让 Subagent workers 调用 LLM

**Files:**
- Modify: `subagents/workers.py`
- Modify: `subagents/__init__.py`

- [ ] **Step 1: 修改 `subagents/workers.py`**

  内容要求：
  - `Researcher` 和 `Writer` 均增加 `__init__(self, model=None)`，保存 model 引用。
  - `run(self, description: str) -> str` 中：
    - 若 `self.model` 为 None，回退到格式化字符串，保证独立测试不崩溃。
    - 否则构造角色化 prompt 并调用 `self.model.complete(prompt)` 返回结果。

  预期代码结构：
  ```python
  class Researcher:
      def __init__(self, model=None):
          self.model = model

      def run(self, description: str) -> str:
          if self.model is None:
              return f"[Researcher] Completed research: {description}"
          prompt = f"You are a research assistant. Please research and summarize the following topic concisely:\n\n{description}"
          return self.model.complete(prompt)

  class Writer:
      def __init__(self, model=None):
          self.model = model

      def run(self, description: str) -> str:
          if self.model is None:
              return f"[Writer] Completed writing task: {description}"
          prompt = f"You are a writing assistant. Please write content based on the following request:\n\n{description}"
          return self.model.complete(prompt)
  ```

- [ ] **Step 2: 修改 `subagents/__init__.py`**

  内容要求：
  - `Subagent.__init__(self, model=None)` 接收 model，并把它传给两个 worker。
  - 保持 `dispatch()` / `task()` 接口不变。

  预期代码结构：
  ```python
  from .workers import Researcher, Writer

  class Subagent:
      def __init__(self, model=None):
          self.model = model
          self.workers = {
              "researcher": Researcher(model),
              "writer": Writer(model),
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
  Expected（当前无 model，走回退分支）：
  ```
  [Researcher] Completed research: analyze AI trends
  [Writer] Completed writing task: write a hello world intro
  ```

---

## Task 2: 让 Task 工具持有 Model 并传给 Subagent

**Files:**
- Modify: `tools/__init__.py`

- [ ] **Step 1: 修改 `tools/__init__.py`**

  内容要求：
  - `Tool.__init__(self, model=None)` 接收 model，并用它创建 `Subagent(model)`。
  - 对 `subagents` 导入失败做 Stub 回退时，Stub Subagent 也应兼容 `dispatch(agent_name, task_description)`。

  预期代码结构：
  ```python
  try:
      from subagents import Subagent
  except ImportError:
      class Subagent:
          def __init__(self, model=None):
              self.model = model

          def dispatch(self, agent_name: str, task_description: str) -> str:
              return f"[STUB] Subagent handled task: {task_description}"

  class Tool:
      def __init__(self, model=None):
          self.subagent = Subagent(model)

      def execute(self, action, params):
          if action == "task":
              return self.subagent.dispatch(params.get("agent"), params.get("description", ""))
          if action == "weather":
              return f"[Tool] Weather in {params.get('city', 'Unknown')} is sunny."
          if action == "math":
              return f"[Tool] Math result for {params.get('expression', '')}"
          return f"[Tool] Executed {action} with {params}"
  ```

- [ ] **Step 2: 验证 task 工具可调用 Subagent（无 model 时走回退）**

  Run:
  ```bash
  python3 -c "from tools import Tool; t = Tool(); print(t.execute('task', {'agent': 'writer', 'description': 'write a blog post intro'}))"
  ```
  Expected：
  ```
  [Writer] Completed writing task: write a blog post intro
  ```

---

## Task 3: 确认 Skill 路由（无需改动）

**Files:**
- Read: `skills/__init__.py`

- [ ] **Step 1: 确认 Skill 仍按关键词返回 task 工具决策**

  当前 `skills/__init__.py` 已实现：
  - “研究/分析/总结/复杂/长/...” → `researcher`
  - “写/文章/文案/创作/博客/...” → `writer`

  若 keywords 需要调整可在此步修改，否则直接验收。

- [ ] **Step 2: 验证 Skill 路由决策**

  Run:
  ```bash
  python3 -c "from skills import Skill; s = Skill(); print(s.decide('帮我研究一下 AI 趋势', '', {}, None)); print(s.decide('写一篇文章', '', {}, None))"
  ```
  Expected：
  ```
  {'action': 'tool', 'tool': 'task', 'params': {'agent': 'researcher', 'description': '帮我研究一下 AI 趋势'}}
  {'action': 'tool', 'tool': 'task', 'params': {'agent': 'writer', 'description': '写一篇文章'}}
  ```

---

## Task 4: 调整 agent.py，将 Model 注入 Tool 和 Subagent

**Files:**
- Modify: `agent.py`

- [ ] **Step 1: 修改 `Agent.__init__()` 的组装顺序**

  当前代码：
  ```python
  self.config = Config()
  self.model = Model()
  self.skill = Skill()
  self.tool = Tool()
  self.subagent = Subagent()
  ```

  改为：
  ```python
  self.config = Config()
  self.model = Model()
  self.skill = Skill()
  self.tool = Tool(self.model)
  self.subagent = Subagent(self.model)
  ```

  同时更新 `agent.py` 中内联的 `Tool` Stub 和 `Subagent` Stub，使它们兼容可选的 `model` 参数：
  - `Tool` Stub：`def __init__(self, model=None):`
  - `Subagent` Stub：`def __init__(self, model=None):` 和 `def dispatch(self, agent_name, task_description):`

- [ ] **Step 2: 验证 Agent 能完整走通 Subagent 路径（未配置 LLM 时）**

  Run:
  ```bash
  printf '帮我研究一下 AI 趋势\nquit\n' | python3 loop.py
  ```
  Expected output contains：
  ```
  Agent is ready. Type 'exit' or 'quit' to stop.
  > [stub-llm] You are a research assistant. Please research and summarize ...
  > Goodbye.
  ```

---

## Task 5: 端到端测试

**Files:**
- Test: `loop.py`
- Test: `.env`（用户自行配置真实 key 后）

- [ ] **Step 1: 未配置 .env 时，验证 researcher 和 writer 两条路径均调用 Stub LLM**

  Run:
  ```bash
  printf '帮我研究一下市场趋势\n写一篇文章\nquit\n' | uv run loop.py
  ```
  Expected output contains：
  ```
  [stub-llm] You are a research assistant. Please research and summarize ...
  [stub-llm] You are a writing assistant. Please write content based on ...
  ```

- [ ] **Step 2: 配置 .env 后，验证 Subagent 调用真实 LLM**

  用户操作：
  ```bash
  cp .env.example .env
  # 编辑 .env，填写 MODEL_BASE_URL、MODEL_API_KEY、MODEL_NAME
  ```

  Run:
  ```bash
  printf '帮我研究一下市场趋势\n写一篇文章\nquit\n' | uv run loop.py
  ```
  Expected: 输出为阿里云模型的真实生成内容（不再是 `[stub-llm]` 前缀）。

- [ ] **Step 3: 验证普通输入仍走直接回答路径**

  Run:
  ```bash
  printf '你好\nquit\n' | uv run loop.py
  ```
  Expected output contains 直接回答（当前为 LLM Stub 返回的 echo 文本）。

- [ ] **Step 4: 验证删除/未实现子模块时骨架仍可运行**

  Run（临时重命名测试，完成后恢复）：
  ```bash
  mv skills/__init__.py /tmp/skills_init.py.bak && printf '你好\nquit\n' | uv run loop.py; mv /tmp/skills_init.py.bak skills/__init__.py
  ```
  Expected: 程序正常结束，无崩溃。

---

## Self-Review

**Spec coverage:**
- 临时 Model 模块实现：Task 0。
- 两个同步 Subagent 实现并调用 LLM：Task 1。
- `task` 工具暴露并传递 model：Task 2。
- 主 Agent 通过 Skill 判断并委派：Task 3。
- 主 Agent 将 Model 注入 Tool/Subagent：Task 4。
- 端到端可运行，支持真实/Stub 两种模式：Task 5。

**Placeholder scan:** 无 TBD/TODO 等未定义占位符。

**Type consistency:** 方法签名与接口约定表一致。
