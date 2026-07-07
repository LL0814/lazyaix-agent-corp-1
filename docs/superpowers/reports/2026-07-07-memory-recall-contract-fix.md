# 合同记忆未召回修复报告

## 现象

用户连续输入五类隐式测试句后，再问：

```text
你基于长期记忆，分别说说我在合同、路演、会议、供应商、招聘方面有哪些偏好和流程习惯？
```

模型回答中路演、会议、供应商、招聘都召回了，但合同显示“暂无相关长期记忆”。

## 根因

实际检查 SQLite 后发现，合同内容并不是没有入库，而是存在三个问题：

1. worker 以前把 `Q: 用户输入\nA: 模型回复` 整段送给抽取器。
   - 当 AI 抽取器失败并回退到规则抽取时，会把整段 Q/A 当成一条 procedural 记忆。
   - 这导致记忆内容很长，含有大量“已记住”等模型回复噪声。

2. “你基于长期记忆……”这种元问题也被规则抽取器当成偏好记忆写入。
   - 这会产生“合同暂无相关长期记忆”这类自引用污染记录。
   - 后续检索时污染记录可能排在真实合同记忆前面。

3. Agent 默认只召回 `MEMORY_PROMPT_TOP_K=5` 条长期记忆。
   - 多领域问题很容易超过 5 条。
   - 即使合同已经入库，也可能因为排序被挤出 prompt。

## 修复内容

- `memory/service.py`
  - outbox payload 新增 `input` 和 `response` 字段。
  - 保留原来的 `text` 字段，兼容旧事件。
  - `Memory.search()` 增加 SQLite 关键词兜底召回。
  - `Memory.search()` 过滤旧的长期记忆问答污染记录。
  - 新增 `_query_terms()`，支持合同、会议、住宿、招聘等简单领域词扩展。

- `memory/worker.py`
  - 抽取文本优先使用 `payload["input"]`。
  - 旧事件没有 `input` 时才回退到 `payload["text"]`。

- `memory/classifier.py`
  - 规则抽取器跳过“基于长期记忆 / 你还记得 / 长期记忆中”等元问题。
  - `请记住`、`记为` 这类显式存储语义不受影响。

- `memory/backends/sqlite_store.py`
  - 新增 `search_records_by_terms()`，用于向量召回漏掉时的本地关键词兜底。

- `agent.py`
  - 默认长期记忆召回数量从 5 提高到 12。
  - prompt 构造时跳过长期记忆元问题的最近历史，避免旧错误回答继续污染下一轮。

## 新增测试

- `tests/test_memory_outbox_worker.py`
  - 验证 worker 只把用户原话送给抽取器，不带助手回复。
  - 验证长期记忆元问题不会被写入 records。

- `tests/test_memory_service_semantic.py`
  - 验证向量检索漏掉合同时，SQLite 关键词兜底能补回。
  - 验证旧的“长期记忆问答污染”不会进入搜索结果。

- `tests/test_memory_integration_with_agent_contract.py`
  - 验证默认 prompt 能容纳多领域长期记忆。
  - 验证 prompt 会跳过“合同暂无相关长期记忆”这类旧历史。

## 验证结果

已运行：

```bash
uv run pytest tests/test_memory_integration_with_agent_contract.py tests/test_memory_outbox_worker.py tests/test_memory_service_semantic.py -q
```

结果：

```text
20 passed
```

已运行：

```bash
uv run pytest -q
```

结果：

```text
132 passed
```

真实本地 prompt 检查结果：

```text
has_contract_memory= True
has_bad_no_contract= False
```

说明合同长期记忆已经进入 prompt，旧的“暂无合同”错误回答不再进入 prompt。

## 人工复测

重新启动 loop：

```bash
uv run python loop.py
```

然后直接问：

```text
你基于长期记忆，分别说说我在合同、路演、会议、供应商、招聘方面有哪些偏好和流程习惯？
```

预期结果：

- 合同部分应该能说出：
  - 周二晚上不适合处理合同审核。
  - 以前因为太晚看漏过续费条款。
  - 以后看合同时先确认续费和自动扣款。
- 不应该再回答“合同暂无相关长期记忆”。
