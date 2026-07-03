"""槽位提取器（基于规则匹配）。

从用户自然语言输入中提取旅需槽位：
  - destination: 目的地（城市/省份）
  - days: 天数
  - budget: 预算总额（元）+ 预算级别
  - preferences: 偏好

练手项目采用基于规则的提取（正则 + 关键词匹配），
不依赖 LLM，保证可离线测试。
"""

import re
from .models import UserRequirement

# ============ 目的地识别 ============

KNOWN_DESTINATIONS = {
    "成都", "北京", "上海", "广州", "深圳", "杭州", "南京", "西安",
    "重庆", "昆明", "大理", "丽江", "拉萨", "厦门", "青岛", "大连",
    "苏州", "桂林", "三亚", "海口", "长沙", "武汉", "天津", "哈尔滨",
    "云南", "四川", "西藏", "海南", "贵州", "甘肃", "青海", "新疆",
    # 江浙及华东
    "镇江", "扬州", "无锡", "常州", "南通", "徐州", "盐城", "连云港",
    "淮安", "泰州", "宿迁", "嘉兴", "湖州", "绍兴", "宁波", "温州",
    "金华", "台州", "黄山", "芜湖", "合肥", "安庆", "九江", "南昌",
}


def _extract_destination(text: str) -> str | None:
    pattern = r"(?:去|到|飞|想去|要去|到|前往|游)\s*([\u4e00-\u9fa5]{2,4})"
    matches = re.findall(pattern, text)
    for m in matches:
        if m in KNOWN_DESTINATIONS:
            return m
    for dest in KNOWN_DESTINATIONS:
        if dest in text:
            return dest
    return None


def _extract_days(text: str) -> int | None:
    cn_num = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    match = re.search(r"(\d+)\s*(?:天|日|号)", text)
    if match:
        return int(match.group(1))
    match = re.search(r"([一二两三四五六七八九十])\s*(?:天|日)", text)
    if match:
        return cn_num.get(match.group(1))
    return None


def _extract_budget(text: str) -> tuple[int | None, str]:
    budget: int | None = None
    level = "mid"
    if "穷游" in text or "便宜" in text or "省钱" in text:
        level = "low"
    elif "豪华" in text or "高端" in text or "奢侈" in text:
        level = "high"
    elif "舒适" in text:
        level = "mid"
    match = re.search(r"(\d{2,6})\s*(?:元|块钱|块)", text)
    if match:
        budget = int(match.group(1))
    match = re.search(r"预算\s*(\d{2,6})", text)
    if match:
        budget = int(match.group(1))
    match = re.search(r"(\d)\s*千", text)
    if match:
        budget = int(match.group(1)) * 1000
    match = re.search(r"(\d)\s*万", text)
    if match:
        budget = int(match.group(1)) * 10000
    # 英文缩写：1k=1000, 2w=20000（大小写不敏感，支持多位数如 10k=10000）
    match = re.search(r"(\d+)\s*k", text, re.IGNORECASE)
    if match:
        budget = int(match.group(1)) * 1000
    match = re.search(r"(\d+)\s*w", text, re.IGNORECASE)
    if match:
        budget = int(match.group(1)) * 10000
    if budget is not None:
        if budget < 2000:
            level = "low"
        elif budget > 8000:
            level = "high"
        else:
            level = "mid"
    return budget, level


PREFERENCE_KEYWORDS = {
    "自然风光": ["自然", "风景", "山水", "湖", "海", "山", "草原", "森林"],
    "人文历史": ["历史", "人文", "古迹", "博物馆", "古", "文化", "寺庙"],
    "美食": ["美食", "吃", "小吃", "好吃", "特色菜", "火锅"],
    "购物": ["购物", "买", "逛街", "商场"],
    "摄影": ["拍照", "摄影", "打卡", "网红"],
    "亲子": ["亲子", "家庭", "孩子", "小孩", "带娃"],
    "户外": ["户外", "徒步", "爬山", "骑行", "探险"],
}


def _extract_preferences(text: str) -> str | None:
    matched = []
    for pref, keywords in PREFERENCE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            matched.append(pref)
    return ", ".join(matched) if matched else None


def extract(text: str) -> UserRequirement:
    """从用户输入提取完整需求。缺失的槽位为 None。"""
    budget, level = _extract_budget(text)
    return UserRequirement(
        destination=_extract_destination(text),
        days=_extract_days(text),
        budget=budget,
        budget_level=level,
        preferences=_extract_preferences(text),
    )
