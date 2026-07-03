"""Tool 模块主类：统一入口 + action 分发。

对外只暴露 Tool 类，内部按 action 字符串分发到具体实现。
符合项目 agent.py 的接口约定：Tool.execute(action, params)。

本文件提供的工具（以 action 名暴露给 Agent / Skills 层）：
  ┌─────────────────────┬────────────────────────────────┬──────────────────────┐
  │ action              │ 作用                            │ 底层实现              │
  ├─────────────────────┼────────────────────────────────┼──────────────────────┤
  │ search_poi          │ 搜索景点/POI                    │ amap_client          │
  │ get_weather         │ 获取天气预报                    │ openmeteo_client     │
  │ geocode             │ 地址 ↔ 经纬度互转               │ amap_client          │
  │ calculate_route     │ 路径规划（驾车/步行/公交）       │ amap_client          │
  │ search_hotel        │ 搜索酒店                        │ baidu_client + 本地JSON│
  │ search_restaurant   │ 搜索餐厅                        │ baidu_client + 本地JSON│
  │ generate_itinerary  │ 生成完整行程（编排以上 6 个工具）│ itinerary_generator   │
  └─────────────────────┴────────────────────────────────┴──────────────────────┘

调用关系：
  Agent → Tool.execute(action, params) → 具体客户端模块 → 外部 API
"""

import logging
from typing import Any, Literal

from . import amap_client, openmeteo_client
from . import itinerary_generator
from .models import POI, Weather, Route, Hotel, Restaurant, Itinerary

logger = logging.getLogger(__name__)


class Tool:
    """Tool 统一入口类。

    被 Agent.process_turn 调用：
        result = self.tool.execute(decision["tool"], decision["params"])
    """

    def execute(self, action: str, params: dict) -> Any:
        """统一入口，按 action 分发到具体实现。

        Args:
            action: 工具动作名（如 "search_poi"）
            params: 参数字典（如 {"city": "成都", "poi_type": "景点"}）

        Returns:
            各 action 对应的返回值（POI 列表 / Weather 列表 / Itinerary 等）。
            调用失败时返回空列表或 None，不抛异常。
        """
        dispatch = {
            "search_poi": self._search_poi,
            "get_weather": self._get_weather,
            "geocode": self._geocode,
            "calculate_route": self._calculate_route,
            "search_hotel": self._search_hotel,
            "search_restaurant": self._search_restaurant,
            "generate_itinerary": self._generate_itinerary,
        }

        handler = dispatch.get(action)
        if not handler:
            logger.warning("未知 action: %s", action)
            return {"error": f"未知 action: {action}"}

        try:
            return handler(**params)
        except TypeError as e:
            logger.warning("action=%s 参数错误: %s | params=%s", action, e, params)
            return {"error": f"参数错误: {e}"}
        except Exception as e:  # noqa: BLE001
            logger.exception("action=%s 执行异常: %s", action, e)
            return {"error": str(e)}

    # ============ 真实 API 类 ============

    def _search_poi(self, city: str, poi_type: str = "",
                    keyword: str = "", limit: int = 10) -> list[POI]:
        """搜索景点、餐厅等兴趣点。

        Args:
            city: 城市/区域名
            poi_type: POI 类型（景点/餐厅/购物等）
            keyword: 关键词（可选）
            limit: 返回数量上限
        """
        return amap_client.search_poi(
            city=city, poi_type=poi_type, keyword=keyword, limit=limit,
        )

    def _get_weather(self, city: str = "", location: str = "",
                     days: int = 7) -> list[Weather]:
        """获取未来 7 天天气预报。

        Args:
            city: 城市名（与 location 二选一）
            location: "经度,纬度"（优先）
            days: 返回天数，最大 16
        """
        return openmeteo_client.get_weather(
            location=location, city=city, days=days,
        )

    def _geocode(self, address: str = "", location: str = "") -> dict | str | None:
        """地址 ↔ 经纬度互转。

        Args:
            address: 地址字符串（地址→坐标）
            location: "经度,纬度"（坐标→地址）
        """
        return amap_client.geocode(address=address, location=location)

    def _calculate_route(self, origin: str, destination: str,
                         mode: Literal["driving", "transit", "walking"] = "driving",
                         city: str = "",
                         ) -> Route | None:
        """路径规划。

        Args:
            origin: 起点坐标 "lng,lat"
            destination: 终点坐标 "lng,lat"
            mode: 出行方式
            city: 起点城市名（transit 模式必需）
        """
        return amap_client.calculate_route(
            origin=origin, destination=destination, mode=mode, city=city,
        )

    # ============ 模拟数据类 ============

    def _search_hotel(self, city: str, checkin: str = "", checkout: str = "",
                      price_min: int = 0, price_max: int = 99999,
                      star: int | None = None, limit: int = 5) -> list[Hotel]:
        """搜索酒店（练手阶段从本地静态 JSON 读取）。

        Args:
            city: 城市名
            checkin: 入住日期（练手阶段不参与筛选，仅记录）
            checkout: 离店日期
            price_min: 最低价格/晚
            price_max: 最高价格/晚
            star: 星级要求（可选）
            limit: 返回数量上限
        """
        hotels = itinerary_generator._search_hotels_local(city, price_max)
        # 价格下限过滤
        hotels = [h for h in hotels if h.price_per_night >= price_min]
        return hotels[:limit]

    def _search_restaurant(self, city: str, cuisine: str = "",
                           price_max: int | None = None,
                           rating_min: float = 0.0,
                           limit: int = 5) -> list[Restaurant]:
        """搜索餐厅（练手阶段从本地静态 JSON 读取）。

        Args:
            city: 城市名
            cuisine: 菜系（可选）
            price_max: 人均上限（可选）
            rating_min: 最低评分
            limit: 返回数量上限
        """
        # _search_restaurants_local 用 BUDGET_MEAL_LIMIT 作为 price_max，
        # 这里再按用户传入的 price_max 二次过滤
        restaurants = itinerary_generator._search_restaurants_local(
            city, price_max or 99999,
        )
        if cuisine:
            restaurants = [r for r in restaurants if cuisine in r.cuisine]
        restaurants = [r for r in restaurants if r.rating >= rating_min]
        return restaurants[:limit]

    # ============ 内部编排类 ============

    def _generate_itinerary(self, destination: str, days: int,
                            budget_level: Literal["low", "mid", "high"] = "mid",
                            preferences: str = "") -> Itinerary:
        """生成完整行程方案（含贪心路线优化 + 预算汇总）。

        Args:
            destination: 目的地
            days: 天数
            budget_level: 预算级别 low/mid/high
            preferences: 偏好（可选，如 "喜欢自然风光"）
        """
        return itinerary_generator.generate(
            destination=destination,
            days=days,
            budget_level=budget_level,
            preferences=preferences,
        )
