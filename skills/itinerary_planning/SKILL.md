---
name: "itinerary-planning"
description: "行程规划技能：当用户需求齐全（目的地/天数/预算）且无已有行程时，决策调用 generate_itinerary 工具生成完整行程方案。"
---

# Skill：行程规划（itinerary_planning）

> **技能类型**：决策模式（Decision Pattern）
> **对应代码**：`scripts/handle.py`（本 skill 文件夹内）
> **共享依赖**：`common/`（skills 公共模块，挂载点见智能体配置）

---

## 一、技能概述

当用户需求信息齐全（目的地、天数、预算均已提供）且当前无已生成行程时，Agent 决策调用 `generate_itinerary` 工具生成完整行程方案。本模式只负责"决定调用"，复杂编排由 Tool 内部完成。

## 二、触发条件

以下条件**全部满足**时触发：

1. `UserRequirement.is_complete() == True`（destination / days / budget 均非空）
2. memory 中无已生成行程（`current_itinerary is None`）
3. 用户未表达"校验"或"重置"意图

## 三、输入

| 参数 | 类型 | 说明 |
|------|------|------|
| `req` | UserRequirement | 已合并多轮槽位的需求对象 |

## 四、处理逻辑

```
槽位齐全 + 无已有行程
   │
   ▼
构建工具调用决策
   │
   ▼
返回 {"action": "tool", "tool": "generate_itinerary", "params": {...}}
   │
   ▼
（由 agent.py 执行 Tool.execute()，内部完成：
     search_poi → get_weather → calculate_route →
     search_hotel → search_restaurant → 贪心排序 → 组装 Itinerary）
   │
   ▼
（Itinerary 存入 memory，供后续校验/展示使用）
```

### 决策返回的参数构造

```python
{
    "action": "tool",
    "tool": "generate_itinerary",
    "params": {
        "destination": "成都",
        "days": 3,
        "budget_level": "mid",
        "preferences": "美食, 自然风光"
    }
}
```

### budget_level 划分

| 级别 | 判定关键词 | 预算金额参考 | 影响 |
|------|-----------|-------------|------|
| `low` | 穷游 / 便宜 / 省钱 | < 2000 元 | 经济型酒店，人均餐标低 |
| `mid` | 舒适 / 默认 | 2000-8000 元 | 中档酒店，人均餐标中等 |
| `high` | 豪华 / 高端 / 奢侈 | > 8000 元 | 高档酒店，人均餐标高 |

## 五、输出

返回决策字典，**不直接生成行程文本**。实际行程由 Tool 生成，格式化由 `common/formatter` 完成。

```python
{
    "action": "tool",
    "tool": "generate_itinerary",
    "params": {"destination": "成都", "days": 3, "budget_level": "mid", "preferences": ""}
}
```

## 六、依赖

- **Tools**：`generate_itinerary`（其内部间接调用 search_poi / get_weather / calculate_route / search_hotel / search_restaurant）
- **共享模块**：`common.models.UserRequirement`

## 七、对话示例

```
用户：我想去成都玩3天，预算3000元，喜欢美食
Agent：（槽位齐全，触发生成）
       → Tool.execute("generate_itinerary", {destination:成都, days:3, ...})
       → 返回 Itinerary 对象

（下一轮）
用户：看看我的行程
Agent：（格式化展示 Itinerary）
       ==================================================
         成都 旅行行程方案
       ==================================================
       【第 1 天】2026-07-01 周二
         天气：晴 22~30℃ | 建议穿短袖
         ...
```

## 八、重新生成

当用户要求"重新生成 / 换一个 / 重做"时：

1. 检测到 `REGENERATE_KEYWORDS`
2. 清除 memory 中的 `current_itinerary`
3. 若槽位仍齐全 → 重新触发生成
4. 若槽位缺失 → 转需求对齐模式

## 九、扩展方向

- 支持用户指定具体景点（"一定要去都江堰"）
- 支持行程风格选择（紧凑型 / 休闲型）
- 多轮微调（"第2天太满了，减少一个景点"）
