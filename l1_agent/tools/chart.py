"""
L1 render_chart — ECharts option 校验 + 自动修复 + chart_title 注入。

复用 ParkingLotAgent chart_tool 的核心校验/修复逻辑。
"""

import time
import uuid
from typing import Any

# Chart config
CHART_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']
ALLOWED_CHART_TYPES = {"pie", "line", "bar"}
MAX_PIE_SECTORS = 20
MAX_DATA_POINTS = 200


class ChartValidationError(Exception):
    pass


def validate_chart_option(option: dict[str, Any]) -> tuple[str, int]:
    """Validate ECharts option. Returns (chart_type, data_points)."""
    if not isinstance(option, dict):
        raise ChartValidationError("option 必须是 JSON 对象")

    series = option.get("series")
    if not series or not isinstance(series, list) or len(series) == 0:
        raise ChartValidationError("option 必须包含非空的 series 数组")

    first_series = series[0]
    if not isinstance(first_series, dict):
        raise ChartValidationError("series 中的每个元素必须是对象")

    chart_type = first_series.get("type", "")
    if chart_type not in ALLOWED_CHART_TYPES:
        raise ChartValidationError(
            f"不支持的图表类型 '{chart_type}'，仅支持 {', '.join(sorted(ALLOWED_CHART_TYPES))}。"
            f"跨源对比请使用 bar 或 line（支持多系列）。"
        )

    data = first_series.get("data", [])
    if not isinstance(data, list):
        raise ChartValidationError("series[0].data 必须是数组")

    data_points = len(data)

    if chart_type == "pie" and data_points > MAX_PIE_SECTORS:
        raise ChartValidationError(f"饼图扇区数 {data_points} 超过上限 {MAX_PIE_SECTORS}")

    if chart_type in ("line", "bar") and data_points > MAX_DATA_POINTS:
        raise ChartValidationError(
            f"{chart_type} 图数据点 {data_points} 超过上限 {MAX_DATA_POINTS}。"
            f"提示：对比多源时请确保各系列数据点数量一致且 xAxis 对齐。"
        )

    if data_points == 0:
        raise ChartValidationError("series[0].data 不能为空。请检查数据源是否返回了有效数值。")

    return chart_type, data_points


def auto_fix_option(option: dict[str, Any], chart_type: str) -> dict[str, Any]:
    """Auto-fix common ECharts option issues."""
    option = dict(option)

    if "tooltip" not in option:
        option["tooltip"] = {"trigger": "item" if chart_type == "pie" else "axis"}

    if chart_type == "pie":
        series = option.get("series", [])
        if series and "radius" not in series[0]:
            series[0]["radius"] = "60%"

    if chart_type == "line":
        series = option.get("series", [])
        for s in series:
            if "smooth" not in s:
                s["smooth"] = True

    return option


def render_chart(option: dict[str, Any], chart_title: str | None = None) -> dict:
    """
    L1 版 render_chart — 生成跨物对比图表。

    Args:
        option: 完整 ECharts option
        chart_title: 可选图表标题。提供时，若 option 中无 title.text 则自动注入。

    Returns:
        {status, chart_id, chart_type, data_points, option}
    """
    try:
        chart_type, data_points = validate_chart_option(option)
    except ChartValidationError as e:
        return {"status": "error", "error": str(e)}

    fixed_option = auto_fix_option(option, chart_type)

    # Inject chart_title if provided and option doesn't already have title.text
    if chart_title:
        if "title" not in fixed_option:
            fixed_option["title"] = {}
        if not fixed_option["title"].get("text"):
            fixed_option["title"]["text"] = chart_title

    # Generate chart_id: {source_id}_{timestamp_ms}_{random_6chars}
    # For L1 charts, we use a generic source prefix
    ts = int(time.time() * 1000)
    rand_suffix = uuid.uuid4().hex[:6]
    chart_id = f"l1_{ts}_{rand_suffix}"

    return {
        "status": "rendered",
        "chart_id": chart_id,
        "chart_type": chart_type,
        "data_points": data_points,
        "option": fixed_option,
    }
