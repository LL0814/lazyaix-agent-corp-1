# 上下文压缩实现计划

> 借鉴 Claude Code 的四层压缩策略，为通用多工具 Python agent 设计的完整实现路线。
> 技术栈：Python · 范围：四层 + 应急 · 场景：通用多工具 agent

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

---

## 2. 总体架构

```
┌──────────────────────────────────────────────────────────────┐
│  agent_loop 每轮 LLM 调用前                                   │
│                                                              │
│  messages[]                                                  │
│    ↓                                                         │
│  L3: tool_result_budget   (0 API)  大结果落盘                │
│    ↓                                                         │
│  L1: snip_compact         (0 API)  裁中间消息                │
│    ↓                                                         │
│  L2: micro_compact         (0 API)  旧 tool_result 占位      │
│    ↓                                                         │
│  [estimate_size > THRESHOLD?]                                │
│    ├─ No  → 直接 LLM 调用                                    │
│    └─ Yes → L4: compact_history (1 API)  全量摘要             │
│                  ↓                                           │
│             LLM 调用                                         │
│    [prompt_too_long?]                                        │
│      └─ Yes → reactive_compact (1 API)  应急切尾              │
│                  ↓                                           │
│            重试 LLM 调用 (上限 1 次)                          │
└──────────────────────────────────────────────────────────────┘
```

**执行顺序固定为 L3 → L1 → L2 → L4**。原因：
- L3 必须在 L2 之前，否则 L2 把旧 tool_result 替换成占位符后，L3 落盘落的是占位符，原始数据永久丢失
- L1 在 L2 之前，避免先占位再裁剪的重复工作

---

## 3. 实现路线图

分 5 个阶段，每阶段可独立验证后再进入下一阶段。

| 阶段 | 内容 | 依赖 | 可验证产出 |
|------|------|------|-----------|
| P0 | 基础设施：token 估算、消息工具函数、配置常量 | 无 | `estimate_size()` 可用 |
| P1 | L2 micro_compact + L4 compact_history | P0 | 单层压缩可用 |
| P2 | L3 tool_result_budget + L1 snip_compact | P0 | 四层管线完整 |
| P3 | reactive_compact + agent_loop 集成 | P1, P2 | 端到端可用 |
| P4 | 测试套件、熔断器、监控埋点 | P3 | 生产就绪 |

---

## 4. 各阶段详细任务

### P0: 基础设施

**目标**：搭建后续所有压缩层共用的工具函数。

#### 任务清单

- [ ] 定义配置常量
- [ ] 实现 `estimate_size(messages) -> int`
- [ ] 实现消息类型判断辅助函数
- [ ] 搭建 transcript 落盘目录结构

#### 关键代码

```python
# config.py
from pathlib import Path

WORKDIR = Path.cwd()
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"

CONTEXT_LIMIT = 50_000          # 字符数估算，约 12K token
KEEP_RECENT_TOOL_RESULTS = 3    # micro_compact 保留最近几条
KEEP_RECENT_MESSAGES = 50       # snip_compact 触发阈值
PERSIST_THRESHOLD = 30_000      # 单条结果超过多大才落盘
TOOL_RESULT_BUDGET = 200_000    # 单条 user 消息 tool_result 总量上限
MAX_REACTIVE_RETRIES = 1
MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3
```

```python
# utils.py
def estimate_size(messages: list) -> int:
    """粗略 token 估算：~4 字符 / token。
    生产环境建议替换为精确 tokenizer (tiktoken / anthropic.count_tokens)。
    """
    return len(str(messages)) // 4

def _block_type(block):
    if isinstance(block, dict):
        return block.get("type")
    return getattr(block, "type", None)

def _message_has_tool_use(msg) -> bool:
    """该消息是否包含 tool_use block（用于配对保护）"""
    if msg.get("role") != "assistant":
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(_block_type(b) == "tool_use" for b in content)

def _is_tool_result_message(msg) -> bool:
    """该消息是否是 tool_result 容器（用于配对保护）"""
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(b, dict) and b.get("type") == "tool_result"
               for b in content)
```

**验证标准**：单元测试覆盖 `estimate_size` 边界（空列表、单条、超大列表）。

---

### P1: L2 micro_compact + L4 compact_history

**目标**：实现最关键的两层——0 API 的旧结果占位，和 1 API 的全量摘要。这两层覆盖了 80% 的场景。

#### L2: micro_compact

**触发条件**：tool_result 数量 > `KEEP_RECENT_TOOL_RESULTS`（默认 3）

**逻辑**：保留最近 3 条 tool_result 完整内容，更旧的替换为一行占位符。**就地修改 block，不重建消息列表**——保留 role、tool_use_id 等元信息。

```python
def collect_tool_results(messages):
    """收集所有 tool_result block 及其位置"""
    blocks = []
    for msg_idx, msg in enumerate(messages):
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            continue
        for block_idx, block in enumerate(msg["content"]):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                blocks.append((msg_idx, block_idx, block))
    return blocks

def micro_compact(messages, keep_recent=KEEP_RECENT_TOOL_RESULTS):
    tool_results = collect_tool_results(messages)
    if len(tool_results) <= keep_recent:
        return messages
    for _, _, block in tool_results[:-keep_recent]:
        # 短结果不值得替换（避免误伤）
        if len(block.get("content", "")) > 120:
            block["content"] = "[Earlier tool result compacted. Re-run if needed.]"
    return messages
```

**验证标准**：
- [ ] 10 条 tool_result 时，前 7 条被替换为占位符
- [ ] ≤3 条 tool_result 时不触发
- [ ] 短结果（<120 字符）不被替换
- [ ] 消息列表结构不变（role、tool_use_id 保留）

#### L4: compact_history

**触发条件**：`estimate_size(messages) > CONTEXT_LIMIT`

**三步流程**：

```python
import json, time

def write_transcript(messages):
    """第 1 步：保存完整对话到磁盘，可追溯"""
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with path.open("w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    return path

def summarize_history(messages, client, model):
    """第 2 步：LLM 生成摘要"""
    # 截断防止摘要请求本身超限
    conversation = json.dumps(messages, default=str)[:80000]
    prompt = (
        "Summarize this agent conversation so work can continue.\n"
        "Preserve:\n"
        "1. current goal\n"
        "2. key findings/decisions\n"
        "3. files read/changed\n"
        "4. remaining work\n"
        "5. user constraints\n"
        "Be compact but concrete.\n\n"
        + conversation
    )
    response = client.messages.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
    )
    # 提取文本，失败兜底
    return "\n".join(
        getattr(b, "text", "")
        for b in response.content
        if getattr(b, "type", None) == "text"
    ).strip() or "(empty summary)"

def compact_history(messages, client, model):
    """第 3 步：替换整个消息列表"""
    transcript_path = write_transcript(messages)
    print(f"[transcript saved: {transcript_path}]")
    summary = summarize_history(messages, client, model)
    return [{"role": "user", "content": f"[Compacted]\n\n{summary}"}]
```

**验证标准**：
- [ ] 触发后消息列表只剩 1 条摘要消息
- [ ] transcript 文件存在于 `.transcripts/`
- [ ] 摘要包含用户最后一条指令的关键信息
- [ ] LLM 调用失败时返回 `(empty summary)` 不崩溃

#### 阶段集成测试

用一个会跑爆上下文的场景（连续读 20 个大文件 + 反复对话）验证：
- [ ] 没有压缩时 API 报 `prompt_too_long`
- [ ] 接入 L2 + L4 后能持续工作
- [ ] transcript 完整可读

---

### P2: L3 tool_result_budget + L1 snip_compact

**目标**：补齐剩余两层，完成四层管线。

#### L3: tool_result_budget

**触发条件**：最后一条 user 消息内所有 tool_result 总大小 > `TOOL_RESULT_BUDGET`（默认 200KB）

**关键设计**：
- **只看最后一条 user 消息**（当前轮新增的结果）
- **按大小降序落盘**，最大的先处理
- 单条 > `PERSIST_THRESHOLD`（30KB）才落盘
- 上下文里留 `<persisted-output>` 标记 + 前 2000 字符预览

```python
def persist_large_output(tool_use_id, output):
    """落盘大输出，返回占位标记"""
    if len(output) <= PERSIST_THRESHOLD:
        return output
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = TOOL_RESULTS_DIR / f"{tool_use_id}.txt"
    if not path.exists():
        path.write_text(output)
    return (
        f"<persisted-output>\n"
        f"Full output: {path}\n"
        f"Preview:\n{output[:2000]}\n"
        f"</persisted-output>"
    )

def tool_result_budget(messages, max_bytes=TOOL_RESULT_BUDGET):
    last = messages[-1] if messages else None
    # 只处理 user 消息且 content 是 list（即 tool_result 容器）
    if (not last or last.get("role") != "user"
            or not isinstance(last.get("content"), list)):
        return messages

    blocks = [(i, b) for i, b in enumerate(last["content"])
              if isinstance(b, dict) and b.get("type") == "tool_result"]
    total = sum(len(str(b.get("content", ""))) for _, b in blocks)
    if total <= max_bytes:
        return messages

    # 按大小降序，从最大的开始落盘
    ranked = sorted(blocks, key=lambda p: len(str(p[1].get("content", ""))),
                    reverse=True)
    for _, block in ranked:
        if total <= max_bytes:
            break
        content = str(block.get("content", ""))
        if len(content) <= PERSIST_THRESHOLD:
            continue
        tid = block.get("tool_use_id", "unknown")
        block["content"] = persist_large_output(tid, content)
        # 落盘后重新计算总量
        total = sum(len(str(b.get("content", ""))) for _, b in blocks)
    return messages
```

**验证标准**：
- [ ] 单条 500KB 结果被落盘，上下文只剩预览 + 文件路径
- [ ] 多条小结果总和超限时，最大的先落盘
- [ ] <30KB 的结果不被落盘
- [ ] 落盘文件可读，内容与原始一致

#### L1: snip_compact

**触发条件**：消息数 > `KEEP_RECENT_MESSAGES`（默认 50）

**关键设计**：保留头部 3 条 + 尾部 47 条，中间替换为占位符。**核心是 tool_use/tool_result 配对保护**——绝不能产生孤立的 tool_result。

```python
def snip_compact(messages, max_messages=KEEP_RECENT_MESSAGES):
    if len(messages) <= max_messages:
        return messages
    keep_head, keep_tail = 3, max_messages - 3
    head_end, tail_start = keep_head, len(messages) - keep_tail

    # 头部边界：若保留的最后一条 head 是 tool_use，
    # 把后续的 tool_result 消息也纳入 head
    if head_end > 0 and _message_has_tool_use(messages[head_end - 1]):
        while (head_end < len(messages)
               and _is_tool_result_message(messages[head_end])):
            head_end += 1

    # 尾部边界：若切到的就是 tool_result，前移一格把 tool_use 也留住
    if (tail_start > 0 and tail_start < len(messages)
            and _is_tool_result_message(messages[tail_start])
            and _message_has_tool_use(messages[tail_start - 1])):
        tail_start -= 1

    # 保底：调整后若 head 区比裁掉区还大，放弃裁剪
    if head_end >= tail_start:
        return messages

    snipped = tail_start - head_end
    return (messages[:head_end]
            + [{"role": "user", "content": f"[snipped {snipped} messages]"}]
            + messages[tail_start:])
```

**验证标准**（最重要的一组测试）：
- [ ] 100 条消息时被裁到 50 条左右
- [ ] 头部边界 tool_use → tool_result 不被拆开
- [ ] 尾部边界 tool_use → tool_result 不被拆开
- [ ] 调整后无孤立 tool_result（用 `assert_no_orphan_tool_results` 校验）
- [ ] head_end >= tail_start 时不裁剪

---

### P3: reactive_compact + agent_loop 集成

**目标**：实现 API 报错兜底，把所有压缩层串进 agent 主循环。

#### reactive_compact

**触发条件**：LLM 调用抛出 `prompt_too_long` 异常

**关键设计**：比 L4 更激进——只保留尾部 5 条原文，前面的全摘要。但同样要保护 tool_use/tool_result 配对。

```python
def reactive_compact(messages, client, model):
    transcript = write_transcript(messages)
    tail_start = max(0, len(messages) - 5)

    # 同样的配对保护
    if (tail_start > 0 and tail_start < len(messages)
            and _is_tool_result_message(messages[tail_start])
            and _message_has_tool_use(messages[tail_start - 1])):
        tail_start -= 1

    # 只对前半段摘要，保留尾部原文
    summary = summarize_history(messages[:tail_start], client, model)
    return ([{"role": "user", "content": f"[Reactive compact]\n\n{summary}"}]
            + list(messages[tail_start:]))
```

**与 L4 的差异**：
- L4 替换**全部**消息为摘要
- reactive 保留尾部 5 条原文，给模型留「当前正在做什么」的即时上下文

**验证标准**：
- [ ] 9 条消息时保留尾部 4-5 条（受配对保护影响）
- [ ] 摘要只覆盖 `messages[:tail_start]`，不重新摘要尾部
- [ ] 输出无孤立 tool_result

#### agent_loop 集成

把所有压缩层串进主循环。**关键：执行顺序固定**。

```python
class PromptTooLongError(Exception):
    pass

def agent_loop(messages, client, model, tools):
    reactive_retries = 0
    while True:
        # === 三层预处理器（0 API，顺序固定） ===
        messages[:] = tool_result_budget(messages)    # L3: 大结果先落盘
        messages[:] = snip_compact(messages)          # L1: 裁中间
        messages[:] = micro_compact(messages)         # L2: 旧结果占位

        # === 还不够？LLM 摘要 ===
        if estimate_size(messages) > CONTEXT_LIMIT:
            print("[auto compact]")
            messages[:] = compact_history(messages, client, model)

        # === LLM 调用 + 应急兜底 ===
        try:
            response = client.messages.create(
                model=model,
                messages=messages,
                tools=tools,
                max_tokens=8000,
            )
            reactive_retries = 0  # 成功就重置
        except Exception as e:
            err_msg = str(e).lower()
            is_ptl = ("prompt_too_long" in err_msg
                      or "too many tokens" in err_msg)
            if is_ptl and reactive_retries < MAX_REACTIVE_RETRIES:
                print("[reactive compact]")
                messages[:] = reactive_compact(messages, client, model)
                reactive_retries += 1
                continue
            raise  # 超过重试上限，抛出

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return

        # === 工具执行 ===
        results = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue

            # 手动 compact 工具：模型主动触发摘要
            if block.name == "compact":
                messages[:] = compact_history(messages, client, model)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "[Compacted. Conversation history summarized.]"
                })
                messages.append({"role": "user", "content": results})
                break  # 结束当前 turn，用压缩后上下文开新轮

            # 普通工具调用
            handler = TOOL_HANDLERS.get(block.name)
            output = handler(**block.input) if handler else f"Unknown: {block.name}"
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(output)
            })
        else:
            messages.append({"role": "user", "content": results})
            continue
        # compact 触发时走这里
        continue
```

**验证标准**：
- [ ] 正常对话路径不触发任何压缩
- [ ] 超阈值时触发 auto compact
- [ ] API 报错时触发 reactive compact，最多重试 1 次
- [ ] 手动 compact 工具能正常触发并结束当前 turn
- [ ] 成功调用后 reactive_retries 重置

---

### P4: 测试套件、熔断器、监控

**目标**：生产就绪。

#### 不变量测试套件

参考 `tests/test_compaction_tool_pairs.py` 的设计，建立**所有压缩层共享的不变量测试**：

```python
def assert_no_orphan_tool_results(testcase, messages):
    """核心不变量：每个 tool_result 前必须有对应的 tool_use"""
    for idx, msg in enumerate(messages):
        content = msg.get("content")
        if (msg.get("role") != "user"
                or not isinstance(content, list)):
            continue
        if not any(isinstance(b, dict) and b.get("type") == "tool_result"
                   for b in content):
            continue
        # 该消息有 tool_result，前一条必须是 tool_use
        testcase.assertGreater(idx, 0)
        testcase.assertTrue(
            _message_has_tool_use(messages[idx - 1]),
            f"Orphan tool_result at index {idx}: {messages}"
        )
```

**必测场景**：
- [ ] `snip_compact` 头部边界保护（保留 head 末尾是 tool_use → 后续 tool_result 纳入 head）
- [ ] `snip_compact` 尾部边界保护（切到 tool_result → 前移保留 tool_use）
- [ ] `reactive_compact` 尾部边界保护
- [ ] `reactive_compact` 摘要只覆盖旧历史，不含被保留的尾部
- [ ] `reactive_compact` 边界跨越 tool_use/tool_result 对时，摘要范围正确收缩

#### 熔断器

```python
class AutoCompactCircuitBreaker:
    """连续失败 N 次后停止，防止死循环烧 API"""
    def __init__(self, max_failures=MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES):
        self.failures = 0
        self.max = max_failures

    def try_call(self, fn, *args, **kwargs):
        if self.failures >= self.max:
            raise RuntimeError(
                f"AutoCompact circuit breaker open: "
                f"{self.failures} consecutive failures"
            )
        try:
            result = fn(*args, **kwargs)
            self.failures = 0  # 成功重置
            return result
        except Exception:
            self.failures += 1
            raise
```

#### 监控埋点

记录以下指标，用于调参：

| 指标 | 用途 |
|------|------|
| 每层压缩触发频率 | 判断哪层是瓶颈，调整阈值 |
| 压缩前后 size 变化 | 评估压缩效率 |
| reactive 触发次数 | 阈值是否过低 |
| compact_history 失败次数 | LLM 摘要稳定性 |
| 平均会话长度 | 验证无限会话目标 |

---

## 5. 关键参数对照表

| 参数 | 推荐值 | CC 源码值 | 说明 |
|------|--------|----------|------|
| `CONTEXT_LIMIT` | 50000 字符 | `contextWindow - maxOutputTokens - 13000` token | 粗略估算用字符数，生产换精确 tokenizer |
| `KEEP_RECENT_TOOL_RESULTS` | 3 | time-based 60 分钟 | micro_compact 保留数 |
| `KEEP_RECENT_MESSAGES` | 50 | HISTORY_SNIP feature gate | snip_compact 触发阈值 |
| `PERSIST_THRESHOLD` | 30000 字符 | — | 单条结果落盘阈值 |
| `TOOL_RESULT_BUDGET` | 200000 字符 | 200000 字符 (`toolLimits.ts:49`) | 单消息 tool_result 总量上限 |
| `MAX_REACTIVE_RETRIES` | 1 | 更精细分级 | 应急重试上限 |
| `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES` | 3 | 3 (`autoCompact.ts:70`) | 熔断阈值 |
| 摘要 `max_tokens` | 2000 | 20000 | 摘要输出长度上限 |

**调参建议**：先用推荐值跑通，然后根据 P4 监控数据调整：
- reactive 频繁触发 → 提高 `CONTEXT_LIMIT` 或降低 `KEEP_RECENT_*`
- 单条大结果频繁 → 降低 `PERSIST_THRESHOLD`
- 摘要丢失关键信息 → 提高 `max_tokens` 或优化摘要 prompt

---

## 6. 风险与取舍

### 已知简化（相对 Claude Code）

| 简化项 | 教学版做法 | CC 真实做法 | 何时需要补齐 |
|--------|----------|------------|-------------|
| token 估算 | 字符数 // 4 | 精确 tokenizer | 上下文窗口紧张时 |
| `read_file` 处理 | 一视同仁清掉 | 维护 `readFileState`，未变化返回 `FILE_UNCHANGED_STUB`，compact 后按预算恢复最近 5 个文件 | 频繁重读同一文件时 |
| 后压缩恢复 | 无 | 自动重读最近文件、计划、agent/skill/tool | 用户偏好/约束丢失成问题时 |
| 摘要 prompt | 5 类信息 | 9 部分 + `<analysis>`/`<summary>` 双标签，首尾双重禁止调工具 | 摘要质量不稳定时 |
| micro_compact 触发 | 按位置 | time-based 60 分钟 + cached 计数双路径 | 工具调用模式不均匀时 |
| `contextCollapse` | 未实现 | 独立上下文管理系统 | 已有 session memory 后 |
| `sessionMemoryCompact` | 未实现 | compact 前先用 session memory 做轻量摘要（免调 LLM） | 已有 session memory 后 |

### 主要风险

1. **配对保护失败** → API 报错，会话中断
   - 缓解：完整的不变量测试套件，每次改动都跑

2. **摘要丢失关键信息** → agent 行为偏离用户意图
   - 缓解：支持 `focus` 参数让模型指定保留重点；优化摘要 prompt

3. **transcript 落盘无检索** → 历史信息实际不可恢复
   - 缓解：MVP 可接受，后续接 RAG 检索或加 `read_transcript` 工具

4. **token 估算不准** → 压缩触发过早或过晚
   - 缓解：先按字符数跑通，生产环境换 `anthropic.count_tokens` 或 `tiktoken`

5. **压缩顺序写死** → 改动时容易破坏不变量
   - 缓解：在 `agent_loop` 中明确注释顺序原因，改动时强制跑全量测试

---

## 7. 后续扩展（v2）

按优先级排序：

1. **精确 token 计数**：替换 `estimate_size` 为 `anthropic.count_tokens` 或 `tiktoken`
2. **read_file 恢复机制**：compact 后自动重读最近 N 个文件（参考 CC 的 5 文件 / 50K token 预算）
3. **session memory 集成**：compact 前先做免 LLM 的轻量摘要（对应 s09）
4. **transcript 检索工具**：让 agent 主动检索历史 transcript
5. **摘要 prompt 强化**：加 `<analysis>`/`<summary>` 双标签，首尾禁止调工具
6. **`contextCollapse`**：独立的上下文管理子系统
7. **prompt cache 优化**：micro_compact 不破坏 cache 边界

---

## 8. 验收清单

实现完成后，用以下场景端到端验证：

- [ ] 连续读 20 个大文件，不报 `prompt_too_long`
- [ ] 单次 `bash` 输出 500KB，触发 L3 落盘
- [ ] 100 轮对话后，触发 L1 snip
- [ ] tool_result 累积超 3 条，触发 L2 micro
- [ ] 总量超 50K 字符，触发 L4 compact_history
- [ ] 强制构造超大上下文，触发 reactive_compact 并重试成功
- [ ] 模型主动调用 `compact` 工具，能正常压缩并开新 turn
- [ ] 所有压缩层输出无孤立 tool_result
- [ ] 连续失败 3 次后熔断器打开，不再重试
- [ ] reactive 重试 1 次后仍失败，抛出异常而非无限循环
