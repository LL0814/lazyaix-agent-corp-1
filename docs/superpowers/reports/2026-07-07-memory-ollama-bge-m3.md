# Ollama bge-m3 全链路适配报告

## 本次目标

把 memory embedding 默认链路从 `FlagEmbedding + HuggingFace BAAI/bge-m3` 切换为本地：

```text
Ollama /api/embed
-> bge-m3
-> 1024 维向量
-> Qdrant
```

同时修复 `loop.py` 对话记忆链路中“长期记忆已检索但回答被 Skill 路由二次 LLM 覆盖”的问题。

## 新增配置

默认值已经变为：

```bash
MEMORY_EMBEDDING_PROVIDER=ollama
OLLAMA_EMBEDDING_MODEL=bge-m3
OLLAMA_BASE_URL=http://localhost:11434
MEMORY_EMBEDDING_DIMENSION=1024
```

如果以后要回退 HuggingFace / FlagEmbedding，可以显式设置：

```bash
MEMORY_EMBEDDING_PROVIDER=flagembedding
MEMORY_EMBEDDING_MODEL=BAAI/bge-m3
```

## 实现位置

- `memory/embeddings.py`
  - 新增 `OllamaEmbeddingProvider`
  - 新增 `create_embedding_provider(config)`
- `memory/config.py`
  - 默认 embedding provider 改为 `ollama`
  - 新增 `ollama_base_url` / `ollama_timeout_seconds`
- `memory/service.py`
  - 初始化时按配置创建 embedding provider
- `memory/worker.py`
  - `summary` 类型写入 summary 表，不再错误写入 Qdrant 向量记录
- `agent.py`
  - prompt 注入 `Memory summary`
  - prompt 注入长期记忆检索结果
- `skills/skill.py`
  - direct 路由只做路由判断，不再用第二次 LLM 回答覆盖已经带记忆的主回答

## 覆盖的记忆类型

- `kv_state`
  - `Memory.store(key, value)` 写入 SQLite KV。
- `semantic`
  - 写入 SQLite `memory_records`，同时用 Ollama bge-m3 生成向量并写入 Qdrant。
- `procedural`
  - 同 semantic，用于工作方式、流程偏好。
- `episodic`
  - 支持写入 SQLite + Qdrant；真实集成测试已覆盖。
- `summary`
  - `Memory.update_summary()` 或 worker 抽取到 `summary` 时写入 `memory_summaries`。
- `tombstone`
  - `Memory.forget(memory_id)` 将原记录标记为 `deleted`，并删除 Qdrant point。

## 测试结果

真实 Ollama API：

```text
/api/embed model=bge-m3
dim=1024
```

针对性测试：

```bash
uv run pytest tests/test_memory_embeddings.py tests/test_memory_interface.py tests/test_memory_ollama_real_integration.py -v
```

结果：

```text
11 passed
```

全量测试：

```bash
uv run pytest -q
```

结果：

```text
118 passed
```

## 真实 loop.py 烟测

启动命令：

```bash
MODEL=deepseek:deepseek-v4-pro \
MEMORY_EXTRACTOR_PROVIDER=deepseek \
MEMORY_EMBEDDING_PROVIDER=ollama \
OLLAMA_EMBEDDING_MODEL=bge-m3 \
MEMORY_DB_PATH=.memory/loop_ollama_smoke.sqlite3 \
QDRANT_COLLECTION=agent_memories_loop_ollama_smoke \
uv run python loop.py
```

输入过的记忆：

```text
我喜欢住安静一点、离地铁近的酒店，以后帮我推荐住宿时优先考虑这个。
以后你每完成一个工程步骤，都先用中文告诉我改了哪些文件、怎么人工验证。
当前项目的本地向量数据库用 Qdrant，embedding 模型用 Ollama 的 bge-m3。
```

验证问题：

```text
请你根据记忆总结一下我的住宿偏好、工程汇报方式和这个项目的向量配置。
```

真实回答命中长期记忆：

```text
住宿偏好：偏好安静且靠近地铁的酒店。
工程汇报方式：每完成一个工程步骤，先列出修改的文件，并提供人工验证的方法，使用中文。
项目向量配置：本地向量数据库是 Qdrant，Embedding 模型是 Ollama 上的 bge-m3。
```

SQLite 检查：

```text
semantic|active|用户偏好安静且靠近地铁的酒店
procedural|active|每次完成工程步骤后，先列出修改的文件并提供人工验证方法，使用中文说明。
semantic|active|当前项目使用 Qdrant 作为本地向量数据库，embedding 模型为 Ollama 的 bge-m3。
```

Qdrant 检查：

```text
collection_exists True
qdrant_count 3
```

## 你接下来可以在 loop.py 里测试的话术

住宿偏好：

```text
我喜欢住安静一点、离地铁近的酒店，以后帮我推荐住宿时优先考虑这个。
```

工程流程偏好：

```text
以后你每完成一个工程步骤，都先用中文告诉我改了哪些文件、怎么人工验证。
```

项目事实：

```text
当前项目的本地向量数据库用 Qdrant，embedding 模型用 Ollama 的 bge-m3。
```

一次性事件：

```text
今天我在 loop.py 里测试了 Ollama bge-m3 记忆链路。
```

验证召回：

```text
请你根据记忆总结一下我的住宿偏好、工程汇报方式和这个项目的向量配置。
```

查看 SQLite：

```bash
sqlite3 .memory/memory.sqlite3 \
"select kind,status,content from memory_records order by created_at desc limit 10;"
```

查看 Qdrant point 数量：

```bash
uv run python - <<'PY'
from qdrant_client import QdrantClient
client = QdrantClient(url="http://localhost:6333")
print(client.count(collection_name="agent_memories_v1", exact=True).count)
PY
```
