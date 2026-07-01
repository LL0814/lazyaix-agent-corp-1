"""Open-Meteo 天气 API 客户端（替代已失效的和风天气 v2 接口）。

Open-Meteo 是完全免费、无需 API Key 的开源天气服务。
文档：https://open-meteo.com/en/docs

本文件提供的工具函数（被 tool.py / itinerary_generator 调用）：
  ┌──────────────┬────────────────────────────────────┬──────────────────────┐
  │ 函数          │ 作用                                │ 数据来源              │
  ├──────────────┼────────────────────────────────────┼──────────────────────┤
  │ get_weather   │ 获取未来 N 天天气预报（含气温/降水） │ Open-Meteo forecast  │
  └──────────────┴────────────────────────────────────┴──────────────────────┘

接口流程：
  city 名 → 经纬度（通过 amap_client.geocode）→ Open-Meteo forecast → Weather 列表
"""

import logging

from . import amap_client
from .http_client import http_get
from .models import Weather

logger = logging.getLogger(__name__)

# Open-Meteo 预报端点
OPENMETEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


# ============ WMO 天气代码 → 中文描述 ============

WMO_CODE_MAP = {
    0: "晴",
    1: "多云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    77: "雪粒",
    80: "阵雨", 81: "中阵雨", 82: "强阵雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷暴", 96: "雷暴夹冰雹", 99: "强雷暴夹冰雹",
}


def _wmo_to_condition(code: int) -> str:
    """WMO 天气代码转中文描述。未知代码返回"未知"。"""
    return WMO_CODE_MAP.get(code, "未知")


# ============ 穿衣建议规则表 ============

def _clothing_advice(temp_max: int, temp_min: int, condition: str) -> str:
    """根据温度和天气生成穿衣建议（本地规则，不调 LLM）。"""
    avg = (temp_max + temp_min) / 2
    if "雨" in condition:
        return "有降雨，建议带伞，穿防水外套"
    if avg >= 28:
        return "炎热，建议穿短袖、短裤，注意防晒"
    if avg >= 22:
        return "温暖，建议穿短袖或薄长袖"
    if avg >= 15:
        return "凉爽，建议穿长袖加薄外套"
    if avg >= 8:
        return "较冷，建议穿毛衣加外套或风衣"
    if avg >= 0:
        return "寒冷，建议穿羽绒服或棉衣"
    return "严寒，建议穿厚羽绒服，注意保暖"


# ============ 天气预报 ============

def get_weather(location: str = "", city: str = "", days: int = 7) -> list[Weather]:
    """获取未来 N 天天气预报。

    Open-Meteo 使用经纬度查询，无需 LocationID。
    调用方传城市名时，通过高德 geocode 转成经纬度。

    Args:
        location: "经度,纬度"（如 "104.07,30.67"），优先使用
        city: 城市名（如 "成都"），location 为空时用此字段查经纬度
        days: 返回天数，最大 16（Open-Meteo 上限）

    Returns:
        Weather 列表，失败时返回空列表
    """
    # 1. 确定经纬度
    if not location:
        if not city:
            logger.warning("get_weather 需要 location 或 city 参数")
            return []
        geo = amap_client.geocode(address=city)
        if not geo or "lng" not in geo:
            logger.warning("无法解析城市经纬度: %s", city)
            return []
        location = f"{geo['lng']},{geo['lat']}"

    try:
        lng_str, lat_str = location.split(",")
        lat = float(lat_str)
        lng = float(lng_str)
    except (ValueError, IndexError):
        logger.warning("location 格式错误（应为 '经度,纬度'）: %s", location)
        return []

    # 2. 调用 Open-Meteo
    # forecast_days 上限 16，超过会被 API 拒绝
    forecast_days = min(max(days, 1), 16)
    params = {
        "latitude": lat,
        "longitude": lng,
        "daily": "temperature_2m_max,temperature_2m_min,weathercode,precipitation_probability_max,wind_speed_10m_max",
        "timezone": "Asia/Shanghai",
        "forecast_days": forecast_days,
    }
    resp = http_get(OPENMETEO_FORECAST_URL, params)

    if not resp or "daily" not in resp:
        logger.warning("Open-Meteo 返回异常: %s", resp)
        return []

    daily = resp["daily"]
    times: list[str] = daily.get("time", [])
    t_max: list[float] = daily.get("temperature_2m_max", [])
    t_min: list[float] = daily.get("temperature_2m_min", [])
    codes: list[int] = daily.get("weathercode", [])
    precip: list[int] = daily.get("precipitation_probability_max", [])
    wind: list[float] = daily.get("wind_speed_10m_max", [])

    result: list[Weather] = []
    for i, date in enumerate(times[:days]):
        try:
            temp_max = int(round(t_max[i])) if i < len(t_max) else 0
            temp_min = int(round(t_min[i])) if i < len(t_min) else 0
        except (IndexError, ValueError, TypeError):
            temp_max, temp_min = 0, 0

        try:
            condition = _wmo_to_condition(int(codes[i])) if i < len(codes) else "未知"
        except (IndexError, ValueError, TypeError):
            condition = "未知"

        try:
            precip_prob = int(precip[i]) if i < len(precip) else 0
        except (IndexError, ValueError, TypeError):
            precip_prob = 0

        try:
            wind_speed = float(wind[i]) if i < len(wind) else 0
            wind_str = f"风速 {wind_speed:.0f} km/h"
        except (IndexError, ValueError, TypeError):
            wind_str = ""

        result.append(Weather(
            date=date,
            temp_min=temp_min,
            temp_max=temp_max,
            condition=condition,
            precip_prob=precip_prob,
            wind=wind_str,
            clothing_advice=_clothing_advice(temp_max, temp_min, condition),
        ))

    return result
