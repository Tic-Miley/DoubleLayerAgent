"""
L1 Tool Registry — L1 自有工具 + L2 bridge 工具。

注册顺序：
1. L1 自有工具（Python 代码定义）：find_nearby_things, aggregate, render_chart
2. L2 bridge 工具（tools.yaml 动态生成）：query_parking_lot_*, query_cafeteria, query_hospital
"""

import json
import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── L1 自有工具 ──────────────────────────────────────────

from tools.geo import find_nearby_things
from tools.aggregate import aggregate
from tools.chart import render_chart

# L1 自有工具的 OpenAI function-calling schemas
L1_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "find_nearby_things",
            "description": (
                "根据经纬度搜索指定半径内的城市设施。"
                "返回设施列表，包含 id、名称、类型、经纬度和距离。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {
                        "type": "number",
                        "description": "中心点纬度",
                    },
                    "lng": {
                        "type": "number",
                        "description": "中心点经度",
                    },
                    "radius_km": {
                        "type": "number",
                        "description": "搜索半径（公里）",
                    },
                    "thing_type": {
                        "type": "string",
                        "description": "可选物类型过滤: parking_lot, cafeteria, hospital",
                    },
                },
                "required": ["lat", "lng", "radius_km"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate",
            "description": (
                "对多个数据源的结果执行统计聚合（求和、均值、最小值、最大值、计数、中位数、标准差）。"
                "field 支持嵌套路径如 'structured.occupancy_rate'。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "data": {
                        "type": "array",
                        "description": "待聚合的数据列表，每项为 dict",
                    },
                    "operations": {
                        "type": "array",
                        "description": (
                            "聚合操作列表。每项包含 field (字段路径，支持点号分隔的嵌套路径)、"
                            "func (聚合函数: sum|avg|min|max|count|median|std)、"
                            "alias (可选，结果中的键名)"
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "func": {
                                    "type": "string",
                                    "enum": ["sum", "avg", "min", "max", "count", "median", "std"],
                                },
                                "alias": {"type": "string"},
                            },
                            "required": ["field", "func"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["data", "operations"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_chart",
            "description": (
                "生成 ECharts 对比图表。支持 pie/line/bar。跨源对比优先用 bar 或 line"
                "（支持多系列）。如果各源数据维度不一致（如时序趋势 vs 车型分类），"
                "不要使用本工具——改为输出文字分析。"
                "传入完整的 ECharts option JSON，可选 chart_title。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "option": {
                        "type": "object",
                        "description": "完整的 ECharts option 对象，必须包含 series 数组",
                    },
                    "chart_title": {
                        "type": "string",
                        "description": "可选图表标题",
                    },
                },
                "required": ["option"],
                "additionalProperties": False,
            },
        },
    },
]

# L1 自有工具执行器映射
L1_EXECUTORS: dict[str, Any] = {
    "find_nearby_things": find_nearby_things,
    "aggregate": aggregate,
    "render_chart": render_chart,
}


# ── L2 Bridge 工具 ───────────────────────────────────────
# 在 TOOL_REGISTRY 初始化时构建

def _build_l2_bridge_executors():
    """
    从 config 动态构建 L2 bridge tool executor 函数。
    每个 executor 捕获其对应的 thing 元数据。

    注意: 这些 executor 不直接参与工具调用。
    agent_loop 通过 BRIDGE_TOOL_NAMES 集合识别 bridge 工具并调用 bridge 层函数。
    此处仅保留 executor 映射以供工具注册的完整性。
    """
    from config import THING_MAP, TOOL_SCHEMA_MAP
    from bridge import query_agent_thing, query_rest_thing

    executors: dict[str, Any] = {}

    for thing_id, schema in TOOL_SCHEMA_MAP.items():
        thing = THING_MAP.get(thing_id)
        if not thing:
            logger.warning(f"Tool schema for '{thing_id}' has no matching thing — skipping")
            continue

        tool_name = schema["function"]["name"]
        protocol = thing.get("protocol")

        if protocol == "agent_sse":
            async def executor(
                query: str,
                _thing=thing,
                _thing_id=thing_id,
                history: list[dict] | None = None,
            ) -> dict:
                return await query_agent_thing(_thing, query, history)
            executors[tool_name] = executor

        elif protocol == "http_rest":
            async def executor(_thing=thing, _thing_id=thing_id):
                return await query_rest_thing(_thing)
            executors[tool_name] = executor

    return executors


# ── Combine ──────────────────────────────────────────────


def get_all_tool_schemas() -> list[dict]:
    """Return combined tool schemas: L1 own + L2 bridge."""
    from config import TOOL_SCHEMA_MAP
    l2_schemas = [ts for ts in TOOL_SCHEMA_MAP.values()]
    return L1_TOOL_SCHEMAS + l2_schemas


def get_all_executors() -> dict[str, Any]:
    """Return combined executors: L1 own + L2 bridge."""
    l2_execs = _build_l2_bridge_executors()
    return {**L1_EXECUTORS, **l2_execs}


# Singleton — built once at import time
TOOL_SCHEMAS = get_all_tool_schemas()
TOOL_EXECUTORS = get_all_executors()
