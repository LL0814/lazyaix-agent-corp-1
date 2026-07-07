# 记忆多条原子抽取实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把记忆抽取从“一段话最多一条记忆”升级为“一段自然语言可自动抽取多条原子记忆”，并为每条记忆补充可审计时间元数据。

**Architecture:** 保留现有 `extract(text) -> MemoryClassification` 兼容接口，新增 `extract_many(text) -> list[MemoryClassification]` 批量接口。`MemoryOutboxWorker` 优先使用批量接口，逐条写入向量库/SQLite summary，并在 metadata 与 outbox `worker_result` 中记录抽取时间、outbox 时间、可选事件时间。

**Tech Stack:** Python、Pydantic、SQLite、Qdrant、Ollama bge-m3、DeepSeek OpenAI-compatible API、pytest。

## Global Constraints

- 所有新增报告和计划使用中文。
- 先写失败测试，再写实现。
- 保持旧接口兼容，避免破坏已有测试桩。
- 不提交 `.idea` 文件，不提交 `.env` 或任何密钥。

---

### Task 1: 批量抽取接口

**Files:**
- Modify: `memory/models.py`
- Modify: `memory/extractors.py`
- Test: `tests/test_memory_deepseek_extractor.py`

**Interfaces:**
- Consumes: `MemoryClassification`
- Produces: `MemoryCandidateExtractor.extract_many(text: str) -> list[MemoryClassification]`

- [ ] **Step 1: Write the failing test**

添加测试 `test_deepseek_extractor_parses_multiple_items_from_batch_json`，DeepSeek 返回 `{"items": [...]}` 时应该解析出 semantic、episodic、procedural、summary 四条记忆。

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_memory_deepseek_extractor.py::test_deepseek_extractor_parses_multiple_items_from_batch_json -q`
Expected: FAIL because `DeepSeekMemoryExtractor.extract_many` does not exist.

- [ ] **Step 3: Write minimal implementation**

在 `memory.extractors` 中给协议、规则 extractor、DeepSeek extractor 增加 `extract_many()`；DeepSeek 解析 JSON 对象时兼容旧单对象与新 `items` 数组。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_memory_deepseek_extractor.py::test_deepseek_extractor_parses_multiple_items_from_batch_json -q`
Expected: PASS.

### Task 2: Worker 多条落库和时间元数据

**Files:**
- Modify: `memory/worker.py`
- Test: `tests/test_memory_outbox_worker.py`

**Interfaces:**
- Consumes: `extract_many(text: str) -> list[MemoryClassification]`
- Produces: outbox `worker_result.items` and memory record metadata keys `extracted_at`, `source_event_created_at`, `observed_at`, `source_event_id`

- [ ] **Step 1: Write the failing test**

添加测试 `test_process_outbox_remembers_multiple_items_with_time_metadata`，一条 outbox 事件应该生成多条 active records 和一条 summary，且每条 record metadata 带时间。

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_memory_outbox_worker.py::test_process_outbox_remembers_multiple_items_with_time_metadata -q`
Expected: FAIL because worker only handles one classification.

- [ ] **Step 3: Write minimal implementation**

worker 对每个 classification 分别处理；summary 进入 `update_summary()`；非 summary 进入 `remember()`；outbox 只标记一次 processed，`worker_result.items` 记录每条结果。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_memory_outbox_worker.py::test_process_outbox_remembers_multiple_items_with_time_metadata -q`
Expected: PASS.

### Task 3: 回归验证和中文报告

**Files:**
- Add: `docs/superpowers/reports/2026-07-07-memory-multi-item-extraction.md`

**Interfaces:**
- Consumes: 全部 memory 测试和全量测试结果。
- Produces: 中文说明、人工验证方法、隐式测试提示词。

- [ ] **Step 1: Run targeted tests**

Run: `uv run pytest tests/test_memory_deepseek_extractor.py tests/test_memory_outbox_worker.py -q`
Expected: PASS.

- [ ] **Step 2: Run full tests**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 3: Write report**

报告说明接口位置、功能变化、数据库验证方法、全新的隐式测试提示词。

- [ ] **Step 4: Commit**

Commit only changed memory/tests/docs files, excluding `.idea`.
