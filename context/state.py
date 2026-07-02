"""Context 模块的核心状态管理实现。

本模块定义 Context 类，负责：
1. 维护对话轮次（recent_turns）与主题状态
2. 估算 token 使用量并计算利用率
3. 根据利用率阈值自动触发四层渐进压缩：
   - SnipCompact（≥50%）：删除安全旧 turn
   - MicroCompact（≥65%）：清空旧 tool turn 的 full_content
   - ContextCollapse（≥80%）：旧 turn 合并为 summary turn
   - AutoCompact（≥90%）：预留 stub，不调用 LLM
4. 提供手动 compact(force=True) 与重置标志位接口

设计要点：
- update() / get() 接口对外契约不变
- Agent / Loop 无需感知压缩细节
- 每层压缩保护最近 SAFE_TURNS 条 turn 不被处理
"""

import re
import warnings
from datetime import datetime
from math import ceil

from context.models import CompactEvent, ContextState, ToolCallRecord, TokenStats, TopicState, TurnSummary


class Context:
    """对话上下文管理器，维护状态并按阈值触发四层渐进压缩。

    通过传入 config 字典配置容量、阈值、保护窗口等参数。
    典型用法：
        ctx = Context(config={"CONTEXT_LIMIT": 4000})
        ctx.update("用户输入")
        state = ctx.get()
    """

    # SnipCompact 的保护关键词：含这些词的 turn 不会被 snip 删除，
    # 因为它们可能包含重要的文件操作或错误信息。
    _PROTECTED_KEYWORDS = ("write_file", "edit_file", "error", "traceback")

    def __init__(self, config: dict | None = None):
        """初始化 Context，读取配置并设置默认值。

        所有配置项都做容错处理：类型错误或非正值时回退到默认值并发出警告，
        保证 Context 始终可用。
        """
        config = config or {}

        # ---- 容量配置 ----
        # 上下文 token 容量上限，用于计算利用率（默认 4000）
        try:
            self.context_limit = int(config.get("CONTEXT_LIMIT", 4000))
        except (ValueError, TypeError):
            warnings.warn("Invalid CONTEXT_LIMIT; falling back to 4000")
            self.context_limit = 4000

        if self.context_limit <= 0:
            warnings.warn("CONTEXT_LIMIT must be positive; falling back to 4000")
            self.context_limit = 4000

        # recent_turns 列表的最大长度（默认 5），超过则截断最旧的 turn
        try:
            self.max_recent_turns = int(config.get("MAX_RECENT_TURNS", 5))
        except (ValueError, TypeError):
            warnings.warn("Invalid MAX_RECENT_TURNS; falling back to 5")
            self.max_recent_turns = 5

        if self.max_recent_turns <= 0:
            warnings.warn("MAX_RECENT_TURNS must be positive; falling back to 5")
            self.max_recent_turns = 5

        # ---- 显示配置 ----
        # content_preview 截断长度（默认 120 字符）
        try:
            self.preview_length = int(config.get("PREVIEW_LENGTH", 120))
        except (ValueError, TypeError):
            warnings.warn("Invalid PREVIEW_LENGTH; falling back to 120")
            self.preview_length = 120

        if self.preview_length <= 0:
            warnings.warn("PREVIEW_LENGTH must be positive; falling back to 120")
            self.preview_length = 120

        # ---- 压缩保护配置 ----
        # 每层压缩保护最近 N 条 turn 不被处理（默认 3）
        try:
            self.safe_turns = int(config.get("SAFE_TURNS", 3))
        except (ValueError, TypeError):
            warnings.warn("Invalid SAFE_TURNS; falling back to 3")
            self.safe_turns = 3

        if self.safe_turns <= 0:
            warnings.warn("SAFE_TURNS must be positive; falling back to 3")
            self.safe_turns = 3

        # ---- 四层压缩阈值配置（单位：百分比）----
        def _threshold(name: str, default: float) -> float:
            """读取阈值配置，类型错误或负值时回退到默认值。"""
            try:
                value = float(config.get(name, default))
            except (ValueError, TypeError):
                warnings.warn(f"Invalid {name}; falling back to {default}")
                value = default
            if value < 0:
                warnings.warn(f"{name} must be non-negative; falling back to {default}")
                value = default
            return value

        # SnipCompact 触发阈值，默认 50%
        self.snip_threshold = _threshold("SNIP_THRESHOLD", 50.0)
        # MicroCompact 触发阈值，默认 65%
        self.micro_threshold = _threshold("MICRO_THRESHOLD", 65.0)
        # ContextCollapse 触发阈值，默认 80%
        self.collapse_threshold = _threshold("COLLAPSE_THRESHOLD", 80.0)
        # AutoCompact 触发阈值，默认 90%
        self.auto_threshold = _threshold("AUTO_THRESHOLD", 90.0)

        # ---- 内部状态 ----
        self._state = ContextState()  # 当前上下文状态
        self._turn_counter = 0        # turn 全局计数器，单调递增

    def _make_preview(self, text: str) -> str:
        """将文本截断为 preview_length 长度，作为 content_preview。"""
        return text[: self.preview_length]

    def _estimate_tokens(self) -> int:
        """估算当前所有 turn 占用的 token 数。

        估算公式：ceil(总字符数 / 4)，即 4 个字符约等于 1 个 token。
        优先使用 full_content，若被 MicroCompact 清空则回退到 content_preview。
        当回退到 content_preview 时，会额外加上 tool_calls 的 result_preview，
        以尽量逼近真实占用。
        """
        total = 0
        for turn in self._state.recent_turns:
            text = turn.full_content or turn.content_preview or ""
            total += len(text)
            # 仅当 full_content 已被清空时，才把 tool_calls 的预览也计入，
            # 避免在 full_content 存在时与原文重复累加。
            if not turn.full_content and turn.tool_calls:
                for tc in turn.tool_calls:
                    preview = tc.result_preview or ""
                    total += len(preview)
        return max(0, ceil(total / 4))

    def _compute_token_stats(self) -> TokenStats:
        """计算当前 token 统计并确定压力等级。

        warning_level 与压缩阈值是分离的：
        - ok：< 50%
        - high：50% - 80%
        - critical：>= 80%
        压缩层使用各自的独立阈值判断，不依赖 warning_level。
        """
        estimated = self._estimate_tokens()
        usage_pct = (estimated / self.context_limit * 100) if self.context_limit > 0 else 0.0

        if usage_pct >= 80.0:
            warning_level = "critical"
        elif usage_pct >= 50.0:
            warning_level = "high"
        else:
            warning_level = "ok"

        return TokenStats(
            estimated_tokens=estimated,
            context_limit=self.context_limit,
            usage_pct=usage_pct,
            warning_level=warning_level,
        )

    def _is_protected(self, turn: TurnSummary) -> bool:
        """检查 turn 是否受保护，不应被 SnipCompact 删除。

        判断依据：full_content 或 content_preview 中是否包含任一保护关键词。
        保护关键词见 _PROTECTED_KEYWORDS（write_file / edit_file / error / traceback）。
        """
        text = turn.full_content or turn.content_preview or ""
        return any(keyword in text for keyword in self._PROTECTED_KEYWORDS)

    def _record_compact_event(
        self,
        layer: str,
        turns_removed: int = 0,
        usage_before: float = 0.0,
        notes: str = "",
    ) -> None:
        """记录一次压缩事件到 compact_history。

        在压缩实际执行后调用，用于审计与调试。
        会重新计算 token_stats 以反映压缩后的利用率。
        """
        self._state.token_stats = self._compute_token_stats()
        after = self._state.token_stats.usage_pct
        threshold = getattr(self, f"{layer}_threshold")
        event = CompactEvent(
            timestamp=datetime.now(),
            layer=layer,  # type: ignore[arg-type]
            threshold=threshold,
            usage_before=usage_before,
            usage_after=after,
            turns_removed=turns_removed,
            notes=notes,
        )
        self._state.compression.compact_history.append(event)

    def _snip_compact(self) -> bool:
        """第一层压缩：SnipCompact（删除安全旧 turn）。

        触发条件：利用率 >= snip_threshold（默认 50%）且本层未触发过。
        操作：从 recent_turns 头部开始，删除不在 safe 窗口内且不含保护关键词的 turn，
              直到利用率降到阈值以下或没有可删除的候选。
        保护规则：最近 safe_turns 条 turn 不被处理；含保护关键词的 turn 不被删除。
        """
        if self._state.compression.snip_triggered:
            return False

        usage = self._state.token_stats.usage_pct
        if usage < self.snip_threshold:
            return False

        removed = 0
        usage_before = self._state.token_stats.usage_pct
        # 持续删除直到利用率降到阈值以下
        while self._state.token_stats.usage_pct >= self.snip_threshold:
            # 候选 = 不在 safe 窗口内（即[:-safe_turns]）且不受保护的 turn 的索引
            candidates = [
                i
                for i, turn in enumerate(self._state.recent_turns[:-self.safe_turns])
                if not self._is_protected(turn)
            ]
            if not candidates:
                break
            idx = candidates[0]
            self._state.recent_turns.pop(idx)
            removed += 1
            self._state.token_stats = self._compute_token_stats()

        if removed > 0:
            self._state.compression.snip_triggered = True
            self._record_compact_event("snip", removed, usage_before=usage_before)
            return True
        return False

    def _micro_compact(self) -> bool:
        """第二层压缩：MicroCompact（清空旧 tool turn 的 full_content）。

        触发条件：利用率 >= micro_threshold（默认 65%）且本层未触发过。
        操作：对所有不在 safe 窗口内的 tool turn，将 full_content 置为 None，
              保留 content_preview 供显示使用。
        保护规则：最近 safe_turns 条 turn 不被处理。
        注意：清空 full_content 会降低 token 估算，但 content_preview 仍保留。
        """
        if self._state.compression.micro_triggered:
            return False

        usage = self._state.token_stats.usage_pct
        if usage < self.micro_threshold:
            return False

        cleared = 0
        usage_before = self._state.token_stats.usage_pct
        for turn in self._state.recent_turns[:-self.safe_turns]:
            if turn.role == "tool" and turn.full_content:
                turn.full_content = None
                cleared += 1

        if cleared > 0:
            self._state.compression.micro_triggered = True
            self._record_compact_event("micro", 0, usage_before=usage_before)
            return True
        return False

    def _context_collapse(self) -> bool:
        """第三层压缩：ContextCollapse（旧 turn 合并为 summary）。

        触发条件：利用率 >= collapse_threshold（默认 80%）且本层未触发过。
        操作：把超出 safe 窗口的旧 turn 合并为一条 role="system" 的 summary turn，
              summary 内容包含主题与实体信息，由规则生成（非 LLM）。
        保护规则：最近 safe_turns 条 turn 保留原样。
        """
        if self._state.compression.collapse_triggered:
            return False

        usage = self._state.token_stats.usage_pct
        if usage < self.collapse_threshold:
            return False

        # turn 数量不足时无需折叠
        if len(self._state.recent_turns) <= self.safe_turns:
            return False

        old_turns = self._state.recent_turns[:-self.safe_turns]
        kept_turns = self._state.recent_turns[-self.safe_turns:]

        # 从被折叠的旧 turn 中聚合主题与实体信息
        topics: set[str] = set()
        entities: list[str] = []
        seen_entities: set[str] = set()
        for turn in old_turns:
            text = turn.full_content or turn.content_preview or ""
            lowered = text.lower()
            if "weather" in lowered or "天气" in text:
                topics.add("weather")
            if "calculate" in lowered or "计算" in text:
                topics.add("math")
            if "write" in lowered or "写文件" in text or "edit_file" in lowered:
                topics.add("file_edit")
            # 提取引号包裹的实体（中英文引号均支持）
            for match in re.findall(r"['\"](.*?)['\"]", text):
                if match not in seen_entities:
                    seen_entities.add(match)
                    entities.append(match)

        # 实体只保留前 5 个，避免 summary 过长
        entities = entities[:5]

        summary_text = (
            f"[Summary of turns {old_turns[0].turn_id}-{old_turns[-1].turn_id}] "
            f"Topics: {', '.join(topics) or 'none'}. "
            f"Entities: {', '.join(entities) or 'none'}."
        )
        summary_turn = TurnSummary(
            turn_id=old_turns[-1].turn_id,
            role="system",
            content_preview=self._make_preview(summary_text),
            full_content=summary_text,
            timestamp=datetime.now(),
        )

        # 用 summary turn 替换所有旧 turn，最近 safe_turns 条保持原样
        self._state.recent_turns = [summary_turn] + kept_turns
        self._state.compression.collapse_triggered = True
        self._record_compact_event("collapse", len(old_turns), usage_before=usage)
        return True

    def _auto_compact(self) -> bool:
        """第四层压缩：AutoCompact（预留 stub，不调用 LLM）。

        触发条件：利用率 >= auto_threshold（默认 90%）且本层未触发过。
        操作：仅记录事件并返回标记，不执行实际压缩。
        原因：当前 Model 是 stub，无真实 LLM 可用于摘要生成。
        未来接入 LLM adapter 后，可在此实现基于模型的智能压缩。
        """
        if self._state.compression.auto_triggered:
            return False

        usage = self._state.token_stats.usage_pct
        if usage < self.auto_threshold:
            return False

        self._state.compression.auto_triggered = True
        self._record_compact_event(
            "auto",
            0,
            usage_before=usage,
            notes="LLM compact not available in stub mode",
        )
        return True

    def _infer_topic(self, user_input: str, turn_id: int) -> TopicState:
        """从用户输入推断当前主题与意图。

        基于关键词匹配识别三类主题：
        - weather / 天气 → primary_topic="weather", intent="query"
        - calculate / 计算 → primary_topic="math", intent="compute"
        - write / 写文件 / edit → primary_topic="file_edit", intent="request"
        其他输入：沿用上一轮的 topic 状态（保持连续性）。

        同时从输入中提取引号包裹的实体作为 active_entities。
        """
        lowered = user_input.lower()

        if "weather" in lowered or "天气" in user_input:
            primary_topic = "weather"
            intent = "query"
        elif "calculate" in lowered or "计算" in user_input:
            primary_topic = "math"
            intent = "compute"
        elif "write" in lowered or "写文件" in user_input or "edit" in lowered:
            primary_topic = "file_edit"
            intent = "request"
        else:
            # 未识别到主题关键词，沿用上一轮状态
            current = self._state.topic
            return TopicState(
                primary_topic=current.primary_topic,
                intent=current.intent,
                active_entities=current.active_entities,
                last_updated_turn=current.last_updated_turn,
            )

        # 提取引号包裹的实体作为活跃实体
        quoted = re.findall(r"['\"](.*?)['\"]", user_input)

        return TopicState(
            primary_topic=primary_topic,
            intent=intent,
            active_entities=quoted,
            last_updated_turn=turn_id,
        )

    def update(self, user_input: str) -> ContextState:
        """记录一条 user turn 并更新状态，随后触发自动压缩。

        步骤：
        1. turn 计数器递增
        2. 创建 TurnSummary（保存 full_content 与 content_preview）
        3. 追加到 recent_turns 并按 max_recent_turns 截断
        4. 推断主题
        5. 重新计算 token 统计
        6. 运行四层压缩检查（按 snip→micro→collapse→auto 顺序）
        """
        self._turn_counter += 1

        turn = TurnSummary(
            turn_id=self._turn_counter,
            role="user",
            content_preview=self._make_preview(user_input),
            full_content=user_input,
            timestamp=datetime.now(),
        )
        self._state.recent_turns.append(turn)
        # 仅保留最近 max_recent_turns 条，避免列表无限增长
        self._state.recent_turns = self._state.recent_turns[-self.max_recent_turns :]

        self._state.topic = self._infer_topic(user_input, self._turn_counter)
        self._state.token_stats = self._compute_token_stats()
        self._run_compression()

        return self._state

    def _run_compression(self) -> None:
        """按顺序运行四层压缩检查。

        顺序：SnipCompact → MicroCompact → ContextCollapse → AutoCompact。
        每层触发后会重新计算 token_stats，让下一层基于最新利用率判断。
        每层有自身的触发标志位，已触发过的层不会重复执行。
        """
        for layer_method in (
            self._snip_compact,
            self._micro_compact,
            self._context_collapse,
            self._auto_compact,
        ):
            if layer_method():
                self._state.token_stats = self._compute_token_stats()

    def update_with_result(self, result: dict | str) -> ContextState:
        """记录一条 assistant 或 tool turn 并更新状态，随后触发自动压缩。

        - 当 result 是 dict 时，视为工具调用结果，创建 role="tool" 的 turn，
          并保存 ToolCallRecord；full_content 取 result_preview 或字符串化的 dict。
        - 当 result 是 str 时，视为模型回复，创建 role="assistant" 的 turn。
        """
        self._turn_counter += 1

        if isinstance(result, dict):
            # 工具结果：dict 中应包含 tool_name / params / result_preview
            result_preview = result.get("result_preview") or str(result)[:self.preview_length]
            full_result = result.get("result_preview") or str(result)
            tool_call = ToolCallRecord(
                tool_name=result.get("tool_name", "unknown"),
                params=result.get("params", {}),
                result_preview=result_preview,
            )
            turn = TurnSummary(
                turn_id=self._turn_counter,
                role="tool",
                content_preview=result_preview,
                full_content=full_result,
                tool_calls=[tool_call],
                timestamp=datetime.now(),
            )
        else:
            # 模型回复：字符串形式
            text = str(result)
            turn = TurnSummary(
                turn_id=self._turn_counter,
                role="assistant",
                content_preview=self._make_preview(text),
                full_content=text,
                timestamp=datetime.now(),
            )

        self._state.recent_turns.append(turn)
        self._state.recent_turns = self._state.recent_turns[-self.max_recent_turns :]
        self._state.token_stats = self._compute_token_stats()
        self._run_compression()

        return self._state

    def get(self) -> dict:
        """返回当前状态的 JSON 可序列化 dict。

        外部模块（Agent / Loop / Skill）通过此方法读取上下文，
        无需引入 Pydantic。返回的 dict 包含 recent_turns / topic /
        token_stats / compression / metadata 五个顶层字段。
        """
        return self._state.model_dump(mode="json")

    def compact(self, force: bool = False) -> ContextState:
        """手动触发压缩。

        - force=False：只执行当前阈值应触发的层（与自动逻辑相同）。
        - force=True：重置所有标志位并临时把阈值降为 0，强制依次执行所有层。
          AutoCompact 即使被强制也仍是 stub，不调用 LLM。
        force=True 的典型用途：调试或在低利用率下主动压缩。
        """
        if force:
            # 备份原始阈值，执行后恢复
            original_thresholds = {
                "snip": self.snip_threshold,
                "micro": self.micro_threshold,
                "collapse": self.collapse_threshold,
                "auto": self.auto_threshold,
            }
            self.reset_compression_flags()
            self.snip_threshold = 0.0
            self.micro_threshold = 0.0
            self.collapse_threshold = 0.0
            self.auto_threshold = 0.0
            try:
                self._run_compression()
            finally:
                # 无论是否异常都恢复原始阈值
                self.snip_threshold = original_thresholds["snip"]
                self.micro_threshold = original_thresholds["micro"]
                self.collapse_threshold = original_thresholds["collapse"]
                self.auto_threshold = original_thresholds["auto"]
        else:
            self._run_compression()
        return self._state

    def reset_compression_flags(self) -> None:
        """重置四层压缩的触发标志位。

        重置后，各层可在下次利用率达到阈值时再次触发。
        compact(force=True) 内部会调用此方法。
        """
        self._state.compression.snip_triggered = False
        self._state.compression.micro_triggered = False
        self._state.compression.collapse_triggered = False
        self._state.compression.auto_triggered = False

    def reset(self) -> None:
        """重置整个 Context 状态。

        清空 recent_turns、topic、token_stats、compression，
        并将 turn 计数器归零。用于开始全新对话。
        """
        self._state = ContextState()
        self._turn_counter = 0

    def snapshot(self) -> ContextState:
        """返回当前状态的深拷贝。

        调用方对返回对象的修改不会影响 Context 内部状态。
        用于调试、测试或在压缩前后对比状态。
        """
        return self._state.model_copy(deep=True)
