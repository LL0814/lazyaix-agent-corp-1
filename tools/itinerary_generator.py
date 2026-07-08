"""行程生成编排逻辑（Tools 层最复杂的部分）。

整合所有底层工具的结果，组装成完整的 Itinerary 对象。
由 Tool._generate_itinerary 调用，不直接对外暴露。

本文件提供的工具：
  ┌──────────────────────┬──────────────────────────────────────────────┐
  │ 函数                  │ 作用                                          │
  ├──────────────────────┼──────────────────────────────────────────────┤
  │ generate              │ 【主入口】生成完整行程方案                     │
  │ _search_hotels        │ 搜索酒店（优先百度 API，失败回退本地 JSON）    │
  │ _search_restaurants   │ 搜索餐厅（优先百度 API，失败回退本地 JSON）    │
  │ _search_hotels_local  │ 本地 JSON 酒店兜底数据                        │
  │ _search_restaurants_local │ 本地 JSON 餐厅兜底数据                    │
  │ _estimate_transport_cost │ 估算交通费用（驾车 1 元/公里）             │
  │ _build_timeline       │ 生成每日时间线                                │
  │ _build_notes          │ 生成行程注意事项                              │
  └──────────────────────┴──────────────────────────────────────────────┘

generate() 内部编排的底层工具链：
  1. amap_client.search_poi          → 景点列表
  2. openmeteo_client.get_weather    → 天气预报
  3. route_optimizer.greedy_nearest_neighbor → 景点排序
  4. amap_client.calculate_route     → 相邻景点驾车路线
  5. baidu_client.search_hotel       → 酒店列表（失败回退本地 JSON）
  6. baidu_client.search_restaurant  → 餐厅列表（失败回退本地 JSON）
  → 组装 Itinerary（含预算汇总 + 注意事项）
"""

import logging
import datetime as dt
from typing import Literal

from . import amap_client, baidu_client, openmeteo_client
from .models import POI, Route, Hotel, Restaurant, Itinerary
from .route_optimizer import greedy_nearest_neighbor

logger = logging.getLogger(__name__)

# 预算级别 → 每日住宿上限（元/晚）
BUDGET_HOTEL_LIMIT = {"low": 400, "mid": 800, "high": 2000}
# 预算级别 → 每日餐饮上限（人均）
BUDGET_MEAL_LIMIT = {"low": 50, "mid": 100, "high": 300}
# 预算级别 → 价格缺失时的默认估算值
DEFAULT_HOTEL_PRICE = {"low": 200, "mid": 400, "high": 800}
DEFAULT_MEAL_PRICE = {"low": 40, "mid": 80, "high": 200}
# 每日推荐景点数
POIS_PER_DAY = 3
# 假设游览时长（小时）
VISIT_HOURS = 2
# 每日游览开始时间
DAY_START_HOUR = 9


def generate(destination: str,
             days: int,
             budget_level: Literal["low", "mid", "high"] = "mid",
             preferences: str = "") -> Itinerary:
    """生成完整行程方案。

    流程：
      1. search_poi 获取景点
      2. geocode 补全景点坐标（高德 search_poi 已返回坐标，通常无需再调）
      3. 按天分配景点
      4. 每日贪心最近邻排序
      5. calculate_route 计算相邻景点路线
      6. get_weather 获取天气
      7. search_hotel / search_restaurant 获取住宿餐饮
      8. 组装 Itinerary + 预算汇总
    """
    # ===== 1. 获取景点 =====
    # 把 preferences 作为 keyword 提高相关性
    keyword = preferences if preferences else ""
    all_pois = amap_client.search_poi(
        city=destination, poi_type="景点", keyword=keyword,
        limit=days * POIS_PER_DAY + 2,  # 多取几个备用
    )
    if not all_pois:
        logger.warning("目的地 %s 未找到景点", destination)
        all_pois = []
    else:
        logger.info("目的地 %s 获取到 %d 个景点，计划 %d 天", destination, len(all_pois), days)

    # ===== 2. 获取天气 =====
    # 天气天数覆盖行程天数，避免长行程后期没有天气数据
    weather_days = min(max(days, 7), 16)
    weathers = openmeteo_client.get_weather(city=destination, days=weather_days)

    # ===== 3. 获取住宿 =====
    # 优先调用百度 Place API（真实数据），失败时函数内部回退本地 JSON
    hotels = _search_hotels(destination, budget_level)

    # ===== 4. 获取餐厅 =====
    # 优先调用百度 Place API（真实数据），失败时函数内部回退本地 JSON
    restaurants = _search_restaurants(destination, budget_level)

    # ===== 5. 按天组装 =====
    today = dt.date.today()
    days_plan: list[dict] = []
    total_cost = {"accommodation": 0, "food": 0, "transport": 0, "tickets": 0}

    # 景点不足时自动分配：优先保证覆盖全部天数
    distributed = _distribute_pois(all_pois, days, POIS_PER_DAY)

    for day_idx in range(days):
        date = today + dt.timedelta(days=day_idx)
        day_pois = distributed[day_idx]
        if not day_pois:
            logger.warning("第 %d 天没有可用景点，停止生成后续天数", day_idx + 1)
            break

        # 5.1 贪心最近邻排序
        ordered_pois = greedy_nearest_neighbor(day_pois)

        # 5.2 计算相邻景点路线
        routes: list[Route] = []
        for i in range(len(ordered_pois) - 1):
            p1, p2 = ordered_pois[i], ordered_pois[i + 1]
            r = amap_client.calculate_route(
                origin=f"{p1.lng},{p1.lat}",
                destination=f"{p2.lng},{p2.lat}",
                mode="driving",
            )
            if r:
                routes.append(r)
                total_cost["transport"] += _estimate_transport_cost(r)

        # 5.3 选餐厅（午餐、晚餐）
        lunch = restaurants[day_idx % len(restaurants)] if restaurants else None
        dinner = restaurants[(day_idx + 1) % len(restaurants)] if restaurants else None
        if lunch:
            total_cost["food"] += lunch.avg_price
        if dinner:
            total_cost["food"] += dinner.avg_price

        # 5.4 选住宿（最后一晚不需要）
        hotel = hotels[day_idx % len(hotels)] if hotels and day_idx < days - 1 else None
        if hotel:
            total_cost["accommodation"] += hotel.price_per_night

        # 5.5 门票估算（无真实数据，按 50 元/景点）
        total_cost["tickets"] += len(ordered_pois) * 50

        # 5.6 生成时间线
        timeline = _build_timeline(ordered_pois, routes, lunch, dinner)

        # 5.7 当日天气
        day_weather = next(
            (w for w in weathers if w.date == date.isoformat()), None
        )

        days_plan.append({
            "date": date.isoformat(),
            "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][date.weekday()],
            "pois": ordered_pois,
            "routes": routes,
            "lunch": lunch,
            "dinner": dinner,
            "hotel": hotel,
            "timeline": timeline,
            "weather": day_weather,
        })

    # ===== 6. 预算汇总 =====
    budget_summary = {
        "accommodation": total_cost["accommodation"],
        "food": total_cost["food"],
        "transport": total_cost["transport"],
        "tickets": total_cost["tickets"],
        "total": sum(total_cost.values()),
        "daily_avg": sum(total_cost.values()) / days if days else 0,
        "level": budget_level,
    }

    # ===== 7. 注意事项 =====
    notes = _build_notes(weathers, days_plan, requested_days=days)

    return Itinerary(
        destination=destination,
        days=days_plan,
        budget_summary=budget_summary,
        notes=notes,
    )


# ============ 辅助函数 ============

def _estimate_transport_cost(route: Route) -> int:
    """估算交通费用（元）。

    驾车按 1 元/公里，公交按 2 元/次起步，步行免费。
    练手简化，不接真实油价/票价。
    """
    if route.mode == "walking":
        return 0
    if route.mode == "transit":
        return 5
    # driving：1 元/公里，至少 10 元起步
    return max(10, route.distance // 1000)


def _build_timeline(pois: list[POI], routes: list[Route],
                    lunch: Restaurant | None, dinner: Restaurant | None) -> list[str]:
    """构建当日时间线。

    时间从 DAY_START_HOUR（9:00）开始累加，
    若超出 22:00 则截断并提示"时间已晚"。
    """
    timeline: list[str] = []
    current_hour = DAY_START_HOUR
    MAX_HOUR = 22  # 当日最晚安排到 22:00

    for i, poi in enumerate(pois):
        # 到达景点
        timeline.append(f"{current_hour:02d}:00 到达 {poi.name}")
        # 游览
        current_hour += VISIT_HOURS
        if current_hour > MAX_HOUR:
            timeline.append(f"{current_hour:02d}:00 离开 {poi.name}（时间已晚，建议结束当日行程）")
            break
        timeline.append(f"{current_hour:02d}:00 离开 {poi.name}")

        # 午餐：第 1 个景点之后
        if i == 0 and lunch:
            current_hour += 1
            timeline.append(f"{current_hour:02d}:00 午餐：{lunch.name}（{lunch.cuisine}，人均{lunch.avg_price}元）")
            current_hour += 1

        # 去下一个景点
        if i < len(routes):
            travel_hours = max(1, routes[i].duration // 3600)
            current_hour += travel_hours
            if current_hour > MAX_HOUR:
                timeline.append(f"时间已晚（{current_hour:02d}:00），剩余景点建议安排到次日")
                break
            timeline.append(f"{current_hour:02d}:00 前往下一景点（约{travel_hours}小时）")

    # 晚餐
    if dinner:
        current_hour = max(current_hour, 18)
        if current_hour <= MAX_HOUR:
            timeline.append(f"{current_hour:02d}:00 晚餐：{dinner.name}（{dinner.cuisine}，人均{dinner.avg_price}元）")

    return timeline


def _build_notes(weathers, days_plan: list[dict], requested_days: int = 0) -> list[str]:
    """根据天气和行程生成注意事项。"""
    notes: list[str] = []
    rainy_days = [w for w in weathers if "雨" in w.condition]
    if rainy_days:
        notes.append(f"未来 {len(rainy_days)} 天有降雨，建议携带雨具")
    cold_days = [w for w in weathers if w.temp_max < 10]
    if cold_days:
        notes.append("有低温天气，注意保暖")
    notes.append("景点门票价格为估算，实际以景区公告为准")
    notes.append("交通时间受实时路况影响，建议预留缓冲")
    if requested_days and len(days_plan) < requested_days:
        notes.append(f"目的地可用景点有限，实际行程按 {len(days_plan)} 天展示")
    return notes


def _distribute_pois(all_pois: list[POI], days: int, pois_per_day: int) -> list[list[POI]]:
    """将景点分配到每一天。

    规则：
      - 景点充足时，每天固定 pois_per_day 个。
      - 景点不足但 >= 天数时，平均分配，每天至少 1 个。
      - 景点极少时，循环复用已有景点，保证覆盖全部天数。
    """
    result: list[list[POI]] = []
    total = len(all_pois)
    if total == 0:
        return [[] for _ in range(days)]

    if total >= days * pois_per_day:
        idx = 0
        for _ in range(days):
            result.append(all_pois[idx:idx + pois_per_day])
            idx += pois_per_day
        return result

    if total >= days:
        base, extra = divmod(total, days)
        idx = 0
        for i in range(days):
            count = base + (1 if i < extra else 0)
            result.append(all_pois[idx:idx + count])
            idx += count
        return result

    # 景点极少：循环复用
    idx = 0
    for _ in range(days):
        day_pois = []
        for _ in range(pois_per_day):
            day_pois.append(all_pois[idx % total])
            idx += 1
        result.append(day_pois)
    return result


# ============ 酒店与餐厅搜索 ============

def _search_hotels(city: str, budget_level: str) -> list[Hotel]:
    """搜索酒店。

    优先调用百度地图 Place API（真实数据），失败时回退本地 JSON。
    百度价格缺失时按预算级别估算默认值。
    """
    price_max = BUDGET_HOTEL_LIMIT.get(budget_level, 800)
    default_price = DEFAULT_HOTEL_PRICE.get(budget_level, 400)

    # 优先：百度地图 Place API
    hotels = baidu_client.search_hotel(city, limit=20)
    if hotels:
        # 价格缺失时按预算级别估算
        for h in hotels:
            if h.price_per_night == 0:
                h.price_per_night = default_price
        # 按预算上限过滤 + 评分降序
        filtered = [h for h in hotels if h.price_per_night <= price_max]
        filtered.sort(key=lambda h: h.rating, reverse=True)
        logger.info("百度 Place 返回 %d 家酒店，预算内 %d 家", len(hotels), len(filtered))
        return filtered or hotels

    # 回退：本地静态 JSON
    logger.info("百度 API 无结果，回退本地 JSON")
    return _search_hotels_local(city, price_max)


def _search_restaurants(city: str, budget_level: str) -> list[Restaurant]:
    """搜索餐厅。

    优先调用百度地图 Place API（真实数据），失败时回退本地 JSON。
    百度价格缺失时按预算级别估算默认值。
    """
    price_max = BUDGET_MEAL_LIMIT.get(budget_level, 100)
    default_price = DEFAULT_MEAL_PRICE.get(budget_level, 80)

    # 优先：百度地图 Place API
    restaurants = baidu_client.search_restaurant(city, limit=20)
    if restaurants:
        # 价格缺失时按预算级别估算
        for r in restaurants:
            if r.avg_price == 0:
                r.avg_price = default_price
        # 按预算上限过滤 + 评分降序
        filtered = [r for r in restaurants if r.avg_price <= price_max]
        filtered.sort(key=lambda r: r.rating, reverse=True)
        logger.info("百度 Place 返回 %d 家餐厅，预算内 %d 家", len(restaurants), len(filtered))
        return filtered or restaurants

    # 回退：本地静态 JSON
    logger.info("百度 API 无结果，回退本地 JSON")
    return _search_restaurants_local(city, price_max)


# ============ 本地静态 JSON（兜底数据） ============

def _search_hotels_local(city: str, price_max: int) -> list[Hotel]:
    """从本地静态 JSON 加载酒店数据（兜底用）。"""
    import json
    import os

    city_key = _city_to_pinyin_key(city)
    data_path = os.path.join(os.path.dirname(__file__), "data", f"hotels_{city_key}.json")
    if not os.path.exists(data_path):
        logger.warning("未找到 %s 的酒店兜底数据: %s", city, data_path)
        return []

    try:
        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取酒店数据失败: %s", e)
        return []

    hotels = [Hotel(**item) for item in data]
    filtered = [h for h in hotels if h.price_per_night <= price_max]
    filtered.sort(key=lambda h: h.rating, reverse=True)
    return filtered or hotels


def _search_restaurants_local(city: str, price_max: int) -> list[Restaurant]:
    """从本地静态 JSON 加载餐厅数据（兜底用）。"""
    import json
    import os

    city_key = _city_to_pinyin_key(city)
    data_path = os.path.join(os.path.dirname(__file__), "data", f"restaurants_{city_key}.json")
    if not os.path.exists(data_path):
        logger.warning("未找到 %s 的餐厅兜底数据: %s", city, data_path)
        return []

    try:
        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取餐厅数据失败: %s", e)
        return []

    restaurants = [Restaurant(**item) for item in data]
    filtered = [r for r in restaurants if r.avg_price <= price_max]
    filtered.sort(key=lambda r: r.rating, reverse=True)
    return filtered or restaurants


# 城市名 → 拼音 key 映射（兜底数据用）
_CITY_PINYIN_MAP = {
    "成都": "chengdu",
    "成都市": "chengdu",
    "北京": "beijing",
    "北京市": "beijing",
}


def _city_to_pinyin_key(city: str) -> str:
    """城市名 → 拼音 key。未映射的城市返回原字符串（小写）。"""
    return _CITY_PINYIN_MAP.get(city, city.lower())
