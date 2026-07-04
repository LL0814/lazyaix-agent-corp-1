"""行程格式化器。

将 Itinerary 对象格式化为用户可读的文本，
用于 Skill 的 direct 回复。
"""

from tools.models import Itinerary, POI, Route, Hotel, Restaurant, Weather


def format_itinerary(itinerary: Itinerary) -> str:
    """将完整行程格式化为可读文本。"""
    if not itinerary.days:
        return f"抱歉，未能为 {itinerary.destination} 生成行程，请检查目的地名称或稍后重试。"

    lines: list[str] = []
    lines.append(f"{'=' * 50}")
    lines.append(f"  {itinerary.destination} 旅行行程方案")
    lines.append(f"{'=' * 50}")
    lines.append("")

    for i, day in enumerate(itinerary.days, 1):
        date = day.get("date", "")
        weekday = day.get("weekday", "")
        lines.append(f"【第 {i} 天】{date} {weekday}")

        weather: Weather | None = day.get("weather")
        if weather:
            lines.append(f"  天气：{weather.condition} {weather.temp_min}~{weather.temp_max}℃ "
                        f"| {weather.clothing_advice}")

        timeline: list[str] = day.get("timeline", [])
        if timeline:
            lines.append("  行程安排：")
            for item in timeline:
                lines.append(f"    {item}")

        pois: list[POI] = day.get("pois", [])
        if pois:
            lines.append("  景点：")
            for poi in pois:
                rating_str = f"评分{poi.rating}" if poi.rating else "暂无评分"
                lines.append(f"    · {poi.name}（{rating_str}）{poi.open_time}")

        # 市内交通：相邻景点间路线（高德 calculate_route 结果）
        routes: list[Route] = day.get("routes", [])
        if routes:
            lines.append("  市内交通：")
            mode_name = {"driving": "驾车", "transit": "公交", "walking": "步行"}
            for i, route in enumerate(routes):
                if i < len(pois) - 1:
                    m = mode_name.get(route.mode, route.mode)
                    dist_km = route.distance / 1000
                    dur_min = route.duration // 60
                    lines.append(f"    · {pois[i].name} → {pois[i+1].name}：{m} {dist_km:.1f}km / {dur_min}分钟")

        lunch: Restaurant | None = day.get("lunch")
        dinner: Restaurant | None = day.get("dinner")
        if lunch or dinner:
            lines.append("  餐饮：")
            if lunch:
                lines.append(f"    午餐：{lunch.name}（{lunch.cuisine}，人均{lunch.avg_price}元）")
            if dinner:
                lines.append(f"    晚餐：{dinner.name}（{dinner.cuisine}，人均{dinner.avg_price}元）")

        hotel: Hotel | None = day.get("hotel")
        if hotel:
            lines.append(f"  住宿：{hotel.name}（{hotel.price_per_night}元/晚，评分{hotel.rating}）")

        lines.append("")

    budget = itinerary.budget_summary
    if budget:
        lines.append(f"{'-' * 50}")
        lines.append("预算汇总：")
        lines.append(f"  住宿：{budget.get('accommodation', 0)} 元")
        lines.append(f"  餐饮：{budget.get('food', 0)} 元")
        lines.append(f"  交通：{budget.get('transport', 0)} 元")
        lines.append(f"  门票：{budget.get('tickets', 0)} 元")
        lines.append(f"  总计：{budget.get('total', 0)} 元")
        lines.append(f"  日均：{budget.get('daily_avg', 0):.0f} 元")

    if itinerary.notes:
        lines.append(f"{'-' * 50}")
        lines.append("注意事项：")
        for note in itinerary.notes:
            lines.append(f"  · {note}")

    lines.append(f"{'=' * 50}")
    return "\n".join(lines)


def format_validation_report(report: dict) -> str:
    """将校验结果格式化为可读文本。"""
    lines: list[str] = []
    lines.append(f"{'=' * 50}")
    lines.append("  行程校验报告")
    lines.append(f"{'=' * 50}")

    if report["is_valid"]:
        lines.append("行程检查通过，未发现明显问题。")
    else:
        lines.append(f"发现 {len(report['issues'])} 个问题：")
        lines.append("")
        for i, issue in enumerate(report["issues"], 1):
            lines.append(f"  {i}. {issue}")

    if report["suggestions"]:
        lines.append("")
        lines.append("修正建议：")
        for i, sug in enumerate(report["suggestions"], 1):
            lines.append(f"  {i}. {sug}")

    lines.append(f"{'=' * 50}")
    return "\n".join(lines)
