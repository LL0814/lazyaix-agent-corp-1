# Context 模块设计文档

> **日期**：2026-07-01  
> **项目**：agent-team-exercise 模块化 Agent 团队练习  
> **主题**：Context（上下文系统）模块设计  
> **版本**：实用对话版（方案 2：Pydantic 类型化 Context）

---

## 1. 目标

为团队练习项目设计并实现一个**实用对话版 Context 模块**，在保持与现有 `loop.py` / `agent.py` 接口兼容的前提下，维护当前会话的活跃状态，支持 Skill 做出更合理的路由决策。

本期重点：

- **A. 最近 N 轮对话摘要**
- **B. 当前会话活跃主题 / 意图**
- **G. Token 利用率 / 上下文压力指标**

---

## 2. 模块定位与边界

| 模块 | 职责 | 边界 |
|------|------|------|
| **Context** | 维护当前会话的**活跃状态**：最近几轮摘要、当前主题、Token 压力。 | 不存完整历史，不存长期记忆。 |
| **Memory** | 持久化完整对话历史、用户偏好等可回放信息。 | Memory 是“存储”，Context 是“活跃视图”。 |
| **Skill** | 根据 `context.get()` 决定直接回答还是调用工具。 | Skill 可以读取 Context，但不应直接修改 Context。 |
| **Agent** | 协调流程：先 `context.update(input)`，再拼 prompt，再 `skill.decide(...)`，最后 `memory.store(...)`。 | Agent 负责在适当时机调用 Context 的更新方法。 |

**关键原则**：

- Context 是“短生命周期、高频读取”的内存状态。
- Memory 是“长生命周期、可持久化”的存储。
- Skill 通过 Context 感知“现在聊到哪了”，通过 Memory 感知“过去聊过什么”。

---

## 3. 核心数据模型

使用 Pydantic v2 定义以下模型。

### 3.1 `ToolCallRecord`

```python
class ToolCallRecord(BaseModel):
    tool_name: str
    params: dict
    result_preview: str | None = None
```

### 3.2 `TurnSummary`

```python
class TurnSummary(BaseModel):
    turn_id: int
    role: Literal["user", "assistant", "tool"]
    content_preview: str
    tool_calls: list[ToolCallRecord] | None = None
    timestamp: datetime
```

### 3.3 `TopicState`

```python
class TopicState(BaseModel):
    primary_topic: str | None = None
    intent: str | None = None
    active_entities: list[str] = Field(default_factory=list)
    last_updated_turn: int = 0
```

### 3.4 `TokenStats`

```python
class TokenStats(BaseModel):
    estimated_tokens: int = 0
    context_limit: int = 4000
    usage_pct: float = 0.0
    warning_level: Literal["ok", "high", "critical"] = "ok"
```

### 3.5 `ContextState`

```python
class ContextState(BaseModel):
    recent_turns: list[TurnSummary] = Field(default_factory=list)
    topic: TopicState = Field(default_factory=TopicState)
    token_stats: TokenStats = Field(default_factory=TokenStats)
    metadata: dict = Field(default_factory=dict)
```

---

## 4. Context 类公开接口

保持与现有 `agent.py` / `loop.py` 的契约兼容：

```python
class Context:
    def __init__(self, config: dict | None = None) -> None: ...
    def update(self, user_input: str) -> ContextState: ...
    def update_with_result(self, result: dict | str) -> ContextState: ...
    def get(self) -> dict: ...
    def reset(self) -> None: ...
    def snapshot(self) -> ContextState: ...
```

### 4.1 方法说明

- **`__init__(config)`**：读取可选配置，如 `CONTEXT_LIMIT`（默认 4000）、`MAX_RECENT_TURNS`（默认 5）。
- **`update(user_input)`**：每轮用户输入时调用，追加 user turn，更新主题/意图/Token 估算，返回更新后的 `ContextState`。
- **`update_with_result(result)`**：当 Skill 决定调用工具并拿到结果后调用，追加 tool/assistant turn。`result` 为 `dict` 时包含 `tool_name`、`params`、`result_preview` 字段；为 `str` 时仅作为 assistant 回复摘要。该方法是可选扩展，供未来使用。
- **`get()`**：返回 `ContextState` 的 `dict` 形式，保持与现有 `Skill.decide(...)` 的兼容性。
- **`reset()`**：清空状态，用于 `/reset` 命令或新会话。
- **`snapshot()`**：返回当前 `ContextState` 模型的只读副本。

### 4.2 设计决策

`get()` 返回 `dict` 而不是 Pydantic 模型，是为了不强制其他模块（Skill、Agent）引入 Pydantic 依赖。

---

## 5. 与现有 agent.py / loop.py 集成

当前 `Agent.process_turn()` 流程：

```python
if self._context_enabled():
    self.context.update(user_input)

prompt = self._build_prompt(user_input)
llm_response = self.model.complete(prompt)
decision = self.skill.decide(
    user_input, llm_response, self.context.get(), self.memory
)
```

### 5.1 集成方式

- 不修改 `agent.py` 的接口调用方式。
- `Context.update()` 和 `Context.get()` 替换掉 `loop.py` 里的 Stub。
- 可选扩展：在 Agent 调用 `Tool.execute()` 拿到结果后，增加一行 `self.context.update_with_result(result)`，让 Context 也能记录工具结果摘要。该扩展需要和同学协商是否修改 `agent.py`，本设计不做强制要求。

---

## 6. 活跃主题 / 意图推断策略

采用**简单规则 + 可选 Skill 写入**的混合策略。

### 6.1 默认规则推断（零依赖）

关键词匹配示例：

| 关键词 | primary_topic | intent |
|--------|---------------|--------|
| `weather` / `天气` | `weather` | `query` |
| `calculate` / `计算` | `math` | `compute` |
| `write` / `写文件` / `edit` | `file_edit` | `request` |

实体提取：使用正则提取引号内文件名、城市名等简单实体，存入 `active_entities`。

### 6.2 Skill 写入

- `ContextState.metadata` 预留扩展字段，供 Skill 或未来功能使用。
- 未来 Skill 可以通过 `context.get()` 读取当前主题，也可以建议 Agent 调用 `context.set_topic(...)`（可选扩展方法）。

### 6.3 本期范围

本期先做规则推断，不引入 LLM 做意图识别。

---

## 7. Token 估算策略

当前项目没有真实 LLM usage，因此采用基于字符数的启发式估算：

```python
estimated_tokens = ceil(total_chars / 4)
```

### 7.1 参数来源

- `context_limit`：从 config 读取，默认 4000。
- `usage_pct`：`estimated_tokens / context_limit * 100`。
- `warning_level`：
  - `< 50%` → `ok`
  - `50% - 80%` → `high`
  - `>= 80%` → `critical`

### 7.2 未来扩展

接入真实 LLM 后，可通过新增方法 `update_with_usage(input_tokens, output_tokens)` 覆盖估算值。

### 7.3 本期范围

本期只做估算和分级，不触发压缩（压缩是未来 AgentContext 框架 Phase 3 的内容）。

---

## 8. 错误处理与边界情况

| 场景 | 处理 |
|------|------|
| `update()` 收到空输入 | 记录为内容空字符串，仍更新 turn，主题/意图保持不变。 |
| `recent_turns` 超过 N 条 | 保留最近 N 条，旧的丢弃。 |
| 主题推断失败 | `primary_topic` / `intent` 为 `None`，不抛异常。 |
| `context_limit` 配置非法 | 回退到默认值 4000，打印 warning。 |
| Pydantic 未安装 | 这是必须依赖，应在 `pyproject.toml` 中声明。 |
| `get()` 被调用前未 update | 返回默认空 `ContextState` 的 dict。 |

---

## 9. 测试思路

### 9.1 单元测试

- `Context.update()` 后 `recent_turns` 是否正确追加。
- 超过 N 轮后旧 turn 是否被丢弃。
- 主题推断规则是否命中预期关键词。
- Token 估算和 warning_level 分级是否正确。

### 9.2 集成测试

- 把 `Context` 替换进 `agent.py`，运行 REPL，验证 `Skill.decide()` 能读到 context。
- 验证 `Context.get()` 返回 dict，保持向后兼容。

### 9.3 边界测试

- 空输入、超长输入、非法 config、未 update 直接 get。

---

## 10. 依赖

- `pydantic >= 2.0`（新增到 `pyproject.toml` 的 `dependencies`）

---

## 11. 成功标准

- `context/` 模块能被 `loop.py` 正常导入并替换 Stub。
- `Agent.process_turn()` 在不修改调用方式的前提下使用新的 Context。
- `context.get()` 返回包含 `recent_turns`、`topic`、`token_stats` 的 dict。
- 单元测试覆盖核心推断、Token 估算、边界情况。

---

## 12. 与未来 AgentContext 框架的关系

本设计是长期 AgentContext 执行计划中“会话状态”的最小可行版本：

- 使用 Pydantic 类型系统，与未来技术栈对齐。
- `ContextState` 是未来 `AgentState` / `SessionState` 的简化版。
- Token 估算为未来四层压缩引擎提供基础统计能力。
- 本期不做持久化、Checkpointer、压缩节点，这些属于后续 Phase。
