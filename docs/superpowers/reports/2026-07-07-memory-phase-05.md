# 第 5 阶段报告：BGE-M3 Embedding Provider

## 本阶段目标

为长期语义记忆增加 embedding provider 抽象：自动测试使用确定性的 `FakeEmbeddingProvider`，真实运行默认可使用 `BGEM3EmbeddingProvider` 加载 `BAAI/bge-m3`。

## 本阶段改动

- 新增 `memory/embeddings.py`，提供 embedding provider 接口和两个实现。
- 修改 `pyproject.toml`，声明 `FlagEmbedding>=1.2.11` 和 `numpy>=1.26`。
- `uv run` 同步依赖时更新了 `uv.lock`。
- 新增 `tests/test_memory_embeddings.py`，覆盖 fake provider、BGE-M3 懒加载和缺少依赖时的错误信息。

## 新增文件

- `memory/embeddings.py`
- `tests/test_memory_embeddings.py`
- `docs/superpowers/reports/2026-07-07-memory-phase-05.md`

## 修改文件

- `pyproject.toml`
- `uv.lock`

## 公开接口

- `EmbeddingProvider.embed(text: str) -> list[float]`
  - 位置：`memory/embeddings.py`
  - 用途：定义 embedding provider 协议。
- `FakeEmbeddingProvider.embed(text: str) -> list[float]`
  - 位置：`memory/embeddings.py`
  - 用途：测试用确定性向量，不访问外部模型。
- `BGEM3EmbeddingProvider.embed(text: str) -> list[float]`
  - 位置：`memory/embeddings.py`
  - 用途：懒加载 `FlagEmbedding.BGEM3FlagModel`，生成 BGE-M3 dense embedding。

## 依赖版本

本阶段声明版本约束：

- `FlagEmbedding>=1.2.11`
- `numpy>=1.26`

当前环境实际解析版本：

```text
FlagEmbedding 1.4.0
numpy 2.4.6
```

## 自动验证

RED 命令：

```bash
uv run pytest tests/test_memory_embeddings.py -v
```

RED 结果：

```text
1 error in 0.10s
```

失败原因：

- `memory.embeddings` 尚不存在，测试收集阶段报 `ModuleNotFoundError`。

GREEN 命令：

```bash
uv run pytest tests/test_memory_embeddings.py -v
```

GREEN 结果：

```text
4 passed in 0.05s
```

回归测试命令：

```bash
uv run pytest tests/test_memory_interface.py tests/test_memory_sqlite_store.py tests/test_memory_audit_outbox.py tests/test_memory_redaction_classifier.py tests/test_memory_embeddings.py -v
```

回归测试结果：

```text
25 passed in 0.09s
```

全量测试命令：

```bash
uv run pytest -q
```

全量测试结果：

```text
80 passed in 0.54s
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

真实 BGE-M3 烟测本阶段未自动执行，因为它会加载大模型，耗时和本地缓存状态不可控。用户可以在本机手动执行：

```bash
uv run python - <<'PY'
from memory.embeddings import BGEM3EmbeddingProvider
p = BGEM3EmbeddingProvider(model_name="BAAI/bge-m3")
v = p.embed("我喜欢安静的酒店")
print(len(v))
print(type(v[0]).__name__)
PY
```

预期：

```text
1024
float
```

## 已知限制

- `FakeEmbeddingProvider` 只用于测试，不具备真实语义能力。
- `BGEM3EmbeddingProvider` 当前只暴露 dense embedding，没有暴露 BGE-M3 的 sparse 或 multi-vector 能力。
- 当前阶段只提供 provider，还没有接入 `remember/search/forget` 闭环。
- 当前工作区存在外部生成的 `.idea/` 变更，本阶段没有提交这些文件。

## 后续阶段

下一阶段是第 6 阶段：Qdrant 向量索引后端。
