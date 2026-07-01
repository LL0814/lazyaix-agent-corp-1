# Agent 团队合作练习项目设计

## 目标

为团队合作练习初始化一个最小可运行的 Python Agent 项目骨架。老师仅负责 `loop.py` 入口文件、`agent.py` 组装文件、`.env.example` 和 `pyproject.toml`，其他七个模块（Config、Models、Tools、Skills、Context、Memory、Subagents）由学生后续实现。

## 设计决策

- **运行形态**：同步 CLI 对话循环（REPL）。
- **接口风格**：简单的类方法占位符，不使用抽象基类或 Protocol。
- **模块组织**：先创建七个空模块目录（`config/`、`models/`、`tools/`、`skills/`、`context/`、`memory/`、`subagents/`），每个目录仅放 `.gitkeep`，不实现代码。
- **环境管理**：使用 `uv` 管理 Python 环境；提供 `pyproject.toml` 和 `.python-version`，学生可通过 `uv run agent.py` 直接运行。
- **环境配置**：提供 `.env.example` 文件，用于说明项目运行所需的环境变量；`agent.py` 通过 `config` 模块读取配置，且 `python-dotenv` 为可选依赖（在 `pyproject.toml` 的 `optional-dependencies` 中声明），未安装时回退到 `os.environ`。
- **占位策略**：`agent.py` 优先尝试从模块目录导入真实实现；若模块尚未实现，则回退到内联的 Stub 类，保证项目初始即可运行。

## 项目结构

```
.
├── loop.py
├── agent.py
├── pyproject.toml
├── .python-version
├── .env.example
├── config/
│   └── .gitkeep
├── models/
│   └── .gitkeep
├── tools/
│   └── .gitkeep
├── skills/
│   └── .gitkeep
├── context/
│   └── .gitkeep
├── memory/
│   └── .gitkeep
├── subagents/
│   └── .gitkeep
└── docs/superpowers/specs/
    └── 2026-07-01-agent-team-exercise-design.md
```

## 模块职责

### `loop.py`

管理同步 CLI REPL 循环，并负责加载 `Context` 和 `Memory` 模块：
- 尝试从 `context/` 和 `memory/` 导入真实实现，失败则使用内联 Stub；
- 实例化 `Context()` 和 `Memory()` 并让它们跨轮次保持存活；
- **每轮循环都重新创建 `Agent(context, memory)`**，以体现动态组装；
- 读取用户输入、处理退出命令、输出结果；
- 通过 `agent.name` 获取显示名称，不直接访问 `agent.config`。

### `agent.py`

动态组装并管理 Agent：

1. **导入区**：对每个模块尝试 `from <module> import <Class>`，失败则使用内联 `<Class>Stub`。`Context` 和 `Memory` 不在这里组装，而是由 `loop.py` 注入。
2. **配置加载**：
   - `Config`：优先从 `config` 模块导入，缺失时使用内联 `ConfigStub`，读取 `.env` 或 `os.environ`。
   - `Model`：自行加载模型相关配置（如 `MODEL_API_KEY`、`MODEL_NAME`），不关心业务输入输出。
3. **Agent 类**：
   - `__init__(context, memory)`：接收 `loop.py` 传入的 `Context` 和 `Memory` 实例。
   - 初始化时动态创建 `Config`、`Model`、`Tool`、`Skill`、`Subagent` 五个实例。
   - 提供 `process_turn(user_input)` 方法处理单次对话轮次。
   - 通过 `ENABLE_CONTEXT` / `ENABLE_MEMORY` 配置开关，让上下文和记忆的使用变成条件式。
4. **单次轮次流程**：
   - 如果 `ENABLE_CONTEXT=true`，通过 `Context` 更新当前上下文；
   - 根据 `ENABLE_MEMORY` 决定是否把历史记忆拼入 prompt；
   - 调用 `Model.complete(prompt)` 获取原始 LLM 文本；
   - 调用 `Skill.decide(user_input, llm_response, context, memory)` 进行路由：
     - `action == "direct"`：直接返回内容；
     - `action == "tool"`：调用 `Tool.execute()`；
   - 如果 `ENABLE_MEMORY=true`，把本轮记录存入 `Memory`；
   - 返回结果字符串。

   `Subagent` 作为已组装的组件保留，供学生按需扩展，默认不进入主流程。
5. **Stub 类**：每个模块一个最小占位类，核心方法返回占位值或抛出 `NotImplementedError`，指导学生实现。

## 模块接口约定

各模块需暴露一个与 `agent.py` 中 Stub 同名的类，且至少包含以下方法：

| 模块 | 类名 | 核心方法 |
|------|------|----------|
| config | `Config` | `get(key, default=None)` |
| models | `Model` | `complete(prompt)` |
| tools | `Tool` | `execute(action, params)` |
| skills | `Skill` | `decide(user_input, llm_response, context, memory)` |
| context | `Context` | `update(input)` / `get()` |
| memory | `Memory` | `store(key, value)` / `retrieve(key)` |
| subagents | `Subagent` | `dispatch(task_description)` |

## 成功标准

- 项目能通过 `uv run loop.py` 或 `python3 loop.py` 直接运行。
- REPL 能接收输入并走完一次完整的主循环流程，即使所有模块都是占位实现。
- 学生能根据 Stub 类的接口约定，在对应目录中逐步实现真实模块。
