"""AI summarizer that decides which preference memory operations to run."""

from __future__ import annotations

import json
import re
from typing import Any

from .operations import MemoryOperation, parse_operations


class MemoryAgent:
    """Use the configured model as a small background memory agent."""

    def __init__(self, model: Any | None = None) -> None:
        self._model = model

    def summarize(
        self,
        user_input: str,
        current_memory: dict[str, str],
    ) -> list[MemoryOperation]:
        """Return memory operations inferred from the latest user message."""
        response = self._complete(self._build_prompt(user_input, current_memory))
        payload = self._extract_json(response)
        return parse_operations(payload)

    def _complete(self, prompt: str) -> str:
        model = self._model or self._load_default_model()
        if model is None:
            return ""
        complete = getattr(model, "complete", None)
        if not callable(complete):
            return ""
        return str(complete(prompt))

    def _load_default_model(self) -> Any | None:
        try:
            from models import Model
        except ImportError:
            return None
        self._model = Model()
        return self._model

    def _build_prompt(self, user_input: str, current_memory: dict[str, str]) -> str:
        memory_json = json.dumps(current_memory, ensure_ascii=False, indent=2)
        return f"""你是一个只管理用户偏好记忆的后台 Agent。

当前已有记忆是一个 JSON 对象，key 是偏好类别或者是情景（事情发生的时间地点人物背景），value 是用中文顿号/逗号连接的字符串：
{memory_json}

用户最新输入：
{user_input}

请判断这句话是否表达了稳定的用户偏好、偏好变化、偏好撤销或偏好纠正。

只允许输出 JSON，不要解释，不要 Markdown。格式必须是：
{{
  "operations": [
    {{"action": "append", "key": "like", "value": "吃苹果"}}
  ]
}}

可用 action：
- create：新增一个不存在的偏好 key或者情景（事情发生的时间地点人物背景）。
- append：给已有或可能已有的 key 追加偏好项，自动去重。
- update：当用户明确整体改写某个偏好类别时，替换整个 key 的 value。
- delete：当用户明确删除整类记忆时，删除整个 key。
- remove_item：当用户撤销、否认、不再具有某个已记住的偏好项时，只删除该项。
- replace_item：当用户纠正某个偏好或者情景（事情发生的时间地点人物背景）项时，把 old_value 替换成 new_value。

规则：
- 每次增删改查前，必须先完整阅读“当前已有记忆”，综合判断用户最新输入和所有本地用户偏好记忆之间的关系。
- 删除或替换记忆时必须基于完整已有偏好做类目分析：如果用户否定的是一个大类，要删除该大类下已经记录的所有相关具体项。
- 例如当前 like 同时有“吃苹果”和“吃昭通丑苹果”，用户说“我不喜欢吃苹果了”，因为“昭通丑苹果”也是苹果，所以应 remove_item “吃苹果，吃昭通丑苹果”。
- 如果用户只否定非常具体的子类，例如“我不喜欢吃昭通丑苹果了”，才只删除“吃昭通丑苹果”，不要删除“吃苹果”。
- 如果不确定某个已记录偏好是否属于用户否定的大类，宁可保守不删；但明显属于同一类的具体项必须一起删。
- 保存用户偏好，例如用户的信息,喜欢/不喜欢/爱吃/讨厌/偏好的语言、工具、风格等。
- 保存用户的基本信息,例如用户姓名，家庭住址和操作，例如用户今天写了一个python脚本或做过一些其他操作
- 不保存普通聊天历史，但可以保存情景记忆，比如事情发生的时间地点人物背景。
- 如果用户说“之前说过我喜欢吃苹果，现在不喜欢吃了”，应输出 remove_item，删除 like 里的“吃苹果”；不要自动新增 hate，除非用户明确说“讨厌/不喜欢”是稳定偏好。
- 如果没有任何需要记忆的偏好变化，输出 {{"operations": []}}。
- value 使用中文短语，例如“吃苹果”“Python”“简洁回答”，“用户让写了一个python脚本”，但是要保证记录的完整性包括事情发生的时间地点人物背景（这时候不需要简短，只需要精炼）。
"""

    def _extract_json(self, text: str) -> Any:
        stripped = text.strip()
        if not stripped:
            return {}

        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        fenced_match = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL)
        if fenced_match:
            try:
                return json.loads(fenced_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        object_match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if object_match:
            try:
                return json.loads(object_match.group(0))
            except json.JSONDecodeError:
                pass

        return {}
