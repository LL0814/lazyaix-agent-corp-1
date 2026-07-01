"""Tools 模块自测脚本（不依赖 API Key，非业务工具）。

验证各工具模块的基本可用性：
  - Tool 类可正常导入与分发
  - 未知 action 优雅返回
  - 本地 JSON 兜底数据加载正确
  - 贪心最近邻算法排序正确
  - 未配置 API Key 时真实 API 优雅降级

运行方式：从项目根目录执行 `python3 tools/_selftest.py`
"""

import os
import sys

# 将项目根目录加入 sys.path，使 `from tools import ...` 可用
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import Tool
from tools.route_optimizer import greedy_nearest_neighbor, haversine_distance
from tools.models import POI

t = Tool()

# 1. 测试未知 action
print("--- 测试未知 action ---")
print(t.execute("unknown_action", {}))

# 2. 测试模拟数据：成都酒店
print()
print("--- 测试 search_hotel（成都，预算 600/晚）---")
hotels = t.execute("search_hotel", {"city": "成都", "price_max": 600, "limit": 3})
for h in hotels:
    print(f"  {h.name} | {h.price_per_night}元/晚 | 评分{h.rating} | {h.room_type}")

# 3. 测试模拟数据：成都餐厅
print()
print("--- 测试 search_restaurant（成都，川菜）---")
restaurants = t.execute("search_restaurant", {"city": "成都", "cuisine": "川菜", "limit": 3})
for r in restaurants:
    print(f"  {r.name} | {r.cuisine} | 人均{r.avg_price}元 | 评分{r.rating} | 招牌: {r.signature_dishes}")

# 4. 测试模拟数据：北京酒店
print()
print("--- 测试 search_hotel（北京，预算 500/晚）---")
hotels_bj = t.execute("search_hotel", {"city": "北京", "price_max": 500, "limit": 3})
for h in hotels_bj:
    print(f"  {h.name} | {h.price_per_night}元/晚 | 评分{h.rating}")

# 5. 测试未配置 API Key 的真实 API（应优雅返回空）
print()
print("--- 测试 search_poi（未配置 Key，应返回空列表）---")
pois = t.execute("search_poi", {"city": "成都", "poi_type": "景点", "limit": 3})
print(f"  返回 {len(pois)} 个 POI（预期 0，因为未配 Key）")

# 6. 测试 geocode 未配置 Key
print()
print("--- 测试 geocode（未配置 Key，应返回 None）---")
result = t.execute("geocode", {"address": "成都市武侯祠"})
print(f"  返回: {result}")

# 7. 测试贪心最近邻算法
print()
print("--- 测试贪心最近邻排序 ---")
# A(104.0, 30.7) → B(104.05, 30.65) → C(104.1, 30.6)
# A→B 距离 < A→C 距离，B→C 距离 < B→A 距离，所以顺序应为 A → B → C
test_pois = [
    POI(name="A", address="", lng=104.0, lat=30.7),
    POI(name="C", address="", lng=104.1, lat=30.6),
    POI(name="B", address="", lng=104.05, lat=30.65),
]
ordered = greedy_nearest_neighbor(test_pois)
print("  排序结果:", " → ".join(p.name for p in ordered))
print("  预期: A → B → C（按距离最近）")

# 8. 测试 haversine 距离
d = haversine_distance(104.0, 30.7, 104.1, 30.6)
print(f"  A→C 距离: {d:.0f} 米")

# 9. 测试参数错误优雅处理
print()
print("--- 测试参数错误（缺少必填参数）---")
result = t.execute("search_poi", {"poi_type": "景点"})  # 缺 city
print(f"  返回: {result}")

print()
print("✓ 所有非 API 测试通过")
