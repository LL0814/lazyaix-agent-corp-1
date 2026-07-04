让我重新精读这两层的核心代码，确保讲解准确。

以下是对四层压缩的完整拆解，重点对比第三层（ContextCollapse）和第四层（AutoCompact）的摘要差异。

---

## 一、四层压缩全景图

```
上下文利用率增长
│
│  70% ──→ SnipCompact（第1层）本地零成本裁剪
│  75% ──→ ContextCollapse（第3层）投影层折叠 ← 重点
│  85% ──→ AutoCompact（第4层）LLM整体压缩 ← 重点
│  50% ──→ MicroCompact（第2层）持续轻量清理
│
└──────────────────────────────────────────→ 时间
```

| 层级 | 名称 | 成本 | 操作对象 | 是否修改原始消息 |
|------|------|------|----------|------------------|
| 1 | **SnipCompact** | 零 | 原始消息列表 | ✅ 直接删除 |
| 2 | **MicroCompact** | 零 | 原始消息列表 | ✅ 清空旧工具结果 |
| 3 | **ContextCollapse** | 中（LLM） | **模型可见投影** | ❌ **不修改原始** |
| 4 | **AutoCompact** | 高（LLM） | 原始消息列表 | ✅ **永久替换** |

---

## 二、第三层 vs 第四层：核心架构差异

这是理解两者摘要差异的前提。它们的**架构定位完全不同**：

### 第三层 ContextCollapse：「投影层」设计

```
原始消息列表（完整保留，用于UI展示和Session恢复）
    │
    │  projectCollapsedView()  ← 根据CollapseSpan状态投影
    ↓
模型可见的消息列表（老消息被替换为context_summary）
```

**关键特点**：
- 原始消息列表 **永远不被修改**
- 用 `CollapseSpan` 记录"哪段消息被什么摘要替换了"
- 每次调用模型前，通过 `projectCollapsedView()` 动态生成模型可见列表
- 可以**累积多个 span**，每个 span 对应一段被折叠的区间
- 跨回合复用 `ContextCollapseState`（span 列表）

```typescript
// 核心数据结构
type CollapseSpan = {
  id: string
  startMessageId: string      // 区间起点消息id
  endMessageId: string        // 区间终点消息id
  messageIds: string[]        // 区间内所有消息id
  summary: string             // LLM生成的摘要内容
  tokensBefore: number
  tokensAfter: number
  status: 'staged' | 'committed'  // 暂存或已提交
}

type ContextCollapseState = {
  spans: CollapseSpan[]       // 跨回合复用的span列表
  enabled: boolean
  consecutiveFailures: number
}
```

### 第四层 AutoCompact：「永久性替换」设计

```
原始消息列表
    │
    │  compactConversation()  ← 直接修改
    ↓
新消息列表 = System + 摘要 + 最近尾部消息
```

**关键特点**：
- 直接修改消息列表，**原始消息永久丢失**（但会写入 compact boundary 到 session）
- 一次性操作，不累积
- 从尾部保留固定量的消息（`MAX_KEEP_TOKENS = 40,000`），其余全部压缩
- 触发后重置 `ContextCollapseState`（因为消息结构已变，旧 span 不再有效）

---

## 三、第三层 vs 第四层：摘要的核心差异

### 差异 1：摘要范围

| | **ContextCollapse（第三层）** | **AutoCompact（第四层）** |
|---|---|---|
| **摘要什么** | 只摘要**一段较老的消息区间**（span） | 摘要**最近尾部之前的所有历史消息** |
| **范围大小** | 小（通常 5-15 条消息） | 大（可能 20-100 条消息） |
| **比喻** | 把笔记本中**某一页**折起来 | 把笔记本中**前面所有页**撕掉，只留最后几页 |

**ContextCollapse**：
```typescript
// 找到一段"安全连续区间"（不包含文件编辑、错误等）
const candidate = findCollapseCandidate(messages, state, options)
// 只摘要这小段
const summaryPrompt = buildContextCollapseSummaryPrompt(
  messagesToCollapseText(candidate.messages)  // ← 只传入这段消息
)
```

**AutoCompact**：
```typescript
// 从尾部保留40K tokens，其余全部压缩
const boundary = findRetentionBoundary(messages)
const messagesToCompress = messages.slice(1, boundary)  // ← 前面所有消息
const summaryPrompt = buildCompactSummaryPrompt(messagesToText(messagesToCompress))
```

---

### 差异 2：摘要格式（Prompt 设计）

这是**最关键的区别**：

**ContextCollapse 的 Prompt**（`buildContextCollapseSummaryPrompt`）：

```
You are creating a local context-collapse summary for an AI coding session.
The summary will replace only this older message span in the model-visible context.
The original transcript remains preserved outside the model-visible projection.

Produce the final summary in <summary> tags.

Preserve:
- User intent and active goals
- Completed tasks and current state
- Important decisions and constraints
- Tool calls and tool results that still matter
- File reads/writes and code changes, with paths, function names, config names, and commands
- Errors, failures, warnings, and exact messages when relevant
- TODOs, uncertainty, follow-up constraints, and anything still relevant later

Rules:
- Do not invent facts or outcomes
- Do not omit critical paths, function names, configuration keys, file paths, or error text
- Keep it concise, but prefer specificity over vague compression
- This is not a full conversation compact; summarize only the provided span
```

**关键指令**：
- `"summarize only the provided span"` — 只摘要提供的这一段，不是整个对话
- `"prefer specificity over vague compression"` — **宁可具体，不要模糊压缩**
- `"Do not omit critical paths, function names, configuration keys, file paths, or error text"` — **不要省略关键技术细节**

**输出格式**：自由文本，在 `<summary>` 标签内，没有固定章节结构。

---

**AutoCompact 的 Prompt**（`buildCompactSummaryPrompt`）：

```
You are summarizing a conversation for context compression.
Produce a structured summary in <summary> tags.

Sections:
1. Primary Request — What the user asked for
2. Key Decisions — Important choices made
3. Files Modified — Which files were changed and why
4. Errors Encountered — Problems hit and how they were resolved
5. Current State — Where things stand right now
6. Pending Tasks — What still needs to be done

Rules:
- Be concise but preserve actionable details (file paths, command outputs, error messages)
- Use <analysis> tags as scratchpad, then <summary> tags for final output
- The summary will replace all messages before the recent tail
```

**关键指令**：
- `"Sections: 1. Primary Request ... 6. Pending Tasks"` — **强制六段式结构**
- `"The summary will replace all messages before the recent tail"` — 摘要将替换所有旧消息
- `"Use <analysis> tags as scratchpad"` — 允许模型先思考，再输出最终摘要

**输出格式**：**结构化六段式**，每个部分有明确标题。

---

### 差异 3：为什么格式不同？设计意图

| **ContextCollapse** | **AutoCompact** |
|---|---|
| 摘要只是一段**局部历史**，模型仍能看到其他未折叠的部分 | 摘要必须**覆盖整段历史**，因为其他旧消息都消失了 |
| 需要保留**具体技术细节**（函数名、路径），因为模型可能随时需要引用 | 需要**结构化概览**，让模型快速理解"之前发生了什么" |
| 格式自由，不限制模型，让模型根据内容灵活组织 | 格式强制，确保每次压缩产出一致，便于解析和验证 |
| 定位：**"这段消息说了什么"** | 定位：**"整个对话的进展状态"** |

---

### 差异 4：摘要的"寿命"和"叠加"

| | **ContextCollapse** | **AutoCompact** |
|---|---|---|
| **可叠加性** | ✅ **可以累积多个 span**，每个 span 对应不同区间的摘要 | ❌ 一次性操作，不累积 |
| **跨回合复用** | `CollapseSpan` 状态跨回合复用，每回合可能新增 1-2 个 span | 每次触发都是全新压缩，旧 span 被重置 |
| **原始消息保留** | 完整保留在原始列表中，UI 可以展示 | 写入 `compact_boundary` 到 session，通过 `loadTranscript` 重建 |
| **摘要的摘要** | 可能出现：一个新的 span 折叠了包含旧 `context_summary` 的区间 | 不会出现，因为一次性替换到底 |

**ContextCollapse 的累积效果**：

```
原始消息：[M1, M2, M3, M4, M5, M6, M7, M8, M9, M10]
          │          │              │              │
          │          span A        span B         保留区
          │          (M2-M4)       (M5-M7)
          │          ↓            ↓
投影后：  [M1, summary_A, summary_B, M8, M9, M10]
```

**AutoCompact 的效果**：

```
原始消息：[M1, M2, M3, M4, M5, M6, M7, M8, M9, M10]
          │                              │
          │  压缩区（M1-M7）               │ 保留区（M8-M10）
          │  ↓                             │
          │  被替换为一个大摘要             │
          │                                │
压缩后：  [System, summary_all, M8, M9, M10]
```

---

### 差异 5：触发条件和执行频率

| | **ContextCollapse** | **AutoCompact** |
|---|---|---|
| **触发阈值** | 利用率 ≥ 75% | 利用率 ≥ 85% 或 blocked |
| **目标利用率** | 降到 65% | 降到 65%（隐式） |
| **每回合执行次数** | 最多 2 个 span（`MAX_SPANS_PER_PASS = 2`） | 只在第 0 步执行一次 |
| **执行成本** | 中（每次新增 span 调用一次 LLM） | 高（一次调用处理大量消息） |
| **失败策略** | 连续 3 次失败自动禁用 | 连续 3 次失败自动禁用 |

**为什么 ContextCollapse 可以每回合执行多次，而 AutoCompact 只执行一次？**

- ContextCollapse 每次只处理一小段（一个候选区间），成本低
- AutoCompact 需要处理大量消息（所有旧消息），成本高，且可能触发 `max_tokens`
- 如果 AutoCompact 每步都触发，会严重拖慢 Agent 循环

---

## 四、四层压缩的触发顺序（Agent 循环中）

```typescript
// 每回合开始
for (let step = 0; step < maxSteps; step++) {
  
  // 第1层：SnipCompact（零成本，每回合只一次）
  if (!snippedThisTurn) {
    const snipResult = await snipCompactConversation(...)
    if (snipResult.didSnip) messages = snipResult.messages
  }
  
  // 第2层：MicroCompact（零成本，持续清理）
  messages = microcompact(messages, model)
  
  // 第3层：ContextCollapse（投影层，可多次）
  const collapseResult = await applyContextCollapseIfNeeded(
    messages, model, adapter, collapseState
  )
  let modelMessages = collapseResult.messages  // 投影后的列表
  
  // 第4层：AutoCompact（只在第0步，critical/blocked时）
  if (step === 0) {
    const stats = computeContextStats(modelMessages, model)
    if (stats.warningLevel === 'critical' || stats.warningLevel === 'blocked') {
      const result = await autoCompact(modelMessages, model, adapter)
      if (result) {
        messages = result.messages
        modelMessages = messages
        collapseState = createContextCollapseState()  // 重置！
      }
    }
  }
  
  // 调用模型
  const next = await adapter.next(modelMessages)
}
```

---

## 五、一句话总结差异

| | **ContextCollapse（第三层）** | **AutoCompact（第四层）** |
|---|---|---|
| **一句话** | 把笔记本的**某一页折起来**，只给模型看摘要，但那一页还在本子里 | 把笔记本的**前面所有页撕掉**，只保留摘要和最后几页 |
| **摘要格式** | 自由文本，强调具体技术细节（函数名、路径、错误） | 结构化六段式，强调整体进展状态 |
| **操作对象** | 模型可见的**投影** | 原始消息列表的**永久替换** |
| **可叠加性** | ✅ 多个 span 可叠加 | ❌ 一次性，不叠加 |
| **触发频率** | 每回合最多 2 次 | 只在回合开始时 1 次 |

---

## 六、为什么要设计两种 LLM 压缩？

MiniCode 的设计者意识到：**单层 LLM 压缩无法同时满足"精确细节保留"和"全局状态概览"两种需求**。

- **ContextCollapse** 解决的是"投影层"问题：原始消息还在，只是模型看不见。因此摘要需要**精确到具体细节**（函数名、文件路径），因为模型随时可能需要引用这些细节。
- **AutoCompact** 解决的是"全局概览"问题：所有旧消息被一次性替换，模型必须能从摘要中**重建对整个对话的理解**。因此需要结构化六段式，确保"用户要什么、做了什么、还有什么没做"一目了然。

两者是**互补关系**：ContextCollapse 先逐步折叠局部细节，AutoCompact 在危急时刻做全局兜底。