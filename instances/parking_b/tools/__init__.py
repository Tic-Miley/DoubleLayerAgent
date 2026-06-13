"""Tool registry v2 — 5 tools (4 core + 1 fallback).

v2 变更 (2026-06-10):
- 从 9 工具精简为 5 工具
- 新增 get_config: 停车场全局配置
- 新增 query_aggregation: 通用参数化聚合 (替代 T1-T5, T7)
- get_vehicle_detail 重命名为 get_vehicle
- 保留 sql_query (T8) 和 render_chart (T9)
"""

from tools.parking import get_config, get_vehicle
from tools.aggregation import query_aggregation
from tools.sql_tool import sql_query, SCHEMA_HINT
from tools.chart_tool import render_chart

# ── Tool Schemas (OpenAI function-calling format) ─────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_config",
            "description": "获取停车场全局配置（总车位数、楼层数、每层车位数、费率等）",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_aggregation",
            "description": (
                "通用聚合查询工具 —— 一个工具覆盖几乎所有停车场数据分析场景。\n"
                "通过参数组合实现：当前空余车位、车辆类型分布、楼层占用、每日趋势、"
                "时段分布、星期几分布、月度汇总、平均停车时长等。\n"
                "优先使用本工具，仅在需要二维交叉分组等本工具无法覆盖的场景时才用 sql_query。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "active_only": {
                        "type": "boolean",
                        "description": (
                            "true=仅当前在场车辆（快照），false=查询历史记录。默认为true。"
                            "true时group_by仅支持vehicle_type和floor；"
                            "设为false后才能使用date_from/date_to/include_duration。"
                        ),
                    },
                    "group_by": {
                        "type": "string",
                        "enum": [
                            "vehicle_type",
                            "floor",
                            "date",
                            "hour",
                            "day_of_week",
                            "month",
                        ],
                        "description": (
                            "分组维度：vehicle_type=按能源类型, floor=按楼层, "
                            "date=按日, hour=按小时, day_of_week=按星期几, month=按月。"
                            "不传此参数则为全局聚合。"
                            "active_only=true 时仅支持 vehicle_type 和 floor。"
                        ),
                    },
                    "date_from": {
                        "type": "string",
                        "description": (
                            "起始日期，格式 YYYY-MM-DD（如 2026-06-01）。"
                            "必须显式传入绝对日期。仅 active_only=false 时有效。"
                        ),
                    },
                    "date_to": {
                        "type": "string",
                        "description": (
                            "结束日期，格式 YYYY-MM-DD（如 2026-06-10）。"
                            "必须显式传入绝对日期。仅 active_only=false 时有效。"
                        ),
                    },
                    "include_duration": {
                        "type": "boolean",
                        "description": (
                            "是否附带平均停车时长（分钟）。仅 active_only=false 时有效。"
                        ),
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_vehicle",
            "description": "按车牌号精确查询车辆的进出记录、当前状态和历史访问次数",
            "parameters": {
                "type": "object",
                "properties": {
                    "plate": {
                        "type": "string",
                        "description": (
                            "车牌号，格式为省份缩写+字母+数字（如 京A12345、沪B67890），"
                            "必填，通常为 7-8 位字符"
                        ),
                    },
                },
                "required": ["plate"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sql_query",
            "description": (
                "执行受控只读SQL查询。仅当 query_aggregation 无法满足时使用。\n"
                "表: parking_lot_config(id,name,total_spots,floors,spots_per_floor,hourly_rate)\n"
                "     vehicle_record(id,plate,vehicle_type[ICE/BEV/PHEV/HEV],entry_time,exit_time,entry_floor,entry_spot)\n"
                "索引: idx_entry_time, idx_exit_time, idx_vehicle_type, idx_plate, idx_active\n"
                "限制: 只读、最多1000行、5秒超时。SQL语法错误时会返回schema提示。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "只读 SELECT SQL 查询语句",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_chart",
            "description": "根据数据生成ECharts图表。支持饼图(pie)、折线图(line)、柱状图(bar)。传入完整的ECharts option JSON。",
            "parameters": {
                "type": "object",
                "properties": {
                    "option": {
                        "type": "object",
                        "description": "完整的ECharts option对象，必须包含series数组，每个series须有type字段",
                    },
                },
                "required": ["option"],
                "additionalProperties": False,
            },
        },
    },
]

# ── Tool Executor Dispatch ───────────────────────────────

TOOL_EXECUTORS = {
    "get_config": get_config,
    "query_aggregation": query_aggregation,
    "get_vehicle": get_vehicle,
    "sql_query": sql_query,
    "render_chart": render_chart,
}
