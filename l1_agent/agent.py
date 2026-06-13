"""
L1 Extended ReAct Agent Loop。

扩展自 ParkingLotAgent/backend/agent.py，核心改动：
1. 并行 tool_call 执行 — 同一轮 LLM 返回的多个 tool_calls 使用 asyncio.gather
2. L2 bridge tool executor 发起 HTTP/SSE 请求（而非本地函数调用）
3. SSE 事件透传 — L2 的 tool_call/chart 事件包装为 source_* 事件
4. L1 自有工具 (find_nearby_things, aggregate, render_chart) 直接调用
"""

import asyncio
import copy
import datetime
import json
from typing import Any

from openai import AsyncOpenAI

import config
from config import THING_MAP, TOOL_NAME_TO_THING_ID
from tools import TOOL_SCHEMAS, TOOL_EXECUTORS
from bridge import query_agent_thing, query_rest_thing
from sse import SSESender

# ── L1 Bridge tool names ─────────────────────────────────
# These are tools that call L2 things via HTTP/SSE
BRIDGE_TOOL_NAMES = {
    "query_parking_lot_a", "query_parking_lot_b", "query_parking_lot_c",
    "query_cafeteria", "query_hospital",
}

SYSTEM_PROMPT = """你是城市数据整合助手，可访问多个城市设施的数据服务。

## 设施列表与返回结构
- 停车场（3个 Agent 数据源）：返回自然语言摘要 + 结构化JSON，
  必含字段: occupancy_rate(float 0-1)、nev_ratio(float 0-1)、
  total_spots(int)、available_spots(int)、vehicle_types(object)
  示例: {"occupancy_rate":0.65, "nev_ratio":0.45, "total_spots":800,
         "available_spots":277, "vehicle_types":{"ICE":440,"BEV":200,...}}
- 食堂/医院（2个 REST 数据源）：返回简单数值（value + capacity）

## 可用工具
1. find_nearby_things(lat,lng,radius_km,thing_type?) → 半径内设施列表
2. query_parking_lot_*(query) → 自然语言查询指定停车场
3. query_cafeteria / query_hospital → 查询当前人数
4. aggregate(data,operations) → 跨源聚合（sum/avg/min/max/count/median/std），
   field 用点号嵌套路径如 structured.occupancy_rate
5. render_chart(option) → 生成 ECharts 对比图（bar/line/pie）

## 工作原则
- 理解需求后并行调用所有相关数据源（你的 tool_calls 会被自动并行执行）
- L2 返回的结构化数据可用于 aggregate 做跨源统计
- 各 L2 独立生成的图表在前端自动展示，无需你重复生成
- 图表是辅助手段，核心是有实质内容的文字分析

## 图表策略
- 跨源对比优先 bar/line（多系列），单源占比可用 pie
- 从 aggregate 的数值构建 chart option，不合并各 L2 原始 option
- 数据维度不兼容时勿强制生成图表，改为文字分析
- aggregate 返回的 _chart_hint 字段提供推荐图表类型
- render_chart 连续失败 2 次 → 立即终止图表生成，转为纯文字

## 时间约定
- 默认查当前/今天数据，不主动查超过 90 天历史
- 历史趋势查询限 7-30 天，按日聚合

## 错误处理
- L2 源 timeout/unavailable → 标记不可用，用剩余源继续，勿反复重试
- aggregate 结果为空或报错 → 检查 field 路径后重试一次，仍失败则跳过
- find_nearby_things 返回空 → 告知用户范围内无对应设施
- 其他工具错误 → 修正参数重试一次，仍失败则跳过并在文字中说明
- 即使无图表，必须输出含具体数值的有实质内容分析

当前用户位置: {user_lat}, {user_lng}
当前时间: {current_datetime}
"""


def _get_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        timeout=120.0,
    )


# ── 工具消息生成 ─────────────────────────────────────────

def _tool_message(tool_name: str, arguments: dict) -> str:
    """Generate a human-readable description for a tool invocation."""
    if tool_name == "find_nearby_things":
        thing_type = arguments.get("thing_type", "")
        radius = arguments.get("radius_km", "")
        type_str = f" ({thing_type})" if thing_type else ""
        return f"搜索{radius}km内设施{type_str}"

    if tool_name == "aggregate":
        ops = arguments.get("operations", [])
        if isinstance(ops, list) and ops:
            funcs = [op.get("func", "") for op in ops]
            return f"聚合数据 (函数: {', '.join(funcs)})"
        return "聚合数据"

    if tool_name == "render_chart":
        title = arguments.get("chart_title", "")
        return f"生成对比图表{f' ({title})' if title else ''}"

    # Bridge tools: use thing metadata for dynamic message generation
    thing_id = TOOL_NAME_TO_THING_ID.get(tool_name)
    if thing_id:
        thing = THING_MAP.get(thing_id, {})
        thing_name = thing.get("name", thing_id)
        query = arguments.get("query", "")
        if query:
            return f"查询{thing_name}{f': {query[:30]}...' if query else ''}"
        return f"查询{thing_name}"

    return f"执行 {tool_name}"


# ── 工具执行 ─────────────────────────────────────────────

async def _execute_l1_tool(tool_name: str, arguments: dict[str, Any]) -> dict:
    """Execute an L1 own tool (local Python function)."""
    executor = TOOL_EXECUTORS.get(tool_name)
    if not executor:
        return {"error": f"未知工具: {tool_name}"}

    try:
        result = executor(**arguments) if arguments else executor()
        return result if isinstance(result, dict) else {"result": result}
    except TypeError as e:
        return {"error": f"工具参数错误: {str(e)}"}
    except Exception as e:
        return {"error": f"工具执行失败: {str(e)}"}


async def _execute_bridge_tool(
    tool_name: str,
    arguments: dict[str, Any],
    message_id: str,
    send_sse: SSESender | None,
    history: list[dict] | None = None,
) -> dict:
    """
    Execute an L2 bridge tool via HTTP/SSE.

    Dispatches based on the thing's protocol:
    - agent_sse → query_agent_thing (SSE streaming)
    - http_rest → query_rest_thing (HTTP GET)
    """
    # O(1) lookup using pre-computed reverse map
    thing_id = TOOL_NAME_TO_THING_ID.get(tool_name)

    if not thing_id:
        return {"error": f"未找到工具 {tool_name} 对应的物"}

    thing = THING_MAP.get(thing_id)
    if not thing:
        return {"error": f"物 {thing_id} 未注册"}

    protocol = thing.get("protocol")

    if protocol == "agent_sse":
        query = arguments.get("query", "")
        return await query_agent_thing(
            thing=thing,
            message=query,
            history=history,
            message_id=message_id,
            send_sse=send_sse,
        )
    elif protocol == "http_rest":
        return await query_rest_thing(
            thing=thing,
            message_id=message_id,
            send_sse=send_sse,
        )
    else:
        return {"error": f"不支持的协议: {protocol}"}


# ── 主循环 ───────────────────────────────────────────────

async def agent_loop(
    user_message: str,
    history: list[dict] | None = None,
    send_sse: SSESender | None = None,
    model: str | None = None,
    thinking_mode: str | None = None,
    message_id: str = "",
) -> str:
    """
    Execute L1 Extended ReAct Agent loop.

    Args:
        user_message: 用户输入
        history: 对话历史
        send_sse: SSE 事件发送器
        model: 模型覆盖
        thinking_mode: thinking mode 覆盖
        message_id: 前端消息 ID（用于 source_* 事件绑定）

    Returns:
        助手完整回复文本
    """
    client = _get_client()

    # Build system prompt with user location
    user_lat, user_lng = config.load_user_default_location()
    now_str = datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M")
    system_content = (
        SYSTEM_PROMPT
        .replace("{user_lat}", str(user_lat))
        .replace("{user_lng}", str(user_lng))
        .replace("{current_datetime}", now_str)
    )

    messages: list[Any] = [{"role": "system", "content": system_content}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    # Chart failure tracking: prevent iteration exhaustion when chart types are incompatible
    MAX_CONSECUTIVE_CHART_FAILURES = 2
    chart_failures_in_a_row = 0

    for _ in range(config.MAX_ITERATIONS):
        # ── Chart failure guard: force text-only conclusion ──
        if chart_failures_in_a_row >= MAX_CONSECUTIVE_CHART_FAILURES:
            force_messages = list(messages) + [{
                "role": "system",
                "content": (
                    "图表生成已连续失败，通常因为各数据源的数据维度不兼容。"
                    "请根据已有的工具调用结果，直接输出文字分析总结。"
                    "不要调用任何工具，直接回复。"
                ),
            }]
            stream = await client.chat.completions.create(
                model=model or config.DEEPSEEK_MODEL,
                messages=force_messages,
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

            messages.append({"role": "assistant", "content": full_response})

            if send_sse:
                # Usage unavailable in guard path — we didn't make a non-streaming call
                await send_sse.done(usage=None)

            return full_response

        # Tool decision phase (non-streaming)
        response = await client.chat.completions.create(
            model=model or config.DEEPSEEK_MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            stream=False,
            extra_body={"thinking": {"type": thinking_mode or config.THINKING_MODE}},
        )

        assistant_msg = response.choices[0].message

        if assistant_msg.tool_calls:
            # ── Tool execution phase (PARALLEL) ──
            messages.append(assistant_msg)

            # Validate: only text OR tool_calls, not both
            if assistant_msg.content and assistant_msg.content.strip():
                # LLM returned both text and tool_calls — use only tool_calls per SPEC
                assistant_msg.content = None

            async def execute_one(tool_call):
                tool_name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}

                # Notify frontend: L1 tool running
                if send_sse:
                    await send_sse.tool_call(
                        tool_name=tool_name,
                        status="running",
                        arguments=arguments,
                        message=_tool_message(tool_name, arguments),
                    )

                # Yield to event loop so the SSE generator can stream the
                # "running" frame before the tool (especially sync L1 tools
                # like aggregate/render_chart) blocks the event loop.
                await asyncio.sleep(0)

                # Execute
                if tool_name in BRIDGE_TOOL_NAMES:
                    result = await _execute_bridge_tool(
                        tool_name, arguments, message_id, send_sse, history
                    )
                else:
                    result = await _execute_l1_tool(tool_name, arguments)

                # Notify frontend: L1 tool complete
                if send_sse:
                    if "error" in result:
                        err_msg = result.get("error", "")
                        if isinstance(err_msg, dict):
                            err_msg = json.dumps(err_msg, ensure_ascii=False)
                        await send_sse.tool_call(
                            tool_name=tool_name,
                            status="error",
                            arguments=arguments,
                            message=_tool_message(tool_name, arguments),
                            error=str(err_msg),
                        )
                    else:
                        await send_sse.tool_call(
                            tool_name=tool_name,
                            status="done",
                            arguments=arguments,
                            message=_tool_message(tool_name, arguments),
                            result_preview=_truncate_preview(result),
                        )

                        # If render_chart succeeded, push chart event
                        if tool_name == "render_chart" and result.get("status") == "rendered":
                            await send_sse.chart(
                                chart_id=result["chart_id"],
                                chart_type=result["chart_type"],
                                option=result["option"],
                            )

                return tool_call.id, result

            # Parallel execution of all tool_calls
            tasks = [execute_one(tc) for tc in assistant_msg.tool_calls]
            tool_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Append tool results to messages
            for tc, tr in zip(assistant_msg.tool_calls, tool_results):
                if isinstance(tr, Exception):
                    content = json.dumps({"error": str(tr)}, ensure_ascii=False)
                    call_id = tc.id
                    result_for_check = {"error": str(tr)}
                else:
                    call_id, result_for_check = tr
                    content = json.dumps(result_for_check, ensure_ascii=False)

                # Track consecutive render_chart failures for guard mechanism
                if tc.function.name == "render_chart":
                    if "error" in result_for_check:
                        chart_failures_in_a_row += 1
                    else:
                        chart_failures_in_a_row = 0

                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": content,
                })

        else:
            # ── Text response phase (streaming) ──
            stream = await client.chat.completions.create(
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

    # Max iterations exceeded
    error_msg = "抱歉，我暂时无法完成这个查询。请尝试换个方式提问。"
    if send_sse:
        await send_sse.text(error_msg)
        await send_sse.done(status="error")
    return error_msg


def _truncate_preview(result: dict, max_chars: int = 200) -> dict:
    """截断长结果用于 SSE 预览。深拷贝，不修改原始数据。"""
    s = json.dumps(result, ensure_ascii=False)
    if len(s) <= max_chars:
        return result
    preview = copy.deepcopy(result)
    for key in list(preview.keys()):
        val = preview[key]
        if isinstance(val, list) and len(val) > 5:
            preview[key] = f"[{len(val)} items]"
        elif isinstance(val, dict):
            for sub_key in list(val.keys()):
                if isinstance(val[sub_key], list) and len(val[sub_key]) > 5:
                    val[sub_key] = f"[{len(val[sub_key])} items]"
    return preview
