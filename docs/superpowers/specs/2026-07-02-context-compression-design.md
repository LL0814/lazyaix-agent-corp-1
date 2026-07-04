# Context 模块轻量版四层渐进压缩设计

> **日期**：2026-07-02  
> **项目**：agent-team-exercise 模块化 Agent 团队练习  
> **主题**：Context 模块轻量版四层渐进压缩  
> **依赖设计**：`docs/superpowers/specs/2026-07-01-context-module-design.md`

---

## 1. 目标

在当前团队练习项目的 `Context` 模块中，实现一个**轻量版四层渐进压缩机制**。该机制与生产级 AgentContext 执行计划中的压缩策略语义对齐，但针对当前无 LangGraph、无真实 LLM 的简单骨架做裁剪，使其可运行、可测试、不影响其他模块。

---

## 2. 核心决策

| 决策 | 说明 |
|------|------|
| **保留完整原文** | `TurnSummary` 新增 `full_content` 字段，压缩基于完整原文进行。 |
| **显示与触发分离** | `warning_level`（ok/high/critical）仅用于显示；每层压缩有独立的利用率阈值。 |
| **自动 + 手动触发** | `update()` 后自动检查阈值；同时暴露 `compact(force=False)` 手动接口。 |
| **AutoCompact 预留** | 因当前 Model 是 stub，AutoCompact 只记录事件、返回标记，不调用 LLM。 |
| **不影响外部接口** | `Context.update()` / `Context.get()` 契约不变；`get()` 返回的 dict 中新增 `compression` 字段。 |

---

## 3. 数据模型变更

### 3.1 `TurnSummary` 新增 `full_content`

```python
class TurnSummary(BaseModel):
    turn_id: int
    role: Literal["user", "assistant", "tool"]
    content_preview: str              # 120 字摘要，给 Skill/显示用
    full_content: str | None = None   # 完整原文，压缩用
    tool_calls: list[ToolCallRecord] | None = None
    timestamp: datetime
```

- `update(user_input)` 时，`full_content = user_input`，`content_preview = user_input[:120]`
- `update_with_result(result)` 时，工具结果也保存完整原文
- 压缩后，基于 `full_content` 重新生成 `content_preview`

### 3.2 新增 `CompressionState`

```python
class CompressionState(BaseModel):
    snip_triggered: bool = False
    micro_triggered: bool = False
    collapse_triggered: bool = False
    auto_triggered: bool = False
    compact_history: list[CompactEvent] = Field(default_factory=list)
```

```python
class CompactEvent(BaseModel):
    timestamp: datetime
    layer: Literal["snip", "micro", "collapse", "auto"]
    threshold: float
    usage_before: float
    usage_after: float
    turns_removed: int = 0
    notes: str = ""
```

### 3.3 `ContextState` 增加 `compression`

```python
class ContextState(BaseModel):
    recent_turns: list[TurnSummary] = Field(default_factory=list)
    topic: TopicState = Field(default_factory=TopicState)
    token_stats: TokenStats = Field(default_factory=TokenStats)
    compression: CompressionState = Field(default_factory=CompressionState)
    metadata: dict = Field(default_factory=dict)
```

---

## 4. 四层压缩语义

| 层级 | 触发阈值 | 操作 | 保护规则 |
|------|----------|------|----------|
| **SnipCompact** | ≥ 50% | 删除安全旧 turn，只保留最近 N 条 | 保留含 `write_file` / `edit` / `error` 的 turn；保留最近 `SAFE_TURNS` 条 |
| **MicroCompact** | ≥ 65% | 清空非最近 tool turn 的 `full_content`；合并相邻同角色 turn | 最近 `SAFE_TURNS` 条不受影响 |
| **ContextCollapse** | ≥ 80% | 把超过最近 `SAFE_TURNS` 条的旧 turn 合并成一条 summary turn | 最近 `SAFE_TURNS` 条保留；summary 用规则生成 |
| **AutoCompact** | ≥ 90% | 预留接口；记录事件；返回需要 LLM 压缩的标记 | 无 |

### 4.1 SnipCompact 细节

- 计算当前 token 利用率
- 如果 ≥ `SNIP_THRESHOLD` 且未触发过：
  - 从 `recent_turns` 头部开始扫描
  - 删除“安全”的 turn：不包含保护关键词、不在最近 `SAFE_TURNS` 内
  - 直到利用率降到阈值以下，或没有可删除的 turn
  - 标记 `snip_triggered = True`
  - 记录 `CompactEvent`

### 4.2 MicroCompact 细节

- 如果 ≥ `MICRO_THRESHOLD` 且未触发过：
  - 对所有非最近 `SAFE_TURNS` 的 tool turn，清空 `full_content`（保留 `content_preview`）
  - 合并相邻同角色 turn 的 `content_preview`（可选，本阶段简化处理）
  - 标记 `micro_triggered = True`
  - 记录 `CompactEvent`

### 4.3 ContextCollapse 细节

- 如果 ≥ `COLLAPSE_THRESHOLD` 且未触发过：
  - 把超过最近 `SAFE_TURNS` 条的旧 turn 合并为一条 `role="system"` 的 summary turn
  - summary 内容用规则生成，例如：
    ```
    [Summary of turns 1-5] Topics: weather, math. Last entities: Beijing.
    ```
  - 标记 `collapse_triggered = True`
  - 记录 `CompactEvent`

### 4.4 AutoCompact 细节

- 如果 ≥ `AUTO_THRESHOLD` 且未触发过：
  - 因当前无真实 LLM，不执行实际压缩
  - 标记 `auto_triggered = True`
  - 记录 `CompactEvent`，`notes="LLM compact not available in stub mode"`

---

## 5. 触发机制

### 5.1 自动触发

每次 `Context.update(user_input)` 后：

1. 更新 `recent_turns`、`topic`、`token_stats`
2. 按 Snip → Micro → Collapse → Auto 顺序检查阈值
3. 若某层未触发且利用率 ≥ 该层阈值，执行该层压缩
4. 压缩后重新计算 `token_stats`
5. 若利用率已降到下一层阈值以下，停止

### 5.2 手动触发

```python
context.compact(force=False)
```

- `force=False`：只执行当前阈值应触发的层（同自动逻辑）
- `force=True`：依次尝试执行所有四层（Auto 仍预留）

```python
context.reset_compression_flags()
```

- 重置所有压缩触发标记，允许重新触发

---

## 6. 配置项

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `SNIP_THRESHOLD` | 50.0 | SnipCompact 触发阈值（%） |
| `MICRO_THRESHOLD` | 65.0 | MicroCompact 触发阈值（%） |
| `COLLAPSE_THRESHOLD` | 80.0 | ContextCollapse 触发阈值（%） |
| `AUTO_THRESHOLD` | 90.0 | AutoCompact 触发阈值（%） |
| `SAFE_TURNS` | 3 | 每层压缩保护最近 N 条 turn |
| `PREVIEW_LENGTH` | 120 | content_preview 长度 |

---

## 7. 公开接口

```python
class Context:
    def __init__(self, config: dict | None = None) -> None: ...
    def update(self, user_input: str) -> ContextState: ...
    def update_with_result(self, result: dict | str) -> ContextState: ...
    def compact(self, force: bool = False) -> ContextState: ...
    def reset_compression_flags(self) -> None: ...
    def get(self) -> dict: ...
    def reset(self) -> None: ...
    def snapshot(self) -> ContextState: ...
```

---

## 8. 与现有模块的边界

- **Agent / Loop**：接口不变，仍然只调用 `context.update(user_input)` 和 `context.get()`。
- **Skill**：可以通过 `context.get()["compression"]` 感知压缩状态；不建议直接调用 `compact()`。
- **Memory**：压缩只影响 Context 中的 `recent_turns`，不影响 Memory 中存储的完整历史。

---

## 9. 测试计划

| 测试 | 目的 |
|------|------|
| `test_snip_compact_triggers_at_threshold` | 验证利用率 ≥ 50% 时删除旧安全 turn |
| `test_snip_compact_protects_keywords` | 验证含 `write_file` / `error` 的 turn 不被删除 |
| `test_micro_compact_clears_old_tool_full_content` | 验证旧 tool turn 的 full_content 被清空 |
| `test_context_collapse_merges_old_turns` | 验证旧 turn 被折叠为 summary |
| `test_auto_compact_is_noop_without_llm` | 验证 Auto 只记录事件 |
| `test_compact_manual_force` | 验证手动 force 触发多层 |
| `test_compression_flags_prevent_repeated_trigger` | 验证同一层不会重复触发 |
| `test_reset_compression_flags` | 验证重置标记后可重新触发 |
| `test_compact_event_recorded` | 验证每次压缩都记录 CompactEvent |

---

## 10. 与长远 AgentContext 计划的对应关系

| 本设计 | AgentContext 计划 | 差异 |
|--------|-------------------|------|
| SnipCompact | SnipCompact | 简化：只处理 `recent_turns` 列表 |
| MicroCompact | MicroCompact | 简化：只清空 tool full_content |
| ContextCollapse | ContextCollapse | 简化：用规则生成 summary，非 LLM |
| AutoCompact | AutoCompact | 预留：不调用 LLM |
| `CompressionState` | `compression_state` in `AgentState` | 字段对齐，便于未来迁移 |

---

## 11. 风险与规避

| 风险 | 规避 |
|------|------|
| 压缩误删重要 turn | 保护关键词 + 保留最近 `SAFE_TURNS` |
| 利用率估算不准 | 使用完整原文 `full_content` 重新估算 |
| AutoCompact 无法演示 | 记录事件并返回标记，未来接入 LLM 即启用 |
| 配置阈值不合理 | 所有阈值可配置，便于调试 |

---

## 12. 成功标准

- `Context.update()` 在利用率超过阈值时自动触发压缩
- `Context.compact(force=True)` 可手动触发所有可用层
- 每层压缩后 `token_stats` 重新计算并更新
- 压缩事件被记录到 `compression.compact_history`
- 单元测试覆盖 4 层压缩 + 边界情况
- `uv run loop.py` 仍然正常运行
