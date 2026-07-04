"""Tools 模块包入口。

agent.py 会执行 `from tools import Tool`，因此这里导出 Tool 类作为模块顶层符号。

本文件导出的符号（供 Agent / Skills 层使用）：
  - Tool        ：统一工具入口类（提供 7 个 action）
  - POI / Weather / Route / Hotel / Restaurant / Itinerary：数据结构

Tools 模块整体结构：
  tool.py             → Tool 主类（action 分发）
  amap_client.py      → 高德地图工具（search_poi / geocode / calculate_route）
  baidu_client.py     → 百度地图工具（search_hotel / search_restaurant）
  openmeteo_client.py → 天气工具（get_weather）
  itinerary_generator.py → 行程编排（generate_itinerary）
  route_optimizer.py  → 路线优化算法（贪心最近邻）
  http_client.py      → HTTP 基础设施
  models.py           → 数据结构定义
"""

from .tool import Tool
from .models import POI, Weather, Route, Hotel, Restaurant, Itinerary

__all__ = ["Tool", "POI", "Weather", "Route", "Hotel", "Restaurant", "Itinerary"]
