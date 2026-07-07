# 第 6 阶段报告：Qdrant 向量索引后端

## 本阶段目标

为语义记忆增加 Qdrant 向量索引后端，提供 collection 初始化、向量 upsert、带过滤条件的搜索和删除接口。自动测试使用 fake Qdrant client，不依赖真实服务；同时执行一次本地 Qdrant 只读烟测确认服务可达。

## 本阶段改动

- 新增 `memory/backends/qdrant_store.py`，封装 Qdrant vector index。
- 修改 `pyproject.toml`，声明 `qdrant-client>=1.10.0`。
- `uv run` 同步依赖时更新了 `uv.lock`。
- 新增 `tests/test_memory_qdrant_store.py`，覆盖 collection、payload、search 和 delete。

## 新增文件

- `memory/backends/qdrant_store.py`
- `tests/test_memory_qdrant_store.py`
- `docs/superpowers/reports/2026-07-07-memory-phase-06.md`

## 修改文件

- `pyproject.toml`
- `uv.lock`

## 公开接口

- `QdrantMemoryIndex.ensure_collection() -> None`
  - 位置：`memory/backends/qdrant_store.py`
  - 用途：确保 collection 存在。
- `QdrantMemoryIndex.upsert_memory(record: MemoryRecord, vector: list[float]) -> None`
  - 位置：`memory/backends/qdrant_store.py`
  - 用途：把 memory record 的 metadata payload 和向量写入 Qdrant。
- `QdrantMemoryIndex.search(vector: list[float], filters: dict, top_k: int) -> list[dict]`
  - 位置：`memory/backends/qdrant_store.py`
  - 用途：按向量和 payload filter 查询候选记忆。
- `QdrantMemoryIndex.delete_memory(memory_id: str) -> None`
  - 位置：`memory/backends/qdrant_store.py`
  - 用途：从 Qdrant 删除指定 memory point。

## Qdrant 配置

- 默认 collection 名称：`agent_memories_v1`
- 默认 vector size：`1024`
- 默认 distance：`Cosine`
- 当前环境实际解析版本：

```text
qdrant-client 1.18.0
```

## Qdrant Payload 字段

每条向量 point 写入以下 payload 字段：

- `memory_id`
- `tenant_id`
- `user_id`
- `project_id`
- `thread_id`
- `scope`
- `kind`
- `status`
- `confidence`
- `importance`
- `sensitivity`
- `source_id`
- `created_at`
- `updated_at`
- `expires_at`

## 自动验证

RED 命令：

```bash
uv run pytest tests/test_memory_qdrant_store.py -v
```

RED 结果：

```text
1 error in 0.11s
```

失败原因：

- `memory.backends.qdrant_store` 尚不存在，测试收集阶段报 `ModuleNotFoundError`。

GREEN 命令：

```bash
uv run pytest tests/test_memory_qdrant_store.py -v
```

GREEN 结果：

```text
4 passed in 1.26s
```

回归测试命令：

```bash
uv run pytest tests/test_memory_interface.py tests/test_memory_sqlite_store.py tests/test_memory_audit_outbox.py tests/test_memory_redaction_classifier.py tests/test_memory_embeddings.py tests/test_memory_qdrant_store.py -v
```

回归测试结果：

```text
29 passed in 0.42s
```

全量测试命令：

```bash
uv run pytest -q
```

全量测试结果：

```text
84 passed in 0.60s
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

本阶段执行了本地 Qdrant 只读烟测：

```bash
curl -s --max-time 3 http://localhost:6333/collections
```

实际结果：

```json
{"result":{"collections":[{"name":"agent_memories"},{"name":"agent_memories_entities"}]},"status":"ok","time":0.000051541}
```

说明：

- 本机 Qdrant 服务可访问。
- 本阶段烟测只读取 collection 列表，没有创建或写入真实 collection。

## 已知限制

- 当前阶段只提供 Qdrant index 后端，还没有被 `Memory.remember/search/forget` 默认闭环调用。
- 自动测试使用 fake client，不依赖真实 Qdrant；真实写入会在后续语义闭环阶段验证。
- 当前工作区存在外部生成的 `.idea/` 变更，本阶段没有提交这些文件。

## 后续阶段

下一阶段是第 7 阶段：`remember`、`search`、`forget` 语义记忆闭环。
