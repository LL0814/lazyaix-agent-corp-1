"""Tools 层的数据结构定义（dataclass，非外部 API 工具）。

本模块定义所有 Tool action 共用的数据结构，作为 Tools 层与 Skills 层之间的契约。

本文件提供的数据结构：
  ┌──────────────┬──────────────────────────────────────────────┐
  │ dataclass    │ 用途                                          │
  ├──────────────┼──────────────────────────────────────────────┤
  │ POI          │ 兴趣点（景点/餐厅/购物等）                    │
  │ Weather      │ 单日天气（气温/降水/描述）                    │
  │ Route        │ 路径（距离/时长/模式/步骤）                   │
  │ Hotel        │ 酒店（价格/评分/房型/设施）                   │
  │ Restaurant   │ 餐厅（菜系/人均/评分/特色菜）                 │
  │ Itinerary    │ 完整行程（多日计划 + 预算汇总 + 注意事项）    │
  └──────────────┴──────────────────────────────────────────────┘

使用 dataclass 而非 dict，便于 IDE 类型提示与静态类型检查。
"""

from dataclasses import dataclass, field
from typing import Literal


# ============ 数据结构 ============

@dataclass
class POI:
    """兴趣点（Point of Interest）。

    由 search_poi / get_nearby_poi 等 action 产生，
    是行程规划的基本单元。
    """
    name: str                       # 名称，如 "武侯祠"
    address: str                    # 地址
    lng: float                      # 经度
    lat: float                      # 纬度
    rating: float = 0.0             # 评分 0-5
    open_time: str = ""             # 开放时间，如 "08:00-18:00"
    intro: str = ""                 # 简介
    image_url: str = ""             # 图片链接
    poi_type: str = ""              # POI 类型，如 "景点" / "餐厅" / "购物"


@dataclass
class Weather:
    """单日天气。

    由 get_weather action 产生，用于行程规划时
    判断是否需要带伞、穿衣建议等。
    """
    date: str                       # 日期，"2026-07-01"
    temp_min: int                   # 最低温度（℃）
    temp_max: int                   # 最高温度（℃）
    condition: str                  # 天气状况，如 "晴" / "多云" / "小雨"
    precip_prob: int                # 降水概率 0-100
    wind: str                       # 风力，如 "微风" / "3-4级"
    clothing_advice: str            # 穿衣建议，如 "建议穿短袖，带薄外套"


@dataclass
class Route:
    """路线规划结果。

    由 calculate_route action 产生。
    distance/duration 用于时间预算校验，steps 用于行程展示。
    """
    distance: int                   # 总距离（米）
    duration: int                   # 预计用时（秒）
    mode: Literal["driving", "transit", "walking"] = "driving"
    steps: list[str] = field(default_factory=list)  # 分段描述


@dataclass
class Hotel:
    """酒店信息。

    由 search_hotel action 产生（练手阶段从静态 JSON 读取）。
    """
    name: str
    address: str
    price_per_night: int            # 每晚价格（元）
    rating: float
    room_type: str                  # 房型，如 "豪华大床房"
    facilities: list[str] = field(default_factory=list)  # 设施列表


@dataclass
class Restaurant:
    """餐厅信息。

    由 search_restaurant action 产生（练手阶段从静态 JSON 读取）。
    """
    name: str
    address: str
    cuisine: str                    # 菜系，如 "川菜" / "火锅"
    avg_price: int                  # 人均消费（元）
    rating: float
    signature_dishes: list[str] = field(default_factory=list)  # 特色菜
    open_time: str = ""             # 营业时间


@dataclass
class Itinerary:
    """完整行程方案。

    由 generate_itinerary action 产生，是 Tools 层最复杂的输出。
    Skill 层接收本结构后，可直接展示给用户或交给校验逻辑。

    每日安排（days 元素）结构：
    {
        "date": "2026-07-01",
        "pois": [POI, ...],            # 已按贪心最近邻排序
        "routes": [Route, ...],        # 各景点间路线（长度 = len(pois)-1）
        "lunch": Restaurant,           # 午餐推荐
        "dinner": Restaurant,          # 晚餐推荐
        "hotel": Hotel,                # 当晚住宿
        "timeline": ["09:00 出发前往A", "11:30 午餐", ...]
    }
    """
    destination: str                                  # 目的地
    days: list[dict] = field(default_factory=list)    # 每日安排
    budget_summary: dict = field(default_factory=dict)  # 预算汇总
    notes: list[str] = field(default_factory=list)    # 注意事项
