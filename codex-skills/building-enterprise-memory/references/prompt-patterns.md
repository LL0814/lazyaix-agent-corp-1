# Prompt Patterns

Use this reference when generating prompts, plans, manual QA scripts, or acceptance criteria for enterprise memory projects.

## User Intent Pattern

The successful user prompt pattern from the memory project was:

```text
帮我只实现 memory 层功能，做企业级方案，可以借鉴 Claude 和 Codex 的记忆系统。
不要一次性黑盒实现，要按照工程流程来做：先写配置和接口，测试接口，再整合功能，再做集成测试。
每完成一步都写中文报告，告诉我接口在哪里、代码在哪里、怎么人工验证。
本地向量数据库用 Qdrant，embedding 用本地 bge-m3。worker 要能自动处理 outbox。
后面我要在 loop.py 里对话测试，记忆要能隐式从自然语言里抽取，不要要求我显式说“记住”。
一句话尽量提取多种类型的记忆，每条记忆标清时间。
```

Codex should preserve the intent, not copy wording blindly.

## Planning Prompt

```text
请基于当前仓库设计一个企业级 memory 层实施计划。
要求：
1. 仿照 Claude/Codex 的记忆模式：隐式抽取、长期记忆、相关召回、用户可验证。
2. 存储按类型拆分：KV、情景、语义、流程、摘要、删除标记。
3. 使用 SQLite 做 durable records/outbox/audit，Qdrant 做向量检索，Ollama bge-m3 做 embedding。
4. DeepSeek/Kimi/OpenAI-compatible 模型只做抽取器和对话模型，不进入确定性单测。
5. 分阶段交付，每阶段必须有 TDD、集成测试、中文报告、人工验证方法。
```

## Stage-Gate Prompt

```text
不要一次性实现。按阶段推进：
第一阶段只做配置和接口，并写测试；
第二阶段做 SQLite 存储和 outbox，并写状态流测试；
第三阶段做 embedding/Qdrant，并写 fake provider + 可选真实集成测试；
第四阶段做 worker 和 AI extractor；
第五阶段接入 Agent/loop.py；
第六阶段跑全量测试并提交功能报告。
每阶段完成后暂停汇报：改了哪些文件、接口在哪、测试怎么跑、我怎么人工验证。
```

## Checkpoint Questions

Ask or answer these at each boundary:

- 现在执行到哪个阶段？
- 本阶段实现了哪些接口？
- 这些接口的实现在哪里？
- 哪些数据写入 SQLite，哪些写入 Qdrant？
- outbox 从什么状态变成什么状态？
- worker 是否自动处理？失败是否记录？
- 对话前检索到的记忆是否拼接进 prompt？
- 怎么人工验证这条记忆真的存进去了？

## Implicit Memory Test Prompts

Use fresh examples when testing. Do not say "记住".

### Semantic

```text
我做供应商评估时不太喜欢只看报价，之前有个便宜方案售后慢，差点拖延上线。
```

Expected extraction: preference for vendor evaluation; after-sales response matters more than price-only comparison.

### Episodic

```text
上周给华南客户路演时，我先讲收益再讲风险，结果问答节奏乱了不少。
```

Expected extraction: dated event/case; bad ordering created Q&A confusion.

### Procedural

```text
以后做路演材料，我一般希望先把风险边界讲清楚，再讲收益空间。
```

Expected extraction: workflow/order preference.

### KV State

```text
我每天 11:30 到 13:00 状态通常不好，这段时间尽量别排项目周会。
```

Expected extraction: scheduling constraint with exact time window.

### Summary

```text
今天这个记忆模块的主线就是：先做接口，再做 SQLite 和 outbox，再做 Qdrant 召回，最后接到 loop.py 里验证。
```

Expected extraction: project summary or conversation summary candidate.

### Multi-kind Single Turn

```text
昨天面试那个后端候选人技术可以，但协作经历太薄；以后筛人时我想先看稳定性和跨团队沟通，再看纯技术亮点。顺便，下午两点前我通常不适合做终面。
```

Expected extraction:
- episodic: yesterday's interview case
- procedural: recruiting evaluation order
- semantic: hiring preference
- kv_state: scheduling constraint before 14:00

## Recall Test Prompts

After storing implicit prompts, ask:

```text
帮我评估一个供应商时应该先看什么？
```

```text
下次路演材料的顺序你建议怎么排？
```

```text
我什么时候不适合排项目周会？
```

```text
招聘候选人时，我比较看重哪些维度？
```

The answer should use relevant memory without dumping unrelated memories.
