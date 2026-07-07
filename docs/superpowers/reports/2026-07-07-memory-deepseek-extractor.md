# DeepSeek 记忆抽取器实现报告

## 本次目标

把 DeepSeek 引入 memory worker，但保持职责分层：

```text
Agent/loop.py
-> Memory.store("history")
-> memory_outbox.pending
-> Memory.process_outbox()
-> MemoryCandidateExtractor
   -> RuleBasedMemoryExtractor
   -> DeepSeekMemoryExtractor
-> Memory.remember()
-> SQLite memory_records / memory_sources
-> Qdrant vector
```

Worker 仍然只负责调度和状态流转；AI 只负责“是否值得记、记忆类型、精炼内容、置信度、重要性”。

## 新增配置

主对话模型：

```bash
MODEL=deepseek:deepseek-v4-pro
```

记忆抽取器：

```bash
MEMORY_EXTRACTOR_PROVIDER=deepseek
MEMORY_DEEPSEEK_MODEL=deepseek-v4-pro
```

API Key 支持两种环境变量：

```bash
DEEPSEEK_API_KEY=...
DS_API_KEY=...
```

默认仍然是规则抽取器。这样测试和普通本地开发不会因为机器上存在 API Key 就误触真实网络请求。

## 新增接口和文件

- `memory/extractors.py`
  - `MemoryCandidateExtractor`
  - `RuleBasedMemoryExtractor`
  - `DeepSeekMemoryExtractor`
  - `create_memory_candidate_extractor(config)`
- `models/providers/deepseek.py`
  - `DeepSeekProvider`
- `Memory(..., candidate_extractor=...)`
  - 测试或企业编排层可以注入自定义抽取器。

## 改动点

- `memory/models.py`
  - `MemoryClassification` 增加 `content` 字段，用来承载 AI 精炼后的长期记忆文本。
- `memory/worker.py`
  - 从直接调用规则分类器，改为调用 `self.memory._candidate_extractor.extract(...)`。
  - 写入 `memory_records.content` 时优先使用 AI 返回的 `content`。
  - 把 `confidence` / `importance` 写入 `MemoryRecord`。
- `memory/service.py`
  - 初始化时根据配置创建抽取器。
  - `remember()` 支持写入 `confidence` / `importance`。
- `agent.py`
  - 每轮回答后自动调用 `memory.process_outbox()`。
  - 下一轮构造 prompt 时，如果已经有长期记忆，会调用 `memory.search(user_input)` 并注入：

```text
Long-term memories:
- [semantic] 用户偏好入住安静的酒店。
```

## 测试覆盖

- DeepSeek 抽取器能解析 JSON。
- DeepSeek 抽取器能剥离 ```json 代码块。
- DeepSeek 返回坏 JSON 时回退规则版。
- Worker 使用 AI 抽取后的 `content`，而不是原始 Q/A。
- Worker 写入 AI 的 `confidence` / `importance`。
- Agent 在第一轮回答后自动消费 outbox。
- Agent 在第二轮 prompt 中注入长期记忆。
- `MODEL=deepseek:deepseek-v4-pro` 可被模型工厂识别。
- `DS_API_KEY` 可作为 DeepSeek API Key 使用。

## loop.py 人工测试命令

如果你的 API Key 已经在 `.env` 或 shell 环境里，可以直接运行：

```bash
MODEL=deepseek:deepseek-v4-pro \
MEMORY_EXTRACTOR_PROVIDER=deepseek \
MEMORY_DEEPSEEK_MODEL=deepseek-v4-pro \
uv run python loop.py
```

如果你的 key 变量名是 `DS_API_KEY`，无需改名；如果是别的名字，建议临时映射：

```bash
export DEEPSEEK_API_KEY="$你的变量名"
```

## 人工测试对话

第一组：测试 semantic 偏好记忆

```text
我喜欢住安静一点、离地铁近的酒店，以后帮我推荐住宿时优先考虑这个。
```

隔一轮再问：

```text
我下次订酒店时你还记得我的住宿偏好吗？
```

第二组：测试 procedural 工作方式记忆

```text
以后你每完成一个工程步骤，都先用中文告诉我改了哪些文件、怎么人工验证。
```

隔一轮再问：

```text
你之后完成工程步骤时应该怎么向我汇报？
```

第三组：测试项目事实记忆

```text
当前项目的本地向量数据库用 Qdrant，embedding 模型用 bge-m3。
```

隔一轮再问：

```text
这个项目现在用什么向量数据库和 embedding 模型？
```

第四组：测试低价值内容不会被记

```text
好的。
```

隔一轮再问：

```text
刚才那句“好的”有没有必要作为长期记忆？
```

## 数据库人工检查

查看长期记忆：

```bash
sqlite3 .memory/memory.sqlite3 \
"select kind, confidence, importance, content from memory_records where status='active' order by created_at desc limit 10;"
```

查看 outbox 状态：

```bash
sqlite3 .memory/memory.sqlite3 \
"select status, json_extract(payload_json, '$.worker_result.kind'), json_extract(payload_json, '$.worker_result.content') from memory_outbox order by created_at desc limit 10;"
```

如果 DeepSeek 返回异常且开启了默认回退，通常会看到规则版继续处理；如果关闭回退，则 outbox 会进入 `failed`。
