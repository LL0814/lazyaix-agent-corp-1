# Context 模块四层渐进压缩实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 Context 模块中实现轻量版四层渐进压缩（SnipCompact / MicroCompact / ContextCollapse / AutoCompact），使 Context 在 token 利用率超过阈值时自动或手动触发压缩，同时不影响其他模块接口。

**Architecture:** 在 `context/models.py` 中新增 `full_content`、`CompressionState`、`CompactEvent`；在 `context/state.py` 中实现四层压缩逻辑和触发控制；`Context.update()` 自动检查阈值并按 Snip → Micro → Collapse → Auto 顺序触发；`Context.compact(force=True)` 提供手动触发入口；`Context.get()` 返回的 dict 中新增 `compression` 字段。

**Tech Stack:** Python 3.10+，Pydantic v2，pytest。

## Global Constraints

- 语言：Python 3.10+（项目 `pyproject.toml` 已声明 `requires-python = ">=3.10"`）
- 包管理：`uv`
- 不引入 LangGraph
- 不影响 `Context.update(user_input: str)` 和 `Context.get() -> dict` 接口契约
- `Context.get()` 返回 dict，不强制其他模块引入 Pydantic
- AutoCompact 因当前 Model 是 stub，仅预留接口、记录事件，不调用 LLM
- 四层压缩触发阈值：`SNIP_THRESHOLD=50`，`MICRO_THRESHOLD=65`，`COLLAPSE_THRESHOLD=80`，`AUTO_THRESHOLD=90`
- 每层压缩保护最近 `SAFE_TURNS=3` 条 turn
- Token 估算公式：`ceil(total_chars / 4)`，基于 `full_content`

---

## File Structure

| 文件 | 职责 |
|------|------|
| `context/models.py` | 修改：新增 `TurnSummary.full_content`、`CompressionState`、`CompactEvent`、更新 `ContextState` |
| `context/state.py` | 修改：新增压缩配置、四层压缩逻辑、触发控制、`compact()` 和 `reset_compression_flags()` |
| `tests/test_context.py` | 修改：新增压缩相关单元测试 |
| `context/__init__.py` | 无需修改（已暴露 `Context`） |

---

### Task 1: 更新 Pydantic 数据模型

**Files:**
- Modify: `context/models.py`

**Interfaces:**
- Consumes: 现有 `TurnSummary`、`ContextState`
- Produces:
  - `TurnSummary` 新增 `full_content: str | None = None`
  - 新增 `CompactEvent`
  - 新增 `CompressionState`
  - `ContextState` 新增 `compression: CompressionState`

- [ ] **Step 1: 新增 `CompactEvent` 模型**

  在 `context/models.py` 中，`TopicState` 之后添加：
  ```python
  class CompactEvent(BaseModel):
      """Record of a single compression event."""

      timestamp: datetime
      layer: Literal["snip", "micro", "collapse", "auto"]
      threshold: float
      usage_before: float
      usage_after: float
      turns_removed: int = 0
      notes: str = ""
  ```

- [ ] **Step 2: 新增 `CompressionState` 模型**

  在 `CompactEvent` 之后添加：
  ```python
  class CompressionState(BaseModel):
      """Tracks which compression layers have fired and their history."""

      snip_triggered: bool = False
      micro_triggered: bool = False
      collapse_triggered: bool = False
      auto_triggered: bool = False
      compact_history: list[CompactEvent] = Field(default_factory=list)
  ```

- [ ] **Step 3: 修改 `TurnSummary` 增加 `full_content`**

  更新为：
  ```python
  class TurnSummary(BaseModel):
      """Summary of a single conversation turn."""

      turn_id: int
      role: Literal["user", "assistant", "tool"]
      content_preview: str
      full_content: str | None = None
      tool_calls: list[ToolCallRecord] | None = None
      timestamp: datetime
  ```

- [ ] **Step 4: 修改 `ContextState` 增加 `compression`**

  更新为：
  ```python
  class ContextState(BaseModel):
      """Aggregated conversation context state."""

      recent_turns: list[TurnSummary] = Field(default_factory=list)
      topic: TopicState = Field(default_factory=TopicState)
      token_stats: TokenStats = Field(default_factory=TokenStats)
      compression: CompressionState = Field(default_factory=CompressionState)
      metadata: dict = Field(default_factory=dict)
  ```

- [ ] **Step 5: 验证语法**

  Run:
  ```bash
  uv run python -m py_compile context/models.py
  ```
  Expected: 无输出。

- [ ] **Step 6: Commit**

  Run:
  ```bash
  git add context/models.py
  git commit -m "feat(context): add full_content and compression state models"
  ```

---

### Task 2: 更新 Context 初始化配置

**Files:**
- Modify: `context/state.py`

**Interfaces:**
- Consumes: 现有 `Context.__init__`
- Produces: `Context` 实例新增压缩相关配置属性

- [ ] **Step 1: 在 `__init__` 中读取压缩配置**

  在 `Context.__init__` 中添加：
  ```python
  self.preview_length = int(config.get("PREVIEW_LENGTH", 120))
  self.safe_turns = int(config.get("SAFE_TURNS", 3))
  self.snip_threshold = float(config.get("SNIP_THRESHOLD", 50.0))
  self.micro_threshold = float(config.get("MICRO_THRESHOLD", 65.0))
  self.collapse_threshold = float(config.get("COLLAPSE_THRESHOLD", 80.0))
  self.auto_threshold = float(config.get("AUTO_THRESHOLD", 90.0))
  ```

  并对 `safe_turns` 做校验：如果 `<= 0`，warn 并回退到 3。

- [ ] **Step 2: 定义保护关键词常量**

  在 `Context` 类中定义：
  ```python
  _PROTECTED_KEYWORDS = ("write_file", "edit_file", "edit", "error", "traceback")
  ```

- [ ] **Step 3: 更新 `_make_preview` 辅助方法**

  确保 `update()` 中创建 turn 时使用 `self.preview_length`：
  ```python
  def _make_preview(self, text: str) -> str:
      return text[: self.preview_length]
  ```

- [ ] **Step 4: Commit**

  Run:
  ```bash
  git add context/state.py
  git commit -m "feat(context): add compression configuration to Context"
  ```

---

### Task 3: 更新 Token 估算以使用 full_content

**Files:**
- Modify: `context/state.py`

**Interfaces:**
- Consumes: `TurnSummary.full_content`、`TurnSummary.content_preview`
- Produces: 更准确的 `TokenStats`

- [ ] **Step 1: 修改 `_estimate_tokens` 使用完整原文**

  实现：
  ```python
  def _estimate_tokens(self) -> int:
      """Estimate tokens from full_content, falling back to content_preview."""
      total = 0
      for turn in self._state.recent_turns:
          text = turn.full_content or turn.content_preview or ""
          total += len(text)
          if turn.tool_calls:
              for tc in turn.tool_calls:
                  preview = tc.result_preview or ""
                  total += len(preview)
      from math import ceil
      return max(0, ceil(total / 4))
  ```

- [ ] **Step 2: 修改 `update()` 保存 full_content**

  当创建 user turn 时：
  ```python
  turn = TurnSummary(
      turn_id=self._turn_counter,
      role="user",
      content_preview=self._make_preview(user_input),
      full_content=user_input,
      timestamp=datetime.now(),
  )
  ```

- [ ] **Step 3: 修改 `update_with_result()` 保存完整结果**

  当 result 是 str 时：
  ```python
  turn = TurnSummary(
      turn_id=self._turn_counter,
      role="assistant",
      content_preview=self._make_preview(result),
      full_content=result,
      timestamp=datetime.now(),
  )
  ```

  当 result 是 dict 时：
  ```python
  result_preview = result.get("result_preview") or str(result)[:self.preview_length]
  full_result = result.get("result_preview") or str(result)
  tool_call = ToolCallRecord(
      tool_name=result.get("tool_name", "unknown"),
      params=result.get("params", {}),
      result_preview=result_preview,
  )
  turn = TurnSummary(
      turn_id=self._turn_counter,
      role="tool",
      content_preview=result_preview,
      full_content=full_result,
      tool_calls=[tool_call],
      timestamp=datetime.now(),
  )
  ```

- [ ] **Step 4: 运行现有测试确保无回归**

  Run:
  ```bash
  uv run pytest tests/test_context.py -q
  ```
  Expected: 全部通过。

- [ ] **Step 5: Commit**

  Run:
  ```bash
  git add context/state.py
  git commit -m "feat(context): estimate tokens from full_content and store full text"
  ```

---

### Task 4: 实现 SnipCompact

**Files:**
- Modify: `context/state.py`
- Test: `tests/test_context.py`

**Interfaces:**
- Consumes: `self._state.recent_turns`、`self._state.compression`、`self.token_stats`
- Produces: `_snip_compact() -> bool`

- [ ] **Step 1: 写 SnipCompact 测试**

  在 `tests/test_context.py` 添加：
  ```python
  def test_snip_compact_triggers_at_threshold():
      ctx = Context(config={"CONTEXT_LIMIT": 100})
      # 每条 turn ~25 tokens，4 条 = ~100 tokens，超过 50% 触发 snip
      for i in range(4):
          ctx.update("a" * 100)  # 25 tokens each
      assert ctx._state.compression.snip_triggered
      assert len(ctx._state.recent_turns) <= ctx.safe_turns + 1

  def test_snip_compact_protects_keywords():
      ctx = Context(config={"CONTEXT_LIMIT": 100})
      ctx.update("write_file test.txt hello")  # protected
      for i in range(5):
          ctx.update("a" * 100)
      # The protected turn should still be in recent_turns or compact history
      protected = any("write_file" in (t.full_content or "") for t in ctx._state.recent_turns)
      assert protected
  ```

- [ ] **Step 2: 运行测试确认失败**

  Run:
  ```bash
  uv run pytest tests/test_context.py::test_snip_compact_triggers_at_threshold -v
  ```
  Expected: FAIL。

- [ ] **Step 3: 实现 `_snip_compact` 方法**

  在 `context/state.py` 的 `Context` 类中添加：
  ```python
  def _is_protected(self, turn: TurnSummary) -> bool:
      text = turn.full_content or turn.content_preview or ""
      return any(kw in text for kw in self._PROTECTED_KEYWORDS)

  def _snip_compact(self) -> bool:
      if self._state.compression.snip_triggered:
          return False
      usage = self._state.token_stats.usage_pct
      if usage < self.snip_threshold:
          return False

      removed = 0
      while self._state.token_stats.usage_pct >= self.snip_threshold:
          candidates = [
              i for i, turn in enumerate(self._state.recent_turns[:-self.safe_turns])
              if not self._is_protected(turn)
          ]
          if not candidates:
              break
          idx = candidates[0]
          self._state.recent_turns.pop(idx)
          removed += 1
          self._state.token_stats = self._compute_token_stats()

      if removed > 0:
          self._state.compression.snip_triggered = True
          self._record_compact_event("snip", removed)
          return True
      return False
  ```

  其中 `_record_compact_event`：
  ```python
  def _record_compact_event(self, layer: str, turns_removed: int = 0) -> None:
      from math import ceil
      before = self._state.token_stats.usage_pct
      self._state.token_stats = self._compute_token_stats()
      after = self._state.token_stats.usage_pct
      threshold = getattr(self, f"{layer}_threshold")
      event = CompactEvent(
          timestamp=datetime.now(),
          layer=layer,  # type: ignore[arg-type]
          threshold=threshold,
          usage_before=before,
          usage_after=after,
          turns_removed=turns_removed,
      )
      self._state.compression.compact_history.append(event)
  ```

- [ ] **Step 4: 运行测试确认通过**

  Run:
  ```bash
  uv run pytest tests/test_context.py::test_snip_compact_triggers_at_threshold tests/test_context.py::test_snip_compact_protects_keywords -v
  ```
  Expected: PASS。

- [ ] **Step 5: Commit**

  Run:
  ```bash
  git add context/state.py tests/test_context.py
  git commit -m "feat(context): implement SnipCompact with protected turns"
  ```

---

### Task 5: 实现 MicroCompact

**Files:**
- Modify: `context/state.py`
- Test: `tests/test_context.py`

**Interfaces:**
- Consumes: `self._state.recent_turns`、`self._state.compression`
- Produces: `_micro_compact() -> bool`

- [ ] **Step 1: 写 MicroCompact 测试**

  在 `tests/test_context.py` 添加：
  ```python
  def test_micro_compact_clears_old_tool_full_content():
      ctx = Context(config={"CONTEXT_LIMIT": 100})
      ctx.update("hello")
      ctx.update_with_result({
          "tool_name": "weather",
          "params": {"city": "Beijing"},
          "result_preview": "sunny" + "x" * 200,
      })
      for i in range(5):
          ctx.update("a" * 100)
      tool_turns = [t for t in ctx._state.recent_turns if t.role == "tool"]
      for turn in tool_turns[:-ctx.safe_turns]:
          assert turn.full_content is None or len(turn.full_content) <= ctx.preview_length
  ```

- [ ] **Step 2: 运行测试确认失败**

  Run:
  ```bash
  uv run pytest tests/test_context.py::test_micro_compact_clears_old_tool_full_content -v
  ```
  Expected: FAIL。

- [ ] **Step 3: 实现 `_micro_compact` 方法**

  在 `context/state.py` 中添加：
  ```python
  def _micro_compact(self) -> bool:
      if self._state.compression.micro_triggered:
          return False
      usage = self._state.token_stats.usage_pct
      if usage < self.micro_threshold:
          return False

      cleared = 0
      for turn in self._state.recent_turns[:-self.safe_turns]:
          if turn.role == "tool" and turn.full_content:
              turn.full_content = None
              cleared += 1

      if cleared > 0:
          self._state.compression.micro_triggered = True
          self._record_compact_event("micro", 0)
          return True
      return False
  ```

- [ ] **Step 4: 运行测试确认通过**

  Run:
  ```bash
  uv run pytest tests/test_context.py::test_micro_compact_clears_old_tool_full_content -v
  ```
  Expected: PASS。

- [ ] **Step 5: Commit**

  Run:
  ```bash
  git add context/state.py tests/test_context.py
  git commit -m "feat(context): implement MicroCompact clearing old tool full_content"
  ```

---

### Task 6: 实现 ContextCollapse

**Files:**
- Modify: `context/state.py`
- Test: `tests/test_context.py`

**Interfaces:**
- Consumes: `self._state.recent_turns`、`self._state.compression`、`self._state.topic`
- Produces: `_context_collapse() -> bool`

- [ ] **Step 1: 写 ContextCollapse 测试**

  在 `tests/test_context.py` 添加：
  ```python
  def test_context_collapse_merges_old_turns():
      ctx = Context(config={"CONTEXT_LIMIT": 100})
      for i in range(8):
          ctx.update("a" * 100)
      collapsed = any(t.role == "system" for t in ctx._state.recent_turns)
      assert collapsed
      assert ctx._state.compression.collapse_triggered
  ```

- [ ] **Step 2: 运行测试确认失败**

  Run:
  ```bash
  uv run pytest tests/test_context.py::test_context_collapse_merges_old_turns -v
  ```
  Expected: FAIL。

- [ ] **Step 3: 实现 `_context_collapse` 方法**

  在 `context/state.py` 中添加：
  ```python
  def _context_collapse(self) -> bool:
      if self._state.compression.collapse_triggered:
          return False
      usage = self._state.token_stats.usage_pct
      if usage < self.collapse_threshold:
          return False

      if len(self._state.recent_turns) <= self.safe_turns:
          return False

      old_turns = self._state.recent_turns[:-self.safe_turns]
      kept_turns = self._state.recent_turns[-self.safe_turns:]

      topics = {t.primary_topic for t in [self._state.topic] if t.primary_topic}
      entities = list(self._state.topic.active_entities)[:5]
      summary_text = (
          f"[Summary of turns {old_turns[0].turn_id}-{old_turns[-1].turn_id}] "
          f"Topics: {', '.join(topics) or 'none'}. "
          f"Entities: {', '.join(entities) or 'none'}."
      )
      summary_turn = TurnSummary(
          turn_id=old_turns[-1].turn_id,
          role="system",
          content_preview=self._make_preview(summary_text),
          full_content=summary_text,
          timestamp=datetime.now(),
      )

      self._state.recent_turns = [summary_turn] + kept_turns
      self._state.compression.collapse_triggered = True
      self._record_compact_event("collapse", len(old_turns))
      return True
  ```

- [ ] **Step 4: 运行测试确认通过**

  Run:
  ```bash
  uv run pytest tests/test_context.py::test_context_collapse_merges_old_turns -v
  ```
  Expected: PASS。

- [ ] **Step 5: Commit**

  Run:
  ```bash
  git add context/state.py tests/test_context.py
  git commit -m "feat(context): implement ContextCollapse merging old turns into summary"
  ```

---

### Task 7: 实现 AutoCompact（预留接口）

**Files:**
- Modify: `context/state.py`
- Test: `tests/test_context.py`

**Interfaces:**
- Consumes: `self._state.compression`
- Produces: `_auto_compact() -> bool`

- [ ] **Step 1: 写 AutoCompact 测试**

  在 `tests/test_context.py` 添加：
  ```python
  def test_auto_compact_is_noop_without_llm():
      ctx = Context(config={"CONTEXT_LIMIT": 50})
      for i in range(10):
          ctx.update("a" * 100)
      assert ctx._state.compression.auto_triggered
      auto_events = [e for e in ctx._state.compression.compact_history if e.layer == "auto"]
      assert len(auto_events) == 1
      assert "LLM" in auto_events[0].notes or "not available" in auto_events[0].notes.lower()
  ```

- [ ] **Step 2: 运行测试确认失败**

  Run:
  ```bash
  uv run pytest tests/test_context.py::test_auto_compact_is_noop_without_llm -v
  ```
  Expected: FAIL。

- [ ] **Step 3: 实现 `_auto_compact` 方法**

  在 `context/state.py` 中添加：
  ```python
  def _auto_compact(self) -> bool:
      if self._state.compression.auto_triggered:
          return False
      usage = self._state.token_stats.usage_pct
      if usage < self.auto_threshold:
          return False

      self._state.compression.auto_triggered = True
      before = self._state.token_stats.usage_pct
      self._state.token_stats = self._compute_token_stats()
      after = self._state.token_stats.usage_pct
      event = CompactEvent(
          timestamp=datetime.now(),
          layer="auto",
          threshold=self.auto_threshold,
          usage_before=before,
          usage_after=after,
          notes="LLM compact not available in stub mode",
      )
      self._state.compression.compact_history.append(event)
      return True
  ```

- [ ] **Step 4: 运行测试确认通过**

  Run:
  ```bash
  uv run pytest tests/test_context.py::test_auto_compact_is_noop_without_llm -v
  ```
  Expected: PASS。

- [ ] **Step 5: Commit**

  Run:
  ```bash
  git add context/state.py tests/test_context.py
  git commit -m "feat(context): implement AutoCompact stub recording events without LLM"
  ```

---

### Task 8: 在 `update()` 中集成自动触发

**Files:**
- Modify: `context/state.py`
- Test: `tests/test_context.py`

**Interfaces:**
- Consumes: `_snip_compact`、`_micro_compact`、`_context_collapse`、`_auto_compact`
- Produces: `update()` 自动触发压缩

- [ ] **Step 1: 写自动触发测试**

  在 `tests/test_context.py` 添加：
  ```python
  def test_update_automatically_triggers_compression():
      ctx = Context(config={"CONTEXT_LIMIT": 100})
      for i in range(10):
          ctx.update("a" * 100)
      assert ctx._state.compression.snip_triggered
      assert ctx._state.compression.micro_triggered
      assert ctx._state.token_stats.usage_pct < 90
  ```

- [ ] **Step 2: 运行测试确认失败**

  Run:
  ```bash
  uv run pytest tests/test_context.py::test_update_automatically_triggers_compression -v
  ```
  Expected: FAIL。

- [ ] **Step 3: 在 `update()` 末尾调用压缩**

  在 `Context.update()` 方法最后、返回 `_state` 之前添加：
  ```python
  self._run_compression()
  ```

  实现 `_run_compression`：
  ```python
  def _run_compression(self) -> None:
      self._state.token_stats = self._compute_token_stats()
      self._snip_compact()
      self._state.token_stats = self._compute_token_stats()
      self._micro_compact()
      self._state.token_stats = self._compute_token_stats()
      self._context_collapse()
      self._state.token_stats = self._compute_token_stats()
      self._auto_compact()
      self._state.token_stats = self._compute_token_stats()
  ```

- [ ] **Step 4: 运行测试确认通过**

  Run:
  ```bash
  uv run pytest tests/test_context.py::test_update_automatically_triggers_compression -v
  ```
  Expected: PASS。

- [ ] **Step 5: Commit**

  Run:
  ```bash
  git add context/state.py tests/test_context.py
  git commit -m "feat(context): trigger compression automatically on update"
  ```

---

### Task 9: 实现手动 `compact()` 和 `reset_compression_flags()`

**Files:**
- Modify: `context/state.py`
- Test: `tests/test_context.py`

**Interfaces:**
- Produces:
  - `Context.compact(force: bool = False) -> ContextState`
  - `Context.reset_compression_flags() -> None`

- [ ] **Step 1: 写手动压缩测试**

  在 `tests/test_context.py` 添加：
  ```python
  def test_compact_manual_force():
      ctx = Context(config={"CONTEXT_LIMIT": 100})
      for i in range(4):
          ctx.update("a" * 100)
      ctx.compact(force=True)
      assert ctx._state.compression.snip_triggered

  def test_reset_compression_flags():
      ctx = Context(config={"CONTEXT_LIMIT": 100})
      for i in range(4):
          ctx.update("a" * 100)
      assert ctx._state.compression.snip_triggered
      ctx.reset_compression_flags()
      assert not ctx._state.compression.snip_triggered
  ```

- [ ] **Step 2: 运行测试确认失败**

  Run:
  ```bash
  uv run pytest tests/test_context.py::test_compact_manual_force tests/test_context.py::test_reset_compression_flags -v
  ```
  Expected: FAIL。

- [ ] **Step 3: 实现 `compact()` 和 `reset_compression_flags()`**

  在 `context/state.py` 中添加：
  ```python
  def compact(self, force: bool = False) -> ContextState:
      if force:
          # Temporarily lower thresholds so all available layers run
          original_snip = self.snip_threshold
          original_micro = self.micro_threshold
          original_collapse = self.collapse_threshold
          original_auto = self.auto_threshold
          self.snip_threshold = 0.0
          self.micro_threshold = 0.0
          self.collapse_threshold = 0.0
          self.auto_threshold = 0.0
          try:
              self._run_compression()
          finally:
              self.snip_threshold = original_snip
              self.micro_threshold = original_micro
              self.collapse_threshold = original_collapse
              self.auto_threshold = original_auto
      else:
          self._run_compression()
      return self._state

  def reset_compression_flags(self) -> None:
      self._state.compression.snip_triggered = False
      self._state.compression.micro_triggered = False
      self._state.compression.collapse_triggered = False
      self._state.compression.auto_triggered = False
  ```

- [ ] **Step 4: 运行测试确认通过**

  Run:
  ```bash
  uv run pytest tests/test_context.py::test_compact_manual_force tests/test_context.py::test_reset_compression_flags -v
  ```
  Expected: PASS。

- [ ] **Step 5: Commit**

  Run:
  ```bash
  git add context/state.py tests/test_context.py
  git commit -m "feat(context): add manual compact and reset_compression_flags"
  ```

---

### Task 10: 补充边界测试和事件记录测试

**Files:**
- Modify: `tests/test_context.py`

**Interfaces:**
- Consumes: 所有压缩功能
- Produces: 完整测试覆盖

- [ ] **Step 1: 添加边界测试**

  在 `tests/test_context.py` 添加：
  ```python
  def test_compression_flags_prevent_repeated_trigger():
      ctx = Context(config={"CONTEXT_LIMIT": 100})
      for i in range(4):
          ctx.update("a" * 100)
      snip_events = [e for e in ctx._state.compression.compact_history if e.layer == "snip"]
      assert len(snip_events) == 1

  def test_compact_event_recorded():
      ctx = Context(config={"CONTEXT_LIMIT": 100})
      for i in range(4):
          ctx.update("a" * 100)
      assert len(ctx._state.compression.compact_history) >= 1
      event = ctx._state.compression.compact_history[0]
      assert event.usage_before >= event.usage_after

  def test_no_compression_when_usage_low():
      ctx = Context()
      ctx.update("short")
      assert not ctx._state.compression.snip_triggered
      assert not ctx._state.compression.micro_triggered
  ```

- [ ] **Step 2: 运行全部测试**

  Run:
  ```bash
  uv run pytest tests/test_context.py -q
  ```
  Expected: 全部通过。

- [ ] **Step 3: Commit**

  Run:
  ```bash
  git add tests/test_context.py
  git commit -m "test(context): add compression boundary and event tests"
  ```

---

### Task 11: 验证 REPL 集成

**Files:**
- Test: `loop.py`

**Interfaces:**
- Consumes: `Context` 类
- Produces: 集成验证结果

- [ ] **Step 1: 运行 REPL 单次回合**

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

- [ ] **Step 2: 验证 `get()` 包含 compression 字段**

  Run:
  ```bash
  uv run python -c "
  from context import Context
  c = Context()
  c.update('hello')
  print('compression' in c.get())
  "
  ```
  Expected: `True`

- [ ] **Step 3: 运行完整测试套件**

  Run:
  ```bash
  uv run pytest tests/test_context.py -q
  ```
  Expected: 全部通过。

- [ ] **Step 4: Commit（如无代码变更则跳过）**

  如无代码变更，无需 commit。

---

## Self-Review

### Spec Coverage

| Spec 要求 | 对应任务 |
|-----------|----------|
| `TurnSummary.full_content` | Task 1 |
| `CompressionState` / `CompactEvent` | Task 1 |
| Token 估算使用 full_content | Task 3 |
| SnipCompact | Task 4 |
| MicroCompact | Task 5 |
| ContextCollapse | Task 6 |
| AutoCompact 预留 | Task 7 |
| 自动触发 | Task 8 |
| 手动 `compact()` / `reset_compression_flags()` | Task 9 |
| 配置项 | Task 2 |
| 测试覆盖 | Task 4-10 |
| REPL 集成 | Task 11 |

### Placeholder Scan

- 无 TBD/TODO。
- 所有步骤包含具体代码或命令。
- 无模糊描述。

### Type Consistency

- `Context.compact(force: bool = False) -> ContextState`
- `Context.reset_compression_flags() -> None`
- `_run_compression()` / `_snip_compact()` / `_micro_compact()` / `_context_collapse()` / `_auto_compact()` 均为 `-> bool` 或 `-> None`
- 配置项名称与 spec 一致。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-02-context-compression-implementation-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
