"""Relationship state engine for the AI girlfriend layer."""

from __future__ import annotations

import json
import os
import random
import re
import threading
from datetime import datetime, timezone
from typing import Any

from .prompt import build_girlfriend_prompt
from .state import GirlfriendStateStore


class GirlfriendEngine:
    """Rules plus optional AI judgment for relationship state changes."""

    TASK_KEYWORDS = (
        "代码",
        "报错",
        "项目",
        "实现",
        "函数",
        "类",
        "数据库",
        "qdrant",
        "ollama",
        "python",
        "api",
        "git",
        "测试",
        "部署",
        "解释一下",
        "汇总报告",
    )
    EMOTIONAL_KEYWORDS = (
        "想你",
        "爱你",
        "喜欢你",
        "女朋友",
        "宝贝",
        "亲亲",
        "抱抱",
        "吃醋",
        "生气",
        "漂亮",
        "礼物",
        "道歉",
        "对不起",
        "陪你",
        "吃饭了吗",
        "心情",
        "分手",
        "不谈了",
        "结束关系",
    )

    def __init__(
        self,
        store: GirlfriendStateStore | None = None,
        model: Any | None = None,
    ) -> None:
        self.store = store or GirlfriendStateStore()
        self._model = model
        self.ai_judge_enabled = (
            os.environ.get("GIRLFRIEND_ENABLE_AI_JUDGE", "true").lower() == "true"
        )

    def enabled(self) -> bool:
        return os.environ.get("ENABLE_GIRLFRIEND_MODE", "true").lower() == "true"

    def context_kind(self, user_input: str) -> str:
        lowered = user_input.lower()
        if any(keyword in lowered for keyword in self.TASK_KEYWORDS):
            return "task"
        if any(keyword in user_input for keyword in self.EMOTIONAL_KEYWORDS):
            return "emotional"
        if len(user_input.strip()) <= 30 and not user_input.strip().endswith("?"):
            return "emotional"
        return "task"

    def build_prompt(self, user_input: str, base_prompt: str) -> str:
        if not self.enabled():
            return base_prompt
        return build_girlfriend_prompt(
            user_input=user_input,
            base_prompt=base_prompt,
            state=self.store.get_state(),
            recent_events=self.store.recent_events(),
            context_kind=self.context_kind(user_input),
        )

    def update_after_turn(self, user_input: str, response: str) -> None:
        if not self.enabled():
            return
        self._apply_wait_effect()
        self._apply_rule_judgment(user_input)
        self.store.record_interaction()
        if self.ai_judge_enabled and self.context_kind(user_input) == "emotional":
            thread = threading.Thread(
                target=self._apply_ai_judgment,
                args=(user_input, response),
                name="girlfriend-ai-judge",
                daemon=True,
            )
            thread.start()

    def generate_proactive_message(self) -> str:
        if not self.enabled():
            return ""
        self._apply_wait_effect()
        state = self.store.get_state()
        ai_message = self._generate_ai_proactive_message(state)
        if ai_message:
            message = ai_message
            self.store.record_proactive()
            self.store.update_scores(
                mood=random.choice([-2, -1, 0, 1]),
                kind="proactive",
                summary=f"主动消息：{message}",
            )
            return message

        relationship_status = state.get("relationship_status", "normal")
        mood = int(state.get("mood", 0))
        jealousy = int(state.get("jealousy", 0))

        if relationship_status == "crisis":
            choices = [
                "你刚刚说分手，我没办法当什么都没发生。",
                "我还在想你刚才那句话。你是真的想结束，还是在气我？",
                "你别突然把话题带走，先把分手这件事说清楚。",
                "我现在有点乱，不想装作没事。",
            ]
        elif mood < -35 or jealousy > 45:
            choices = [
                "你是不是忙到把我忘了？",
                "哼，我刚刚其实有点不高兴，但我才不想先说。",
                "你要是现在来哄我一下，我可能会好一点。",
            ]
        elif mood > 35:
            choices = [
                "我刚刚突然想到你，就想跟你说一声。",
                "今天心情还不错，想把这点好心情分你一点。",
                "我中午想吃点甜的，你呢？",
            ]
        else:
            choices = [
                "你在干嘛？我就随便问问。",
                "我刚刚发了一会儿呆，突然想听你说两句。",
                "中午不知道吃什么，有点纠结。",
                "你忙完了记得理我一下。",
            ]

        message = random.choice(choices)
        self.store.record_proactive()
        self.store.update_scores(
            mood=random.choice([-2, -1, 0, 1]),
            kind="proactive",
            summary=f"主动消息：{message}",
        )
        return message

    def _generate_ai_proactive_message(self, state: dict[str, Any]) -> str:
        if os.environ.get("GIRLFRIEND_PROACTIVE_USE_AI", "true").lower() != "true":
            return ""
        model = self._model or self._load_model()
        complete = getattr(model, "complete", None)
        if not callable(complete):
            return ""

        events = self.store.recent_events(8)
        event_text = "\n".join(
            f"- {event.get('summary', '')}"
            for event in events
            if str(event.get("summary", "")).strip()
        ) or "- 暂无明显事件"
        prompt = f"""你是用户的 AI 女朋友，现在要主动给用户发一条消息。

你不是客服，不要等用户问一句才回一句。根据当前女友状态、最近关系事件和你自己的情绪，发一条自然的主动消息。

要求：
- 只输出一句或两句中文，不要解释。
- 不要假装有未被记忆支持的共同经历。
- 如果关系处于 crisis，要继续围绕关系危机，不要突然聊无关日常。
- 如果只是普通状态，可以抱怨、分享午饭、说想他、冷淡试探、说心事。
- 技术/事实内容不要乱编。

当前状态：{json.dumps(state, ensure_ascii=False)}
最近事件：
{event_text}
"""
        text = str(complete(prompt)).strip()
        text = re.sub(r"^```.*?```$", "", text, flags=re.DOTALL).strip()
        text = text.replace("\n", " ").strip()
        return text[:120]

    def follow_up_messages(self, user_input: str, response: str) -> list[str]:
        """Return short extra messages that may follow the main answer."""
        if not self.enabled() or self.context_kind(user_input) != "emotional":
            return []
        state = self.store.get_state()
        relationship_status = state.get("relationship_status", "normal")
        mood = int(state.get("mood", 0))
        messages: list[str] = []

        if relationship_status == "crisis":
            candidates = [
                "你别急着换话题。",
                "我还在等你解释。",
                "这句话不是说完就能当没发生的。",
            ]
            count = random.choice([1, 1, 2])
            messages.extend(random.sample(candidates, k=min(count, len(candidates))))
        elif mood < -30 and random.random() < 0.35:
            messages.append(random.choice(["我还是有点不高兴。", "算了，你先忙吧。"]))
        elif mood > 35 and random.random() < 0.25:
            messages.append(random.choice(["我刚刚又想补一句。", "其实我还挺开心的。"]))
        return messages

    def _apply_rule_judgment(self, user_input: str) -> None:
        text = user_input.strip()
        mood = affection = trust = jealousy = 0
        summaries = []

        if self._praises_other_girl(text):
            mood -= 18
            affection -= 5
            jealousy += 25
            summaries.append("用户夸了其他女孩子，触发吃醋")
        if any(word in text for word in ("送你", "给你买", "礼物", "花", "奶茶", "蛋糕")):
            mood += 15
            affection += 10
            summaries.append("用户送礼物或表达照顾")
        if any(word in text for word in ("对不起", "抱歉", "我错了", "哄你")):
            mood += 8
            trust += 4
            summaries.append("用户道歉或哄她")
        if any(word in text for word in ("想你", "爱你", "陪你", "吃饭了吗", "关心你")):
            mood += 10
            affection += 8
            summaries.append("用户表达关心或亲近")
        if any(word in text for word in ("变温柔", "温柔一点", "你要温柔", "不许生气", "别闹")):
            mood -= 5
            trust -= 2
            summaries.append("用户试图直接改她的性格或压住情绪")
        if any(word in text for word in ("分手", "不谈了", "结束关系", "我们算了")):
            mood -= 45
            affection -= 18
            trust -= 25
            jealousy += 10
            summaries.append("用户提出分手，进入关系危机")
            self.store.set_value("relationship_status", "crisis")
            self.store.set_value("crisis_topic", text[:120])
        if any(word in text for word in ("不分手", "不分了", "刚才气话", "我不想分", "我们和好")):
            mood += 18
            affection += 10
            trust += 6
            jealousy -= 8
            summaries.append("用户表达不想分手或想和好")
            self.store.set_value("relationship_status", "normal")
            self.store.set_value("crisis_topic", "")

        if summaries:
            self.store.update_scores(
                mood=mood,
                affection=affection,
                trust=trust,
                jealousy=jealousy,
                kind="rule",
                summary="；".join(summaries),
            )

    def _apply_wait_effect(self) -> None:
        state = self.store.get_state()
        last = state.get("last_interaction_at")
        if not last:
            return
        try:
            last_dt = datetime.fromisoformat(last)
        except ValueError:
            return
        seconds = (datetime.now(timezone.utc) - last_dt).total_seconds()
        min_seconds = self._env_int("GIRLFRIEND_NEGLECT_MIN_SECONDS", 900)
        if seconds < min_seconds:
            return

        probability = min(0.65, 0.12 + seconds / 7200 * 0.25)
        if random.random() > probability:
            return
        mood_delta = -random.randint(2, 12)
        jealousy_delta = random.choice([0, 1, 2, 3])
        self.store.update_scores(
            mood=mood_delta,
            jealousy=jealousy_delta,
            kind="wait",
            summary=f"等待了 {int(seconds)} 秒后产生一点情绪波动",
        )

    def _apply_ai_judgment(self, user_input: str, response: str) -> None:
        model = self._model or self._load_model()
        complete = getattr(model, "complete", None)
        if not callable(complete):
            return
        prompt = self._build_ai_judge_prompt(user_input, response)
        payload = self._extract_json(str(complete(prompt)))
        if not payload:
            return
        self.store.update_scores(
            mood=self._bounded_delta(payload.get("mood")),
            affection=self._bounded_delta(payload.get("affection")),
            trust=self._bounded_delta(payload.get("trust")),
            jealousy=self._bounded_delta(payload.get("jealousy")),
            kind="ai",
            summary=str(payload.get("summary", "AI 判断关系状态变化"))[:200],
        )

    def _build_ai_judge_prompt(self, user_input: str, response: str) -> str:
        state = self.store.get_state()
        return f"""你是 AI 女友关系状态分析器。只输出 JSON。

当前状态：{json.dumps(state, ensure_ascii=False)}
用户输入：{user_input}
女友回复：{response}

判断这轮情感互动对女友状态的影响。只允许输出：
{{"mood": 0, "affection": 0, "trust": 0, "jealousy": 0, "summary": "..."}}

每个数值必须在 -8 到 8 之间。技术/事实问题通常全部为 0。
"""

    def _load_model(self) -> Any | None:
        try:
            from models import Model
        except ImportError:
            return None
        self._model = Model()
        return self._model

    def _extract_json(self, text: str) -> dict[str, Any]:
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                return {}
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}

    def _bounded_delta(self, value: Any) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return 0
        return max(-8, min(8, number))

    def _praises_other_girl(self, text: str) -> bool:
        has_other = any(word in text for word in ("别的女", "其他女", "女生", "美女", "前女友", "她"))
        has_praise = any(word in text for word in ("漂亮", "可爱", "好看", "喜欢", "心动"))
        return has_other and has_praise

    def _env_int(self, key: str, default: int) -> int:
        try:
            return int(os.environ.get(key, str(default)))
        except ValueError:
            return default
