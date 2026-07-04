"""高德地图 Web 服务 API 客户端。

封装高德地图的三个接口，提供景点搜索、地理编码、路径规划能力。

本文件提供的工具函数（被 tool.py / itinerary_generator 调用）：
  ┌──────────────────┬────────────────────────────────────┬──────────────────┐
  │ 函数              │ 作用                                │ 数据来源          │
  ├──────────────────┼────────────────────────────────────┼──────────────────┤
  │ geocode           │ 地理编码：地址→经纬度 / 逆地理编码   │ 高德 地理编码 API │
  │ search_poi        │ POI 关键词搜索（景点/餐厅/购物等）   │ 高德 搜索 POI API │
  │ calculate_route   │ 路径规划（驾车/步行/公交）           │ 高德 方向 API     │
  └──────────────────┴────────────────────────────────────┴──────────────────┘

文档参考：https://lbs.amap.com/api/webservice/summary
API Key 通过环境变量 AMAP_API_KEY 配置。
注意：驾车路径规划有 QPS 限制，已加 500ms 延迟 + 1 次重试。
"""

import logging
import os
import time
from typing import Any

from .http_client import http_get
from .models import POI, Route

logger = logging.getLogger(__name__)

# 高德 Web 服务基础 URL
AMAP_BASE = "https://restapi.amap.com/v3"
AMAP_V5_BASE = "https://restapi.amap.com/v5"


def _get_api_key() -> str:
    """从环境变量读取高德 API Key。"""
    return os.environ.get("AMAP_API_KEY", "")


def _is_ok(resp: dict | None) -> bool:
    """判断高德 API 响应是否成功。

    高德 v3 接口 status 字段为 "1" 表示成功。
    """
    if not resp:
        return False
    return str(resp.get("status", "0")) == "1"


# ============ 地理编码 ============

def geocode(address: str = "", location: str = "") -> dict | str | None:
    """地址 ↔ 经纬度互转。

    Args:
        address: 地址字符串（地理编码：地址 → 坐标）
        location: "经度,纬度"（逆地理编码：坐标 → 地址）

    Returns:
        - 地址→坐标：{"lng": float, "lat": float}
        - 坐标→地址：结构化地址字符串
        - 失败：None
    """
    key = _get_api_key()
    if not key:
        logger.warning("未配置 AMAP_API_KEY，geocode 无法调用")
        return None

    if address:
        # 地理编码：地址 → 坐标
        params = {"key": key, "address": address}
        resp = http_get(f"{AMAP_BASE}/geocode/geo", params)
        if not _is_ok(resp):
            logger.warning("geocode 失败: address=%s", address)
            return None
        geocodes = resp.get("geocodes", [])
        if not geocodes:
            return None
        # 高德返回的 location 格式为 "经度,纬度"
        lng, lat = geocodes[0]["location"].split(",")
        return {"lng": float(lng), "lat": float(lat)}

    elif location:
        # 逆地理编码：坐标 → 地址
        params = {"key": key, "location": location}
        resp = http_get(f"{AMAP_BASE}/geocode/regeo", params)
        if not _is_ok(resp):
            logger.warning("regeocode 失败: location=%s", location)
            return None
        regeocode = resp.get("regeocode", {})
        return regeocode.get("formatted_address", "")

    return None


# ============ POI 搜索 ============

def search_poi(city: str, poi_type: str = "", keyword: str = "",
               location: str = "", radius: int = 0, limit: int = 10) -> list[POI]:
    """POI 搜索。

    同时支持关键词搜索和周边搜索：
      - 不传 location：按关键词在城市内搜索
      - 传 location + radius：在指定坐标周边搜索

    Args:
        city: 城市名（如 "成都"）
        poi_type: POI 类型（如 "景点" / "餐厅" / "购物"）
        keyword: 关键词（可选，用于精确搜索）
        location: 中心坐标 "lng,lat"（可选，启用周边搜索）
        radius: 搜索半径（米，仅周边搜索时生效）
        limit: 返回数量上限

    Returns:
        POI 列表，失败时返回空列表
    """
    key = _get_api_key()
    if not key:
        logger.warning("未配置 AMAP_API_KEY，search_poi 无法调用")
        return []

    # 使用 v5 接口（支持更多字段，且 2024 起官方推荐）
    params: dict[str, Any] = {
        "key": key,
        "keywords": keyword or poi_type,
        "region": city,
        "size": min(limit, 25),  # v5 单次最多 25 条
        "show_fields": "business_rating,photos,opentime",
    }
    # 周边搜索参数
    if location:
        params["location"] = location
        params["radius"] = radius
        url = f"{AMAP_V5_BASE}/place/around"
    else:
        url = f"{AMAP_V5_BASE}/place/text"

    resp = http_get(url, params)
    if not _is_ok(resp):
        logger.warning("search_poi 失败: city=%s keyword=%s", city, keyword)
        return []

    pois_data = resp.get("pois", [])
    result: list[POI] = []
    for p in pois_data[:limit]:
        # 解析坐标
        loc = p.get("location", "")
        lng, lat = 0.0, 0.0
        if "," in loc:
            parts = loc.split(",")
            lng, lat = float(parts[0]), float(parts[1])

        # 解析评分（v5 接口 business_rating 字段）
        biz = p.get("business_rating", {}) or {}
        rating = 0.0
        try:
            rating = float(biz.get("rating", 0))
        except (ValueError, TypeError):
            pass

        # 解析图片
        photos = p.get("photos", []) or []
        image_url = photos[0].get("url", "") if photos else ""

        # 解析开放时间
        opentime = p.get("opentime", "") or ""

        # 拼接地址：优先 address，为空时用 pname+cityname
        address = p.get("address") or ""
        if not address:
            address = (p.get("pname") or "") + (p.get("cityname") or "")

        result.append(POI(
            name=p.get("name", ""),
            address=address,
            lng=lng,
            lat=lat,
            rating=rating,
            open_time=opentime,
            intro=p.get("tag", ""),
            image_url=image_url,
            poi_type=poi_type or p.get("tag", ""),
        ))
    return result


# ============ 路径规划 ============

def calculate_route(origin: str, destination: str,
                    mode: str = "driving",
                    city: str = "") -> Route | None:
    """路径规划。

    Args:
        origin: 起点坐标 "lng,lat"
        destination: 终点坐标 "lng,lat"
        mode: 出行方式 driving / walking / transit
        city: 起点城市名（transit 模式必需，driving/walking 可省）

    Returns:
        Route 对象，失败时返回 None
    """
    key = _get_api_key()
    if not key:
        logger.warning("未配置 AMAP_API_KEY，calculate_route 无法调用")
        return None

    if mode == "driving":
        url = f"{AMAP_BASE}/direction/driving"
        params = {"key": key, "origin": origin, "destination": destination,
                  "extensions": "base"}
        resp = http_get(url, params)
        # 高德免费版有 QPS 限制，快速连续调用会偶发失败，重试一次
        if not _is_ok(resp):
            logger.info("driving route 首次失败，500ms 后重试: %s → %s", origin, destination)
            time.sleep(0.5)
            resp = http_get(url, params)
        if not _is_ok(resp):
            logger.warning("driving route 重试仍失败: %s → %s", origin, destination)
            return None
        path = (resp.get("route", {}).get("paths", [{}]) or [{}])[0]
        distance = int(path.get("distance", 0))
        duration = int(path.get("duration", 0))
        steps = [s.get("instruction", "") for s in path.get("steps", [])]
        return Route(distance=distance, duration=duration, mode="driving", steps=steps)

    elif mode == "walking":
        url = f"{AMAP_BASE}/direction/walking"
        params = {"key": key, "origin": origin, "destination": destination}
        resp = http_get(url, params)
        if not _is_ok(resp):
            logger.warning("walking route 失败: %s → %s", origin, destination)
            return None
        path = (resp.get("route", {}).get("paths", [{}]) or [{}])[0]
        distance = int(path.get("distance", 0))
        duration = int(path.get("duration", 0))
        steps = [s.get("instruction", "") for s in path.get("steps", [])]
        return Route(distance=distance, duration=duration, mode="walking", steps=steps)

    elif mode == "transit":
        if not city:
            logger.warning("transit 模式需要 city 参数")
            return None
        url = f"{AMAP_BASE}/direction/transit/integrated"
        params = {"key": key, "origin": origin, "destination": destination,
                  "city": city, "cityd": city, "extensions": "base"}
        resp = http_get(url, params)
        if not _is_ok(resp):
            logger.warning("transit route 失败: %s → %s", origin, destination)
            return None
        transit = (resp.get("route", {}).get("transits", [{}]) or [{}])[0]
        distance = int(transit.get("distance", 0))
        duration = int(transit.get("duration", 0))
        steps = []
        for seg in transit.get("segments", []):
            bus = seg.get("bus", {}).get("buslines", [{}])
            if bus:
                steps.append(bus[0].get("name", ""))
        return Route(distance=distance, duration=duration, mode="transit", steps=steps)

    logger.warning("未知出行方式: %s", mode)
    return None
