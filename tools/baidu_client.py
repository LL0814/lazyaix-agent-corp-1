"""百度地图 Place API 客户端。

替代静态 JSON 模拟数据，获取真实的酒店/餐厅信息。
文档：https://lbsyun.baidu.com/index.php?title=webapi/guide/webservice-placeapi

本文件提供的工具函数（被 itinerary_generator 调用）：
  ┌────────────────────┬────────────────────────────────┬────────────────────────┐
  │ 函数                │ 作用                            │ 数据来源                │
  ├────────────────────┼────────────────────────────────┼────────────────────────┤
  │ search_hotel        │ 搜索酒店（真实商户）             │ 百度 Place API          │
  │ search_restaurant   │ 搜索餐厅（真实商户）             │ 百度 Place API          │
  └────────────────────┴────────────────────────────────┴────────────────────────┘

字段映射：
  - name/address/location → 直接映射
  - detail_info.overall_rating → rating
  - detail_info.price → price_per_night（酒店）/ avg_price（餐厅）
  - detail_info.tag → cuisine（餐厅，解析 "美食;中餐厅" → "中餐厅"）

注意：
  1. 百度坐标为 BD09 坐标系，高德为 GCJ02。
     混用会有几百米偏差，对练手项目的路径规划可接受。
  2. 百度 detail_info.price 字段部分商户缺失（实测大连酒店缺失率 85%），
     缺失时由调用方 itinerary_generator 按预算级别估算。
  3. API Key 通过环境变量 BAIDU_MAP_AK 配置；失败时由调用方回退本地 JSON。
"""

import logging
import os

from .http_client import http_get
from .models import Hotel, Restaurant

logger = logging.getLogger(__name__)

BAIDU_PLACE_URL = "https://api.map.baidu.com/place/v2/search"


def _get_ak() -> str:
    """从环境变量读取百度地图 AK。"""
    return os.environ.get("BAIDU_MAP_AK", "")


def _parse_rating(detail: dict) -> float:
    """解析评分。百度返回字符串如 "4.7"，转 float。失败返回 0.0。"""
    try:
        return float(detail.get("overall_rating", 0))
    except (ValueError, TypeError):
        return 0.0


def _parse_price(detail: dict) -> int:
    """解析价格。百度返回字符串如 "71.5"，转 int（取整）。缺失返回 0。"""
    try:
        p = detail.get("price")
        if p is None or p == "-":
            return 0
        return int(round(float(p)))
    except (ValueError, TypeError):
        return 0


def _parse_cuisine(tag: str) -> str:
    """从百度 tag 字段解析菜系。

    百度 tag 格式如 "美食;中餐厅" / "美食;火锅" / "美食;小吃快餐店"
    取分号后部分，去掉"店"字简化。
    """
    if not tag:
        return "中餐"
    parts = tag.split(";")
    if len(parts) >= 2:
        cuisine = parts[-1].replace("店", "")
        return cuisine or "中餐"
    return tag


# ============ 酒店搜索 ============

def search_hotel(city: str, limit: int = 10) -> list[Hotel]:
    """搜索酒店（真实数据）。

    Args:
        city: 城市名，如 "成都"
        limit: 返回数量上限

    Returns:
        Hotel 列表。price_per_night 缺失时为 0（由调用方按预算级别估算）。
        失败时返回空列表。
    """
    ak = _get_ak()
    if not ak:
        logger.warning("未配置 BAIDU_MAP_AK，search_hotel 无法调用")
        return []

    params = {
        "query": "酒店",
        "region": city,
        "output": "json",
        "ak": ak,
        "scope": "2",            # 返回 detail_info
        "page_size": str(min(limit, 20)),
        "page_num": "0",
    }
    resp = http_get(BAIDU_PLACE_URL, params)
    if not resp or resp.get("status") != 0:
        logger.warning("百度 Place 查询酒店失败: status=%s", resp.get("status") if resp else "None")
        return []

    results = resp.get("results", [])
    hotels: list[Hotel] = []
    for r in results[:limit]:
        detail = r.get("detail_info", {}) or {}
        loc = r.get("location", {}) or {}
        # 坐标（BD09，与高德 GCJ02 有几百米偏差，练手可接受）
        lng = loc.get("lng", 0.0)
        lat = loc.get("lat", 0.0)

        hotels.append(Hotel(
            name=r.get("name", ""),
            address=r.get("address", "") or "",
            price_per_night=_parse_price(detail),
            rating=_parse_rating(detail),
            room_type="标准间",  # 百度 Place 不返回房型，给默认值
            facilities=[],        # 百度 Place 不返回设施列表
        ))
    return hotels


# ============ 餐厅搜索 ============

def search_restaurant(city: str, limit: int = 10) -> list[Restaurant]:
    """搜索餐厅（真实数据）。

    Args:
        city: 城市名
        limit: 返回数量上限

    Returns:
        Restaurant 列表。avg_price 缺失时为 0（由调用方估算）。
        失败时返回空列表。
    """
    ak = _get_ak()
    if not ak:
        logger.warning("未配置 BAIDU_MAP_AK，search_restaurant 无法调用")
        return []

    params = {
        "query": "餐厅",
        "region": city,
        "output": "json",
        "ak": ak,
        "scope": "2",
        "page_size": str(min(limit, 20)),
        "page_num": "0",
    }
    resp = http_get(BAIDU_PLACE_URL, params)
    if not resp or resp.get("status") != 0:
        logger.warning("百度 Place 查询餐厅失败: status=%s", resp.get("status") if resp else "None")
        return []

    results = resp.get("results", [])
    restaurants: list[Restaurant] = []
    for r in results[:limit]:
        detail = r.get("detail_info", {}) or {}
        tag = detail.get("tag", "")

        restaurants.append(Restaurant(
            name=r.get("name", ""),
            address=r.get("address", "") or "",
            cuisine=_parse_cuisine(tag),
            avg_price=_parse_price(detail),
            rating=_parse_rating(detail),
            signature_dishes=[],   # 百度 Place 不返回特色菜
            open_time="",          # 百度 Place 不返回营业时间
        ))
    return restaurants
