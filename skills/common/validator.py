"""行程校验器。

检查已生成的行程是否存在逻辑问题：
  1. 时间冲突：景点开放时间 vs 到达时间
  2. 可达性：相邻景点交通时间是否足够
  3. 预算一致性：预算汇总是否合理

不调用外部 API，纯逻辑校验。
"""

from tools.models import Itinerary, POI, Route


def validate(itinerary: Itinerary) -> dict:
    """校验行程方案。

    Returns:
        {"issues": [...], "suggestions": [...], "is_valid": bool}
    """
    issues: list[str] = []
    suggestions: list[str] = []

    if not itinerary.days:
        issues.append("行程为空，未生成任何日程")
        return {"issues": issues, "suggestions": suggestions, "is_valid": False}

    for i, day in enumerate(itinerary.days, 1):
        date = day.get("date", f"第{i}天")
        pois: list[POI] = day.get("pois", [])
        routes: list[Route] = day.get("routes", [])

        for poi in pois:
            if not poi.open_time:
                continue
            time_range = _parse_time_range(poi.open_time)
            if not time_range:
                continue
            open_start, open_end = time_range
            arrival = _find_arrival_time(day.get("timeline", []), poi.name)
            if arrival and (arrival < open_start or arrival > open_end):
                issues.append(
                    f"{date}：{poi.name} 的到达时间 {arrival:02d}:00 "
                    f"不在开放时间 {poi.open_time} 内"
                )
                suggestions.append(f"建议调整 {poi.name} 的游览时间到 {poi.open_time}")

        for j, route in enumerate(routes):
            if not route.duration:
                continue
            travel_hours = route.duration / 3600
            if travel_hours > 4:
                issues.append(f"{date}：第{j+1}段路程耗时 {travel_hours:.1f} 小时，过长")
                suggestions.append("建议减少当日景点数量或更换更近的景点")
            elif j < len(pois) - 1 and travel_hours > 2:
                issues.append(f"{date}：第{j+1}段路程耗时 {travel_hours:.1f} 小时，偏长")

        if len(pois) > 5:
            issues.append(f"{date}：安排了 {len(pois)} 个景点，可能过于紧凑")
            suggestions.append("建议每日景点不超过 3-4 个，留出休息时间")
        elif len(pois) == 0:
            issues.append(f"{date}：没有安排任何景点")

    budget = itinerary.budget_summary
    if budget and budget.get("total", 0) <= 0:
        issues.append("预算汇总异常：总预算为 0")
    if budget:
        daily_avg = budget.get("daily_avg", 0)
        if daily_avg > 2000:
            suggestions.append(f"日均花费 {daily_avg:.0f} 元偏高，可考虑降低住宿标准")

    return {
        "issues": issues,
        "suggestions": suggestions,
        "is_valid": len(issues) == 0,
    }


def _parse_time_range(time_str: str) -> tuple[int, int] | None:
    if not time_str or "-" not in time_str:
        return None
    try:
        parts = time_str.split("-")
        start = int(parts[0].strip().split(":")[0])
        end = int(parts[1].strip().split(":")[0])
        return (start, end)
    except (ValueError, IndexError):
        return None


def _find_arrival_time(timeline: list[str], poi_name: str) -> int | None:
    import re
    for line in timeline:
        if poi_name in line and "到达" in line:
            match = re.match(r"(\d{2}):00", line)
            if match:
                return int(match.group(1))
    return None
