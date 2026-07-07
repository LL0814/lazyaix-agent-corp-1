# 记忆多条原子抽取阶段报告

## 本次完成的功能

这次把记忆抽取从“一段话最多生成一条记忆”升级为“一段自然语言可以自动生成多条原子记忆”。

现在一段用户输入可以同时抽取：

- `semantic`：稳定偏好、事实、项目背景。
- `episodic`：一次性事件、历史经历、某次反馈。
- `procedural`：以后应该怎么做的流程规则。
- `summary`：对当前长期状态的压缩摘要。

并且每条落库的普通记忆都会带时间元数据：

- `created_at`：记忆记录创建时间，写在 `memory_records.created_at`。
- `updated_at`：记忆记录更新时间，写在 `memory_records.updated_at`。
- `extracted_at`：worker 抽取这条记忆的时间，写在 `metadata_json`。
- `source_event_created_at`：outbox 事件创建时间，写在 `metadata_json`。
- `observed_at`：如果用户原话明确说了事件发生时间，AI 可以抽出来；没有明确时间就是 `null`。

## 改动位置

- `memory/models.py`
  - `MemoryClassification` 新增 `observed_at: str | None`。

- `memory/extractors.py`
  - `MemoryCandidateExtractor` 新增 `extract_many(text: str) -> list[MemoryClassification]`。
  - `RuleBasedMemoryExtractor.extract_many()` 兼容旧规则分类，返回单条列表。
  - `DeepSeekMemoryExtractor.extract_many()` 支持解析新的 JSON 格式：`{"items": [...]}`。
  - `DeepSeekMemoryExtractor.extract()` 保留旧接口，返回第一条结果，避免旧调用方崩。
  - DeepSeek system prompt 已改成要求“一段话可抽取多条原子记忆，最多 8 条”。

- `memory/worker.py`
  - worker 优先调用 `extract_many()`。
  - 一个 outbox 事件可以生成多条 `memory_records`。
  - `summary` 类型仍然写入 `memory_summaries`，不会进 Qdrant。
  - outbox 的 `worker_result.items` 会记录每条 item 的 kind、content、confidence、importance、reason、时间信息、memory_id 或 summary_updated。
  - 兼容旧字段：单条记忆时，`worker_result.kind/content/memory_id` 仍然保留。

- `tests/test_memory_deepseek_extractor.py`
  - 新增批量 JSON items 解析测试。
  - 验证 `observed_at` 不会被吞掉。

- `tests/test_memory_outbox_worker.py`
  - 新增一条 outbox 生成 semantic、episodic、procedural、summary 的完整 worker 测试。
  - 验证每条普通记忆的 metadata 都带 `extracted_at`、`source_event_created_at`、`observed_at`。

## 已验证

已运行：

```bash
uv run pytest tests/test_memory_deepseek_extractor.py tests/test_memory_outbox_worker.py -q
```

结果：

```text
11 passed
```

已运行：

```bash
uv run pytest -q
```

结果：

```text
126 passed
```

## 人工验证方式

先启动对话：

```bash
uv run python loop.py
```

输入一条自然语言，不要显式说“记住什么类型”。然后查看 SQLite：

```bash
sqlite3 .memory/memory.sqlite3 "
select
  kind,
  content,
  created_at,
  json_extract(metadata_json, '$.extracted_at') as extracted_at,
  json_extract(metadata_json, '$.source_event_created_at') as source_event_created_at,
  json_extract(metadata_json, '$.observed_at') as observed_at
from memory_records
order by created_at desc
limit 20;
"
```

查看摘要：

```bash
sqlite3 .memory/memory.sqlite3 "
select content, version, created_at, updated_at
from memory_summaries
order by updated_at desc
limit 5;
"
```

查看 outbox 批量处理结果：

```bash
sqlite3 .memory/memory.sqlite3 "
select status, attempts, json_extract(payload_json, '$.worker_result.processed_items') as processed_items, updated_at
from memory_outbox
order by updated_at desc
limit 10;
"
```

如果 `.env` 里配置了 `MEMORY_DB_PATH`，请把命令里的 `.memory/memory.sqlite3` 换成实际路径。

## 隐式测试提示词

这些话都不要说“请记住”，直接当普通对话输入。

1. 周二晚上我一般不适合处理合同审核，去年 12 月那次就是因为太晚看漏了续费条款。以后如果让我看合同，先帮我确认续费和自动扣款。

2. 我最近给客户做路演时更喜欢先讲风险边界，再讲收益空间。上周五给华东客户讲反了，现场问答有点乱。

3. 以后帮我排项目周会时，尽量避开每天 11 点半到 13 点。今天中午那个会让我没法按时吃饭，下午状态明显下降。

4. 我在供应商评估里更看重售后响应速度，不想只看报价。6 月底那个低价供应商响应太慢，差点影响上线。

5. 如果我让你整理招聘候选人，先把稳定性和跨团队沟通能力放前面。昨天那个候选人技术可以，但协作经历太薄。

输入后可以追问：

```text
你基于长期记忆，分别说说我在合同、路演、会议、供应商、招聘方面有哪些偏好和流程习惯？
```

如果抽取正常，应该能看到它不是只记一条，而是从每句话里拆出偏好、历史事件、以后流程和摘要。
