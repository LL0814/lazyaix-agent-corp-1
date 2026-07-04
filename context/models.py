"""Context 模块的 Pydantic 数据模型定义。

本模块定义了 Context 模块所有用到的数据结构，包括：
- TurnSummary：单轮对话的摘要记录（含原文保留与压缩清理字段）
- TopicState：当前对话主题与意图
- TokenStats：token 使用量与压力等级
- CompactEvent / CompressionState：压缩事件记录与四层压缩的整体状态
- ContextState：聚合以上所有字段的顶层状态对象

设计原则：
- 所有模型继承 BaseModel，使用 Pydantic v2 校验
- full_content 字段用于"原文保留"，压缩时可被清空以节省 token
- content_preview 字段用于"显示与传递"，压缩后仍然保留
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ToolCallRecord(BaseModel):
    """工具调用的轻量记录。

    当 agent 调用某个工具（如 weather、write_file 等）时，
    用此结构记录工具名、参数和结果预览，便于后续压缩与回溯。
    """

    tool_name: str
    # 工具调用参数，例如 {"city": "Beijing"}
    params: dict
    # 工具返回结果的预览文本；可为 None 表示无结果或尚未填充
    result_preview: str | None = None


class TurnSummary(BaseModel):
    """单轮对话的摘要记录。

    每当用户输入、模型回复、或工具返回时，都会创建一条 TurnSummary。
    字段分为两类：
    - 显示用：content_preview（截断后的预览文本，压缩后仍保留）
    - 压缩用：full_content（完整原文，可被 MicroCompact 清空以降低 token 占用）

    role="system" 的 turn 由 ContextCollapse 生成，作为对旧 turn 的折叠摘要。
    """

    # turn 序号，全局递增，不随压缩而重排
    turn_id: int
    # 角色标识：user=用户输入, assistant=模型回复, tool=工具结果, system=压缩生成的摘要
    role: Literal["user", "assistant", "tool", "system"]
    # 内容预览，默认截断为 PREVIEW_LENGTH（120 字符），用于展示与传递给 Skill
    content_preview: str
    # 完整原文，供压缩层基于原文进行估算与折叠；被 MicroCompact 清空后为 None
    full_content: str | None = None
    # 当 role="tool" 时记录的工具调用信息；其他角色为 None
    tool_calls: list[ToolCallRecord] | None = None
    # 该 turn 创建的时间戳
    timestamp: datetime


class TopicState(BaseModel):
    """当前对话的主题与意图状态。

    基于用户输入的关键词推断（见 Context._infer_topic），
    用于让其他模块（如 Skill）感知当前正在讨论什么。
    主题类型目前固定为 weather / math / file_edit 三类。
    """

    # 当前主主题，例如 "weather"；无明确主题时为 None（沿用上一轮）
    primary_topic: str | None = None
    # 意图：query=查询, compute=计算, request=请求操作
    intent: str | None = None
    # 从用户输入中提取的引号包裹的实体，例如 ["Beijing", "test.txt"]
    active_entities: list[str] = Field(default_factory=list)
    # 最近一次更新主题时的 turn_id
    last_updated_turn: int = 0


class TokenStats(BaseModel):
    """Token 使用量统计与压力等级。

    usage_pct 是驱动四层压缩触发的核心指标；warning_level 仅用于显示，
    与压缩阈值是分离的（设计文档第 2 节明确）。
    """

    # 估算的已用 token 数（公式：ceil(总字符数 / 4)）
    estimated_tokens: int = 0
    # 上下文容量上限，对应配置项 CONTEXT_LIMIT，默认 50000
    context_limit: int = 50_000
    # 利用率百分比 = estimated_tokens / context_limit * 100
    usage_pct: float = 0.0
    # 压力等级：ok(<50%) / high(50-80%) / critical(>=80%)，仅供显示
    warning_level: Literal["ok", "high", "critical"] = "ok"


class CompactEvent(BaseModel):
    """Record of a single compaction event."""

    timestamp: datetime
    layer: Literal[
        "tool_result_budget",
        "snip",
        "micro",
        "compact_history",
        "reactive",
    ]
    usage_before: int = 0
    usage_after: int = 0
    notes: str = ""


class CompressionState(BaseModel):
    """Tracks which compaction layers have fired and their history."""

    tool_result_budget_triggered: bool = False
    snip_triggered: bool = False
    micro_triggered: bool = False
    compact_history_triggered: bool = False
    compact_history_failures: int = 0
    compact_history_disabled: bool = False
    compact_history_path: str | None = None
    compact_history_summary: str | None = None
    compact_history: list[CompactEvent] = Field(default_factory=list)


class ContextState(BaseModel):
    """Context 模块的顶层聚合状态。

    将 recent_turns、topic、token_stats、compression 全部聚合在一个对象中，
    便于整体快照、序列化与传递。Context.snapshot() 返回此对象的深拷贝，
    Context.get() 返回此对象的 JSON-serializable dict。
    """

    # 最近的对话轮次记录（按时间顺序，受 MAX_RECENT_TURNS 限制长度）
    recent_turns: list[TurnSummary] = Field(default_factory=list)
    # 当前主题状态
    topic: TopicState = Field(default_factory=TopicState)
    # 当前 token 统计
    token_stats: TokenStats = Field(default_factory=TokenStats)
    # 压缩状态与历史
    compression: CompressionState = Field(default_factory=CompressionState)
    # 扩展元数据，供其他模块附加自定义信息
    metadata: dict = Field(default_factory=dict)
