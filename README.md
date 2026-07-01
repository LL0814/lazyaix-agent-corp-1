# Agent Team Exercise

一个用于团队合作练习的模块化 Agent 骨架项目。

老师负责初始化入口文件、核心组装逻辑和环境配置；学生分组实现 `models/`、`tools/`、`skills/`、`context/`、`memory/`、`subagents/`、`config/` 七个模块。

## 项目结构

```
.
├── loop.py              # REPL 入口：管理循环并持有 Context / Memory
├── agent.py             # Agent 组装与单次轮次逻辑
├── pyproject.toml       # uv 项目配置
├── .python-version      # Python 版本锁定
├── .env.example         # 环境变量示例
├── README.md            # 本文件
├── config/              # Config 模块（学生实现）
├── models/              # Model 模块：加载配置，提供 LLM complete()（学生实现）
├── tools/               # Tool 模块：执行外部动作（学生实现）
├── skills/              # Skill 模块：决定直接回答还是调用工具（学生实现）
├── context/             # Context 模块：维护当前上下文（学生实现）
├── memory/              # Memory 模块：存储与检索记忆（学生实现）
└── subagents/           # Subagent 模块：子代理分发（学生实现）
```

## 快速开始

```bash
# 使用 uv 运行
uv run loop.py

# 或使用系统 Python3
python3 loop.py
```

## 单次轮次流程

`Agent.process_turn(user_input)` 的执行流程：

1. **更新 Context**（当 `ENABLE_CONTEXT=true` 时）
2. **构建 Prompt**（根据 `ENABLE_MEMORY` 决定是否拼入历史记忆）
3. **调用 Model.complete(prompt)** 获取原始 LLM 文本
4. **调用 Skill.decide(...)** 进行路由：
   - `action == "direct"`：直接返回 LLM 文本
   - `action == "tool"`：调用 `Tool.execute(tool, params)`
5. **写入 Memory**（当 `ENABLE_MEMORY=true` 时）
6. 返回结果

## 环境变量

复制 `.env.example` 为 `.env` 并按需修改：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MODEL_API_KEY` | 模型提供商 API Key | `stub-key` |
| `MODEL_NAME` | 模型名称 | `stub-llm` |
| `AGENT_NAME` | REPL 中显示的 Agent 名称 | `Agent` |
| `ENABLE_CONTEXT` | 是否启用上下文更新 | `true` |
| `ENABLE_MEMORY` | 是否启用记忆存储 | `true` |
| `LOG_LEVEL` | 日志级别 | `INFO` |

## 模块接口约定

| 模块 | 类名 | 核心方法 |
|------|------|----------|
| config | `Config` | `get(key, default=None)` |
| models | `Model` | `__init__()` 加载配置；`complete(prompt: str) -> str` |
| tools | `Tool` | `execute(action, params)` |
| skills | `Skill` | `decide(user_input, llm_response, context, memory) -> dict` |
| context | `Context` | `update(input)` / `get()` |
| memory | `Memory` | `store(key, value)` / `retrieve(key)` |
| subagents | `Subagent` | `dispatch(task_description)` |

## 设计要点

- **loop.py** 保持薄：只负责 I/O、持有 `Context` / `Memory`、每轮重新创建 `Agent`。
- **agent.py** 负责动态组装除 `Context` / `Memory` 外的所有模块，并实现单次轮次逻辑。
- **Model** 是纯 LLM 包装器，不处理业务路由。
- **Skill** 是路由层，决定直接回答或调用工具。
- 如果学生模块未实现，`agent.py` / `loop.py` 会回退到内联 Stub，保证项目初始即可运行。
