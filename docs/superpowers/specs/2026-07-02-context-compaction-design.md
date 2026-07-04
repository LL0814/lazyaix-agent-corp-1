# Context 四层压缩设计文档

> 基于 `docs/CONTEXT_COMPACT_PLAN.md`，为当前通用多工具 Python agent 项目设计上下文压缩方案。
> 日期：2026-07-02
> 技术栈：Python
> 范围：L1~L4 压缩 + reactive 应急压缩

---

## 1. 目标与设计原则

### 目标

让 agent 能在长会话（数百轮工具调用）中持续工作而不触发 `prompt_too_long`，且尽可能保留对当前任务有用的信息。

### 设计原则

| 原则 | 含义 |
|------|------|
| **便宜的先跑，贵的后跑** | 0 API 的结构操作优先，LLM 摘要作为最后手段 |
| **分层渐进降级** | 从「替换单条内容」到「裁掉整段消息」再到「全量摘要」，激进度递增 |
| **可逆性递减** | 落盘可恢复 > 留占位符可重跑 > 仅留摘要 |
| **不变量保护** | 任何压缩都不能产生孤立的 `tool_result`（前面缺 `tool_use`） |
| **失败兜底** | 每层都有熔断/重试上限，全部失败才抛异常 |
| **不改动 agent 主流程** | 压缩层作为独立工具函数，通过 `Context` 内部转换接入当前 `TurnSummary` 模型 |

---

## 2. 总体架构

### 执行管线

```
Context.update() / update_with_result()
    ↓
TurnSummary → 标准消息 dict 列表
    ↓
L3: tool_result_budget   (0 API)  大结果落盘
    ↓
L1: snip_compact         (0 API)  裁中间消息
    ↓
L2: micro_compact        (0 API)  旧 tool_result 占位
    ↓
[estimate_size(messages) > CONTEXT_LIMIT?]
    ├─ No  → 结束
    └─ Yes → L4: compact_history (1 API)  全量摘要
                  ↓
           同步回 recent_turns
```

**执行顺序固定为 L3 → L1 → L2 → L4**，原因见 `CONTEXT_COMPACT_PLAN.md`：
- L3 必须在 L2 之前，否则 L2 把旧 tool_result 替换成占位符后，L3 落盘的是占位符，原始数据永久丢失。
- L1 在 L2 之前，避免先占位再裁剪的重复工作。

### 模块划分

```
context/
├── __init__.py          # 导出 Context
├── models.py            # TurnSummary、CompressionState、CompactEvent 等数据模型
├── state.py             # Context 类：维护 recent_turns + _messages，调用压缩管线
├── compaction.py        # L1~L4 + reactive_compact 纯函数
├── adapter.py           # CompactAdapter 协议 + RuleBasedCompactAdapter
├── utils.py             # estimate_size、tool 配对判断、transcript 落盘
└── config.py            # 默认配置常量
```

### 调用关系

```
loop.py / agent.py
    ↓ Context.update() / Context.get() / Context.get_messages()
context/state.py (Context)
    ↓ 内部维护 recent_turns + _messages
    ↓ _turn_to_message() 把 TurnSummary 转成标准 dict 列表
context/compaction.py
    ↓ L3 → L1 → L2 → L4
context/adapter.py
    ↓ summarize_history()
context/utils.py
    ↓ estimate_size() / tool 配对判断 / transcript 落盘
```

---

## 3. 数据模型

### `TurnSummary`（基本不变）

```python
class TurnSummary(BaseModel):
    turn_id: int
    role: Literal["user", "assistant", "tool", "system"]
    content_preview: str
    full_content: str | None = None
    tool_calls: list[ToolCallRecord] | None = None
    timestamp: datetime
```

### `CompactEvent`

```python
class CompactEvent(BaseModel):
    timestamp: datetime
    layer: Literal[
        "tool_result_budget",
        "snip",
        "micro",
        "compact_history",
        "reactive",
    ]
    usage_before: int  # 字符数
    usage_after: int
    notes: str = ""
```

### `CompressionState`

```python
class CompressionState(BaseModel):
    tool_result_budget_triggered: bool = False
    snip_triggered: bool = False
    micro_triggered: bool = False
    compact_history_triggered: bool = False
    compact_history_failures: int = 0
    compact_history_disabled: bool = False
    compact_history_path: str | None = None  # 上次 transcript 路径
    compact_history_summary: str | None = None
    compact_history: list[CompactEvent] = Field(default_factory=list)
```

### `ContextState`

```python
class ContextState(BaseModel):
    recent_turns: list[TurnSummary] = Field(default_factory=list)
    topic: TopicState = Field(default_factory=TopicState)
    token_stats: TokenStats = Field(default_factory=TokenStats)
    compression: CompressionState = Field(default_factory=CompressionState)
    metadata: dict = Field(default_factory=dict)
```

---

## 4. 消息格式转换

`Context` 内部维护 `_messages`（标准 Anthropic 风格 dict 列表），与 `recent_turns` 同步。

### TurnSummary → dict

| TurnSummary | 转换后消息 |
|------------|-----------|
| `role="user"` | `{"role": "user", "content": "..."}` |
| `role="assistant"`，无 `tool_calls` | `{"role": "assistant", "content": "..."}` |
| `role="assistant"`，有 `tool_calls` | `{"role": "assistant", "content": [{"type": "tool_use", "id": ..., "name": ..., "input": ...}]}` |
| `role="tool"` | `{"role": "user", "content": [{"type": "tool_result", "tool_use_id": ..., "content": "..."}]}` |
| `role="system"` | `{"role": "system", "content": "..."}` |

### dict → TurnSummary

压缩后 `_messages` 可能包含占位符消息或摘要消息，需要同步回 `recent_turns`：
- 普通 user/assistant 消息 → `TurnSummary(role=..., content_preview=..., full_content=...)`
- `tool_use` / `tool_result` block → 恢复为 `TurnSummary(role="assistant"/"tool", tool_calls=...)`
- `[snipped N messages]` / `[Compacted]` 占位符 → `TurnSummary(role="system", ...)`

同步策略：当 `_messages` 长度因 snip 缩短时，`recent_turns` 也相应截断；当消息内容被替换为占位符时，更新对应 `TurnSummary` 的 `full_content` 和 `content_preview`。

---

## 5. 压缩层详细设计

### 配置常量

```python
CONTEXT_LIMIT = 50_000          # 字符数估算，约 12K token
KEEP_RECENT_TOOL_RESULTS = 3    # micro_compact 保留最近几条
KEEP_RECENT_MESSAGES = 50       # snip_compact 触发阈值
PERSIST_THRESHOLD = 30_000      # 单条结果超过多大才落盘
TOOL_RESULT_BUDGET = 200_000    # 单条 user 消息 tool_result 总量上限
MAX_REACTIVE_RETRIES = 1
MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3
```

这些作为 `Context` 默认配置，可通过 `config=dict(...)` 覆盖。

### L3: `tool_result_budget(messages, max_bytes=TOOL_RESULT_BUDGET)`

- **触发**：最后一条 user 消息内所有 `tool_result` block 总大小 > `max_bytes`
- **行为**：按大小降序落盘，单条 > `PERSIST_THRESHOLD` 才处理
- **输出**：上下文里保留 `<persisted-output>` 标记 + 前 2000 字符预览
- **不变量**：不拆 `tool_use` / `tool_result` 对

### L1: `snip_compact(messages, max_messages=KEEP_RECENT_MESSAGES)`

- **触发**：`len(messages) > max_messages`
- **行为**：保留头部 3 条 + 尾部 47 条，中间替换为占位符消息
- **不变量**：头部/尾部边界处若切到 `tool_use` / `tool_result` 对，自动扩展保留区
- **输出**：`[{"role": "user", "content": "[snipped N messages]"}]`

### L2: `micro_compact(messages, keep_recent=KEEP_RECENT_TOOL_RESULTS)`

- **触发**：消息中 `tool_result` block 数量 > `keep_recent`
- **行为**：保留最近 3 个完整 `tool_result`，更旧的替换为占位符
- **关键**：短结果（<120 字符）不值得替换
- **输出**：就地修改 block，不重建消息列表

### L4: `compact_history(messages, adapter)`

- **触发**：`estimate_size(messages) > CONTEXT_LIMIT`
- **三步**：
  1. `write_transcript(messages)` 落盘完整对话到 `.transcripts/`
  2. `adapter.summarize_history(messages)` 生成摘要
  3. 返回 `[{"role": "user", "content": f"[Compacted]\n\n{summary}"}]`
- **失败兜底**：摘要失败返回 `(empty summary)`，不抛异常；连续失败 3 次后禁用

### `reactive_compact(messages, adapter)`

- **触发**：LLM 调用报 `prompt_too_long` 后
- **行为**：保留尾部 5 条原文，前面全部摘要
- **不变量**：同样做 `tool_use` / `tool_result` 配对保护

### 执行入口

```python
def run_compaction(messages, adapter, config):
    messages[:] = tool_result_budget(messages, config.tool_result_budget)
    messages[:] = snip_compact(messages, config.keep_recent_messages)
    messages[:] = micro_compact(messages, config.keep_recent_tool_results)
    if estimate_size(messages) > config.context_limit:
        messages[:] = compact_history(messages, adapter)
    return messages
```

---

## 6. Adapter 接口

### `CompactAdapter` 协议

```python
from typing import Protocol


class CompactAdapter(Protocol):
    """为 L4 / reactive 生成摘要的适配器接口。"""

    def summarize_history(self, messages: list[dict]) -> str:
        """为 compact_history / reactive_compact 生成全局摘要。"""
        ...
```

> 该计划里没有 `summarize_span`（对应 MiniCode 的 ContextCollapse），因为 L3 落盘已经覆盖了大结果处理场景。

### `RuleBasedCompactAdapter`

默认实现，不调用 LLM，用于测试和 demo：

```python
class RuleBasedCompactAdapter:
    def summarize_history(self, messages: list[dict]) -> str:
        # 提取 topics、entities、关键 tool 调用
        # 返回简化版结构化摘要
        ...
```

### 未来接入真实 LLM

```python
class LLMCompactAdapter:
    def __init__(self, model: Model):
        self.model = model

    def summarize_history(self, messages: list[dict]) -> str:
        prompt = build_compact_history_prompt(messages)
        return self.model.complete(prompt)
```

---

## 7. `Context` 类修改

### 构造参数

```python
class Context:
    def __init__(self, config=None, compact_adapter=None):
        ...
        self.compact_adapter = compact_adapter or RuleBasedCompactAdapter()
        self._messages = []  # 标准 dict 列表
```

### 配置字段调整

移除旧的百分比阈值：
- `snip_threshold`
- `micro_threshold`
- `collapse_threshold`
- `auto_threshold`

新增配置字段：
- `context_limit`
- `keep_recent_tool_results`
- `keep_recent_messages`
- `persist_threshold`
- `tool_result_budget`
- `max_reactive_retries`
- `max_consecutive_autocompact_failures`

### 核心方法

```python
def _turn_to_message(self, turn: TurnSummary) -> dict:
    """把 TurnSummary 转成 Anthropic 风格消息 dict。"""

def _sync_messages_to_turns(self):
    """压缩后把 _messages 同步回 recent_turns。"""

def update(self, user_input: str) -> ContextState:
    """添加 user turn，运行压缩管线。"""

def update_with_result(self, result) -> ContextState:
    """添加 assistant/tool turn，运行压缩管线。"""

def get_messages(self) -> list[dict]:
    """返回压缩后的标准消息列表（给 LLM 用）。"""

def compact(self, force=False) -> ContextState:
    """手动触发 L4 compact_history。"""
```

### 不变量

- 每次 `update` / `update_with_result` 后 `_messages` 必须经过 `run_compaction`
- `recent_turns` 与 `_messages` 保持同步
- 调用方仍通过 `Context.get()` 拿 dict，`get_messages()` 返回标准消息列表

---

## 8. Demo 与测试

### `demo_compression.py`

按新四层顺序展示：
- Demo L3：单条 500KB tool result → 落盘
- Demo L1：100 条消息 → snip 到 50 条
- Demo L2：10 条 tool_result → 前 7 条变占位符
- Demo L4：总量超 50K → 压缩为 1 条摘要
- Demo reactive：模拟 prompt_too_long → 保留尾部 5 条
- Demo 综合：长会话跑完不超限

### 测试文件

| 测试文件 | 覆盖 |
|---------|------|
| `tests/test_compaction_utils.py` | `estimate_size`、tool 配对判断、transcript 落盘 |
| `tests/test_compaction_l1_l2_l3.py` | 各层独立行为和不变量 |
| `tests/test_compaction_l4.py` | `compact_history`、adapter、失败兜底 |
| `tests/test_context.py` | Context 集成、`_messages` 与 `recent_turns` 同步 |

### 核心不变量测试

```python
def assert_no_orphan_tool_results(messages):
    for idx, msg in enumerate(messages):
        if _is_tool_result_message(msg):
            assert idx > 0
            assert _message_has_tool_use(messages[idx - 1])
```

---

## 9. 实现阶段

按 `CONTEXT_COMPACT_PLAN.md` 的 P0~P4 分阶段实现：

| 阶段 | 内容 | 可验证产出 |
|------|------|-----------|
| P0 | 基础设施：`estimate_size`、消息工具函数、配置常量、transcript 落盘 | `estimate_size()` 单测通过 |
| P1 | L2 `micro_compact` + L4 `compact_history` | 单层压缩可用 |
| P2 | L3 `tool_result_budget` + L1 `snip_compact` | 四层管线完整 |
| P3 | `reactive_compact` + `Context` 集成 | 端到端可用 |
| P4 | 测试套件、熔断器、监控埋点 | 生产就绪 |

---

## 10. 风险与后续扩展

### 主要风险

1. **配对保护失败** → API 报错，会话中断
   - 缓解：完整的不变量测试套件，每次改动都跑
2. **摘要丢失关键信息** → agent 行为偏离用户意图
   - 缓解：优化 `RuleBasedCompactAdapter` 的摘要逻辑；未来接入 LLM
3. **transcript 落盘无检索** → 历史信息实际不可恢复
   - 缓解：MVP 可接受，后续接 RAG 检索或加 `read_transcript` 工具
4. **token 估算不准** → 压缩触发过早或过晚
   - 缓解：先按字符数跑通，生产环境换 `tiktoken` 或模型自带计数

### 后续扩展

1. 精确 token 计数
2. `read_file` 恢复机制：compact 后自动重读最近 N 个文件
3. session memory 集成：compact 前先做免 LLM 的轻量摘要
4. transcript 检索工具
5. 摘要 prompt 强化：加 `<analysis>` / `<summary>` 双标签
6. 接入真实 LLM adapter

---

## 11. 验收清单

- [ ] 连续读 20 个大文件，不报 `prompt_too_long`
- [ ] 单次 tool 输出 500KB，触发 L3 落盘
- [ ] 100 轮对话后，触发 L1 snip
- [ ] tool_result 累积超 3 条，触发 L2 micro
- [ ] 总量超 50K 字符，触发 L4 compact_history
- [ ] 强制构造超大上下文，触发 reactive_compact 并重试成功
- [ ] 所有压缩层输出无孤立 tool_result
- [ ] 连续失败 3 次后熔断器打开，不再重试
- [ ] reactive 重试 1 次后仍失败，抛出异常而非无限循环
