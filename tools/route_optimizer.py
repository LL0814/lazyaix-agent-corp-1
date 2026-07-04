"""贪心最近邻路线优化算法（纯算法，无外部 API 调用）。

用于 generate_itinerary 内部，对单日景点按游览顺序排序，减少折返。
复杂度 O(n²)，对练手项目足够。

本文件提供的函数：
  ┌──────────────────────┬──────────────────────────────────────────┐
  │ 函数                  │ 作用                                      │
  ├──────────────────────┼──────────────────────────────────────────┤
  │ greedy_nearest_neighbor │ 贪心最近邻排序：输入景点列表，输出有序列表 │
  │ haversine_distance      │ 计算两个经纬度点之间的球面距离（公里）    │
  └──────────────────────┴──────────────────────────────────────────┘

算法思路：
  1. 从第一个景点出发（或指定起点）
  2. 每次从剩余未访问景点中，选距离当前景点最近的一个
  3. 标记为已访问，重复直到所有景点访问完毕

进阶可替换为 2-opt（见技术文档扩展项 P2）。
"""

import math

from .models import POI


def haversine_distance(lng1: float, lat1: float,
                       lng2: float, lat2: float) -> float:
    """计算两个经纬度坐标之间的球面距离（米）。

    使用 Haversine 公式，精度对行程规划足够。
    """
    R = 6371000  # 地球平均半径（米）
    # 度 → 弧度
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)

    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def greedy_nearest_neighbor(pois: list[POI],
                            start_index: int = 0) -> list[POI]:
    """贪心最近邻排序。

    Args:
        pois: 待排序的景点列表（必须含坐标）
        start_index: 起点景点在原列表中的下标，默认 0

    Returns:
        按贪心最近邻顺序排序后的景点列表。
        若 pois 为空或只有一个，直接返回原列表。
    """
    if len(pois) <= 1:
        return list(pois)

    # 防御 start_index 越界
    if start_index < 0 or start_index >= len(pois):
        start_index = 0

    # 拷贝避免修改原列表
    remaining = list(pois)
    # 起点：先取出指定起点
    ordered = [remaining.pop(start_index)]

    while remaining:
        current = ordered[-1]
        # 找剩余景点中距离 current 最近的
        nearest_idx = 0
        nearest_dist = float("inf")
        for i, p in enumerate(remaining):
            d = haversine_distance(current.lng, current.lat, p.lng, p.lat)
            if d < nearest_dist:
                nearest_dist = d
                nearest_idx = i
        ordered.append(remaining.pop(nearest_idx))

    return ordered
