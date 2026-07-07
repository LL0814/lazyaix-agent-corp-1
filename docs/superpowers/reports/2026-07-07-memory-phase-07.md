# 第 7 阶段报告：remember、search、forget 语义记忆闭环

## 本阶段目标

在前面已有的 SQLite、脱敏、embedding provider 和 Qdrant index 基础上，打通语义长期记忆的最小闭环：`remember()` 写入长期记忆，`search()` 按默认 tenant/user/project filter 检索，`forget()` 软删除 SQLite 记录并删除向量索引。

## 本阶段改动

- 新增 `memory/retrieval.py`，提供搜索结果综合评分 helper。
- 扩展 `memory/backends/sqlite_store.py`：
  - 新增 `memory_sources` 表。
  - 新增 `memory_records` 表。
  - 新增 source/record 插入、读取、列表和软删除方法。
- 修改 `memory/service.py`：
  - `Memory.__init__` 支持注入 `embedding_provider` 和 `vector_index`。
  - 新增 `Memory.remember()`。
  - 新增 `Memory.search()`。
  - 新增 `Memory.forget()`。
- 新增 `tests/test_memory_service_semantic.py`，使用 fake embedding 和 fake index 覆盖闭环。

## 新增文件

- `memory/retrieval.py`
- `tests/test_memory_service_semantic.py`
- `docs/superpowers/reports/2026-07-07-memory-phase-07.md`

## 修改文件

- `memory/backends/sqlite_store.py`
- `memory/service.py`

## 公开接口

- `SQLiteMemoryStore.insert_source(source: SourceRef) -> str`
- `SQLiteMemoryStore.insert_record(record: MemoryRecord) -> str`
- `SQLiteMemoryStore.get_record(memory_id: str) -> MemoryRecord | None`
- `SQLiteMemoryStore.list_records(memory_ids: list[str]) -> list[MemoryRecord]`
- `SQLiteMemoryStore.mark_deleted(memory_id: str) -> bool`
- `Memory.remember(content, kind, scope, metadata, source) -> str`
- `Memory.search(query, top_k, scope, project_id, include_sources) -> list[MemorySearchResult]`
- `Memory.forget(memory_id, reason) -> bool`

## 存储结构

SQLite 保存语义长期记忆的两张表：

- `memory_sources`：保存来源信息，包括 `source_id`、`source_type`、`source_ref`、`excerpt`、`metadata_json`、`created_at`。
- `memory_records`：保存长期记忆正文和治理字段，包括 `tenant_id`、`user_id`、`project_id`、`scope`、`kind`、`content`、`metadata_json`、`status`、`confidence`、`importance`、`sensitivity`、`source_id`、时间戳等。

Qdrant 保存向量和 payload。payload 字段由第 6 阶段定义，包括 `memory_id`、`tenant_id`、`user_id`、`project_id`、`scope`、`kind`、`status`、`confidence`、`importance`、`sensitivity`、时间戳等。

## Search 过滤逻辑

`Memory.search()` 默认加入以下 filter：

- `tenant_id = self.config.tenant_id`
- `user_id = self.config.user_id`
- `project_id = project_id or self.config.project_id`
- `status = active`

如果传入 `scope`，会额外加入 `scope` filter。Qdrant 返回候选后，再从 SQLite 读取 record，并过滤掉 SQLite 中已经 `deleted` 的记录。

## Forget 逻辑

`Memory.forget()` 做三件事：

- SQLite `memory_records.status` 软删除为 `deleted`。
- 调用 vector index 删除对应 memory point。
- 写入 `memory.record.forgotten` 审计日志，payload 中记录删除原因。

因此即使向量索引未来出现延迟，`search()` 仍会用 SQLite 的 active 状态做二次过滤，避免 deleted 记忆再次出现。

## 自动验证

RED 命令：

```bash
uv run pytest tests/test_memory_service_semantic.py -v
```

RED 结果：

```text
3 failed in 0.07s
```

失败原因：

- `Memory.__init__()` 尚不支持 `embedding_provider` 注入。

GREEN 命令：

```bash
uv run pytest tests/test_memory_service_semantic.py -v
```

GREEN 结果：

```text
3 passed in 0.38s
```

回归测试命令：

```bash
uv run pytest tests/test_memory_interface.py tests/test_memory_sqlite_store.py tests/test_memory_audit_outbox.py tests/test_memory_redaction_classifier.py tests/test_memory_embeddings.py tests/test_memory_qdrant_store.py tests/test_memory_service_semantic.py -v
```

回归测试结果：

```text
32 passed in 0.56s
```

全量测试命令：

```bash
uv run pytest -q
```

全量测试结果：

```text
87 passed in 0.67s
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

本阶段执行了 fake embedding + fake index 的人工闭环验证：

```text
id True
before ['用户喜欢安静、交通方便的酒店']
forget True
after []
counts kv=0 records=1 sources=1 outbox=0 audit=2 summaries=0
```

说明：

- `remember()` 生成了 `mem_` 前缀的记忆 ID。
- 第一次 `search()` 返回酒店偏好。
- `forget()` 后同样查询不再返回这条记忆。
- SQLite 记录了 1 条 record、1 条 source、2 条 audit。

真实 BGE-M3 + Qdrant 端到端写入未在本阶段自动执行，原因是真实 BGE-M3 会加载大模型，耗时和本地缓存状态不可控。本阶段已通过 fake provider/index 完成服务层闭环验证，并在第 6 阶段确认本机 Qdrant HTTP 服务可达。

## 已知限制

- `include_sources=True` 当前保留参数，但搜索结果暂未回填完整 `SourceRef`。
- 默认真实运行会使用 `BGEM3EmbeddingProvider` 和 `QdrantMemoryIndex`，首次调用 `remember/search` 时可能加载大模型。
- 当前没有 outbox worker 自动把第 3 阶段候选事件转为 `remember()` 写入；本阶段实现的是手动/服务层闭环。
- 当前工作区存在外部生成的 `.idea/` 变更，本阶段没有提交这些文件。

## 后续阶段

下一阶段是第 8 阶段：Summary、Import、Export。
