"""
T9: 图表渲染工具。

验证 ECharts option JSON，通过 SSE 推送到前端。
"""

import json
import uuid
from typing import Any

CHART_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']
ALLOWED_CHART_TYPES = {"pie", "line", "bar"}
MAX_PIE_SECTORS = 20
MAX_DATA_POINTS = 200


class ChartValidationError(Exception):
    """图表数据验证错误。"""
    pass


def validate_chart_option(option: dict[str, Any]) -> tuple[str, int]:
    """
    校验 ECharts option。返回 (chart_type, data_points)。
    抛出 ChartValidationError 如果校验失败。
    """
    if not isinstance(option, dict):
        raise ChartValidationError("option 必须是 JSON 对象")

    series = option.get("series")
    if not series or not isinstance(series, list) or len(series) == 0:
        raise ChartValidationError("option 必须包含非空的 series 数组")

    # 取第一个 series（多 series 图表的统一校验）
    first_series = series[0]
    if not isinstance(first_series, dict):
        raise ChartValidationError("series 中的每个元素必须是对象")

    chart_type = first_series.get("type", "")
    if chart_type not in ALLOWED_CHART_TYPES:
        raise ChartValidationError(
            f"不支持的图表类型 '{chart_type}'，仅支持 {', '.join(sorted(ALLOWED_CHART_TYPES))}"
        )

    # 数据点计数
    data = first_series.get("data", [])
    if not isinstance(data, list):
        raise ChartValidationError("series[0].data 必须是数组")

    data_points = len(data)

    if chart_type == "pie" and data_points > MAX_PIE_SECTORS:
        raise ChartValidationError(f"饼图扇区数 {data_points} 超过上限 {MAX_PIE_SECTORS}")

    if chart_type in ("line", "bar") and data_points > MAX_DATA_POINTS:
        raise ChartValidationError(f"{chart_type} 图数据点 {data_points} 超过上限 {MAX_DATA_POINTS}")

    if data_points == 0:
        raise ChartValidationError("series[0].data 不能为空")

    return chart_type, data_points


def auto_fix_option(option: dict[str, Any], chart_type: str) -> dict[str, Any]:
    """
    自动修复常见的 ECharts option 问题。
    - 确保 tooltip 存在
    - 饼图设置默认 radius
    """
    option = dict(option)  # 浅拷贝

    # tooltip
    if "tooltip" not in option:
        option["tooltip"] = {"trigger": "item" if chart_type == "pie" else "axis"}

    # 饼图默认环形
    if chart_type == "pie":
        series = option.get("series", [])
        if series and "radius" not in series[0]:
            series[0]["radius"] = "60%"

    # 折线图平滑
    if chart_type == "line":
        series = option.get("series", [])
        for s in series:
            if "smooth" not in s:
                s["smooth"] = True

    return option


def render_chart(option: dict[str, Any]) -> dict:
    """
    T9: 渲染 ECharts 图表。校验 option 并返回图表元数据。
    实际 SSE 推送由 agent 层负责。
    返回 {status, chart_id, chart_type, data_points, option}。
    """
    try:
        chart_type, data_points = validate_chart_option(option)
    except ChartValidationError as e:
        return {"status": "error", "error": str(e)}

    # 自动修复
    fixed_option = auto_fix_option(option, chart_type)

    chart_id = f"chart_{uuid.uuid4().hex[:8]}"

    return {
        "status": "rendered",
        "chart_id": chart_id,
        "chart_type": chart_type,
        "data_points": data_points,
        "option": fixed_option,
    }
