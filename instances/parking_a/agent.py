"""
ReAct Agent 循环。

协调 LLM (DeepSeek V4) 与工具执行，产生 SSE 流式响应。
"""

import json
import datetime
from typing import Any

from openai import AsyncOpenAI

import config
from tools import TOOL_SCHEMAS, TOOL_EXECUTORS
from sse import SSESender

SYSTEM_PROMPT = """你是停车场数据服务，为上层编排 Agent 提供结构化数据。

你的调用者是另一个 AI Agent（而非终端用户），因此你的回复需要：
1. 简短的自然语言摘要（1-3句，不要修饰性语言如"好的，我来帮您查一下"）
2. 在回复末尾附上结构化 JSON 摘要块，包含核心数值字段

## JSON 摘要要求

每次回复末尾必须包含一个 JSON 块（用 ```json 代码块包裹），包含以下字段：
- occupancy_rate (float 0-1, 占用率)
- nev_ratio (float 0-1, 新能源车占比，BEV+PHEV+HEV)
- total_spots (int, 总车位数)
- available_spots (int, 空余车位)
- vehicle_types (object, key=类型 value=数量，如 {"ICE": 440, "BEV": 200, "PHEV": 96, "HEV": 64})

如果查询涉及历史趋势，额外包含：
- total_vehicles_{n}d (int, N天总车次)
- nev_count_{n}d (int, N天新能源车次)

如果查询涉及楼层，额外包含 floor 分组数据。

示例输出格式：
"当前停车场占用率65%，剩余277个车位。新能源车占比45%。
```json
{"occupancy_rate": 0.65, "nev_ratio": 0.45, "total_spots": 800, "available_spots": 277, "vehicle_types": {"ICE": 440, "BEV": 200, "PHEV": 96, "HEV": 64}}
```"

## 工具选择优先级

1. **优先用 `query_aggregation`** —— 覆盖 90% 的查询场景
2. 车辆个体查询用 **`get_vehicle`**
3. 需要总车位数/楼层数等上下文时先调用 **`get_config`**
4. **仅当 query_aggregation 无法覆盖时使用 `sql_query`**
5. 数据就绪后用 **`render_chart`** 生成单体图表（饼图/折线图/柱状图）

## 工作原则

- 使用工具获取数据，不编造数字
- 回复简洁，面向机器消费者
- 每次回复末尾必须附 JSON 摘要

## 错误恢复

- 工具返回 `{"error": "..."}` 时：修正参数后重试一次
- 连续两次失败后：在 JSON 摘要中包含 error 字段，不再重试

## 数据说明

- 车辆类型代码：ICE=燃油车, BEV=纯电动, PHEV=插电混动, HEV=油电混动
- 新能源车 = BEV + PHEV + HEV

当前时间：{current_datetime}

日期换算参考（基于当前时间，所有日期参数请转换为 YYYY-MM-DD 格式的绝对日期后传入）：
- "今天" = 当前日期
- "昨天" = 当前日期减 1 天
- "最近7天" = 当前日期减 7 天 到 当前日期
- "最近30天" = 当前日期减 30 天 到 当前日期
- "本月" = 当前日期所在月的第一天 到 当前日期
- "上月" = 当前日期减 1 月的第一天 到 该月最后一天
"""


def _get_client() -> AsyncOpenAI:
    """Create DeepSeek-compatible async OpenAI client."""
    return AsyncOpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        timeout=60.0,
    )


async def execute_tool(tool_name: str, arguments: dict[str, Any]) -> dict:
    """Execute a single tool and return its result."""
    executor = TOOL_EXECUTORS.get(tool_name)
    if not executor:
        return {"error": f"未知工具: {tool_name}"}

    try:
        result = executor(**arguments) if arguments else executor()
        return result if isinstance(result, dict) else {"result": result}
    except TypeError as e:
        return {"error": f"工具参数错误: {str(e)}。请检查参数名称和类型。"}
    except Exception as e:
        return {"error": f"工具执行失败: {str(e)}"}


# ── 工具消息生成 ──────────────────────────────────────

GROUP_BY_LABELS = {
    "vehicle_type": "按能源类型统计",
    "floor": "按楼层统计",
    "date": "按日统计趋势",
    "hour": "按时段分布",
    "day_of_week": "按星期分布",
    "month": "按月汇总",
}

CHART_TYPE_LABELS = {"pie": "生成饼图", "line": "生成折线图", "bar": "生成柱状图"}


def _tool_message(tool_name: str, arguments: dict) -> str:
    """Generate a human-readable description for a tool invocation."""
    if tool_name == "get_config":
        return "获取停车场配置"

    if tool_name == "get_vehicle":
        plate = arguments.get("plate", "")
        return f"查询车辆 {plate}" if plate else "查询车辆信息"

    if tool_name == "query_aggregation":
        active_only = arguments.get("active_only", True)
        group_by = arguments.get("group_by")

        if active_only and not group_by:
            return "查询当前空余车位"

        if group_by and group_by in GROUP_BY_LABELS:
            label = GROUP_BY_LABELS[group_by]
            date_from = arguments.get("date_from")
            date_to = arguments.get("date_to")
            if date_from and date_to:
                if date_from == date_to:
                    label += f" ({date_from})"
                else:
                    label += f" ({date_from} ~ {date_to})"
            elif date_from:
                label += f" ({date_from}起)"
            return label

        if not active_only and not group_by:
            return "查询历史汇总统计"

        return "执行聚合查询"

    if tool_name == "sql_query":
        query = arguments.get("query", "")
        if query:
            upper = query.upper()
            if "COUNT" in upper and "GROUP BY" in upper:
                return "执行分组统计查询"
            if "AVG" in upper:
                return "执行平均值查询"
            if "WHERE" in upper and "NULL" in upper:
                return "查询在场车辆"
        return "执行自定义SQL查询"

    if tool_name == "render_chart":
        option = arguments.get("option", {})
        if isinstance(option, dict):
            series = option.get("series", [{}])
            if isinstance(series, list) and len(series) > 0:
                chart_type = series[0].get("type", "") if isinstance(series[0], dict) else ""
                return CHART_TYPE_LABELS.get(chart_type, "生成统计图表")
        return "生成统计图表"

    return f"执行 {tool_name}"


async def agent_loop(
    user_message: str,
    history: list[dict] | None = None,
    send_sse: SSESender | None = None,
    model: str | None = None,
    thinking_mode: str | None = None,
) -> str:
    """
    执行 ReAct Agent 循环。

    Args:
        user_message: 用户的输入消息
        history: 之前的对话历史
        send_sse: SSE 事件发送器（None 表示非流式模式）

    Returns:
        助手完整回复文本
    """
    client = _get_client()

    # 构建消息
    now_str = datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M")
    system_content = SYSTEM_PROMPT.replace("{current_datetime}", now_str)

    messages: list[Any] = [{"role": "system", "content": system_content}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    for _ in range(config.MAX_ITERATIONS):
        # 工具决策阶段（非流式）
        response = await client.chat.completions.create(  # type: ignore[reportArgumentType]
            model=model or config.DEEPSEEK_MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,  # type: ignore[reportArgumentType]
            tool_choice="auto",
            stream=False,
            extra_body={"thinking": {"type": thinking_mode or config.THINKING_MODE}},
        )

        assistant_msg = response.choices[0].message

        if assistant_msg.tool_calls:
            # 工具调用阶段
            messages.append(assistant_msg)

            for tool_call in assistant_msg.tool_calls:
                tool_name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}

                # 通知前端：工具开始执行
                if send_sse:
                    await send_sse.tool_call(
                        tool_name=tool_name,
                        status="running",
                        arguments=arguments,
                        message=_tool_message(tool_name, arguments),
                    )

                # 执行工具
                result = await execute_tool(tool_name, arguments)

                # 通知前端：工具执行完成
                if send_sse:
                    if "error" in result:
                        await send_sse.tool_call(
                            tool_name=tool_name,
                            status="error",
                            arguments=arguments,
                            message=_tool_message(tool_name, arguments),
                            error=result["error"],
                        )
                    else:
                        # 截断长结果用于预览
                        preview = _truncate_preview(result)
                        await send_sse.tool_call(
                            tool_name=tool_name,
                            status="done",
                            arguments=arguments,
                            message=_tool_message(tool_name, arguments),
                            result_preview=preview,
                        )

                        # 如果是 render_chart 且成功，推送 chart 事件
                        if tool_name == "render_chart" and result.get("status") == "rendered":
                            await send_sse.chart(
                                chart_id=result["chart_id"],
                                chart_type=result["chart_type"],
                                option=result["option"],
                            )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

        else:
            # 文本响应阶段：流式输出
            stream = await client.chat.completions.create(  # type: ignore[reportArgumentType]
                model=model or config.DEEPSEEK_MODEL,
                messages=messages,
                stream=True,
                extra_body={"thinking": {"type": thinking_mode or config.THINKING_MODE}},
            )

            full_response = ""
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_response += token
                    if send_sse:
                        await send_sse.text(token)

            messages.append({
                "role": "assistant",
                "content": full_response,
            })

            if send_sse:
                try:
                    usage = {
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                        "total_tokens": response.usage.total_tokens if response.usage else 0,
                    }
                except Exception:
                    usage = None
                await send_sse.done(usage=usage)

            return full_response

    # 超过最大迭代次数
    error_msg = "抱歉，我暂时无法完成这个查询。请尝试换个方式提问。"
    if send_sse:
        await send_sse.text(error_msg)
        await send_sse.done(status="error")
    return error_msg


def _truncate_preview(result: dict, max_chars: int = 200) -> dict:
    """截断长结果用于 SSE 预览。"""
    s = json.dumps(result, ensure_ascii=False)
    if len(s) <= max_chars:
        return result
    # 对 trend 等大数组做摘要
    preview = dict(result)
    for key in list(preview.keys()):
        val = preview[key]
        if isinstance(val, list) and len(val) > 5:
            preview[key] = f"[{len(val)} items]"
        elif isinstance(val, dict):
            # 嵌套对象也尝试截断
            for sub_key in list(val.keys()):
                if isinstance(val[sub_key], list) and len(val[sub_key]) > 5:
                    val[sub_key] = f"[{len(val[sub_key])} items]"
    return preview