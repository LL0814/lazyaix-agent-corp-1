"""Pydantic data models for the Context module."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ToolCallRecord(BaseModel):
    """A lightweight record of a tool call and its result."""

    tool_name: str
    params: dict
    result_preview: str | None = None


class TurnSummary(BaseModel):
    """Summary of a single conversation turn."""

    turn_id: int
    role: Literal["user", "assistant", "tool"]
    content_preview: str
    tool_calls: list[ToolCallRecord] | None = None
    timestamp: datetime


class TopicState(BaseModel):
    """Current active topic and intent."""

    primary_topic: str | None = None
    intent: str | None = None
    active_entities: list[str] = Field(default_factory=list)
    last_updated_turn: int = 0


class TokenStats(BaseModel):
    """Estimated token usage and pressure level."""

    estimated_tokens: int = 0
    context_limit: int = 4000
    usage_pct: float = 0.0
    warning_level: Literal["ok", "high", "critical"] = "ok"


class ContextState(BaseModel):
    """Aggregated conversation context state."""

    recent_turns: list[TurnSummary] = Field(default_factory=list)
    topic: TopicState = Field(default_factory=TopicState)
    token_stats: TokenStats = Field(default_factory=TokenStats)
    metadata: dict = Field(default_factory=dict)
