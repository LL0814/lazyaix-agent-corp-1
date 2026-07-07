# 第 8 阶段报告：Summary、Import、Export

## 本阶段目标

在长期语义记忆闭环之上，增加可编辑 summary、Markdown 导出、JSONL 导出和导入能力，方便企业环境中做人工审查、迁移和备份。

## 本阶段改动

- 新增 `memory/exporter.py`，集中实现 Markdown/JSONL 导出和 JSONL 解析。
- 扩展 `memory/backends/sqlite_store.py`：
  - 新增 `memory_summaries` 表。
  - 新增 `upsert_summary()`、`get_summary()`、`list_active_records()`。
  - `debug_counts()` 现在会返回 `summaries` 数量。
- 修改 `memory/service.py`：
  - 新增 `get_summary()`。
  - 新增 `update_summary()`。
  - 新增 `export()`。
  - 新增 `import_memories()`。
- 新增 `tests/test_memory_import_export_summary.py`，覆盖 summary round trip、Markdown 导出、JSONL 导出导入 round trip。

## 新增文件

- `memory/exporter.py`
- `tests/test_memory_import_export_summary.py`
- `docs/superpowers/reports/2026-07-07-memory-phase-08.md`

## 修改文件

- `memory/backends/sqlite_store.py`
- `memory/service.py`

## 公开接口

- `Memory.get_summary(scope: str = "project") -> str`
- `Memory.update_summary(summary: str, scope: str = "project") -> None`
- `Memory.export(format: str = "markdown") -> str`
- `Memory.import_memories(content: str, source: str = "manual") -> list[str]`

## Summary 使用方式

查看 summary：

```python
from memory import Memory

m = Memory()
print(m.get_summary())
```

编辑 summary：

```python
from memory import Memory

m = Memory()
m.update_summary("用户正在构建企业级本地记忆系统。")
```

summary 按 `tenant_id + user_id + project_id + scope` 唯一保存；重复更新会覆盖内容并递增 version。

## Markdown 导出结构

`Memory.export("markdown")` 输出结构：

```markdown
# Memory Export

## Summary

...

## Durable Memories

- [mem_xxx] memory content
  - kind: semantic
  - scope: project
  - source: src_xxx

## Deleted Memories
```

当前 Markdown 导出只包含 active durable memories。Deleted memories 章节先保留结构，后续可扩展为 tombstone 审计导出。

## JSONL 导入导出限制

- `Memory.export("jsonl")` 每行导出一个 `MemoryRecord` 的 JSON。
- `Memory.import_memories(jsonl)` 会逐行解析，并通过 `remember()` 重建 active record。
- 导入会重新生成 `memory_id` 和 `source_id`，不会保留原始 ID。
- 导入会重新走 redaction、embedding 和 vector index upsert。
- Markdown import 第一版只解析无缩进的 `- content` 或 `- [id] content` 行，会忽略缩进 metadata 行。

## 自动验证

RED 命令：

```bash
uv run pytest tests/test_memory_import_export_summary.py -v
```

RED 结果：

```text
3 failed in 0.32s
```

失败原因：

- `Memory.update_summary()` 尚不存在。
- `Memory.export()` 尚不存在。

GREEN 命令：

```bash
uv run pytest tests/test_memory_import_export_summary.py -v
```

GREEN 结果：

```text
3 passed in 0.38s
```

回归测试命令：

```bash
uv run pytest tests/test_memory_interface.py tests/test_memory_sqlite_store.py tests/test_memory_audit_outbox.py tests/test_memory_redaction_classifier.py tests/test_memory_embeddings.py tests/test_memory_qdrant_store.py tests/test_memory_service_semantic.py tests/test_memory_import_export_summary.py -v
```

回归测试结果：

```text
35 passed in 0.50s
```

全量测试命令：

```bash
uv run pytest -q
```

全量测试结果：

```text
90 passed in 0.75s
```

运行产物检查命令：

```bash
test ! -e .memory && echo 'no .memory residue' || find .memory -maxdepth 2 -type f -print
```

结果：

```text
no .memory residue
```

## 人工验证

本阶段执行了临时 SQLite 人工验证，不留下 `.memory`：

```text
用户正在构建企业级本地记忆系统。
# Memory Export

## Summary

用户正在构建企业级本地记忆系统。

## Durable Memories


## Deleted Memories


kv=0 records=0 sources=0 outbox=0 audit=0 summaries=1
```

说明：

- `update_summary()` 能写入 summary。
- `get_summary()` 能读取同一条 summary。
- `export("markdown")` 输出包含 `# Memory Export` 和 `## Summary`。
- `debug_counts().summaries == 1`。

## 已知限制

- Markdown import 只支持简单 bullet 格式，不是完整 Markdown parser。
- JSONL import 会生成新 ID，不保留原始 memory/source ID。
- `list_active_records()` 当前返回 SQLite 中全部 active records，未按 tenant/project 做导出过滤；后续企业版可以加导出范围参数。
- 当前工作区存在外部生成的 `.idea/` 变更，本阶段没有提交这些文件。

## 后续阶段

下一阶段是第 9 阶段：现有 Agent 契约集成验证。
