"""
L1 Extended ReAct Agent Loop。

扩展自 ParkingLotAgent/backend/agent.py，核心改动：
1. 并行 tool_call 执行 — 同一轮 LLM 返回的多个 tool_calls 使用 asyncio.gather
2. L2 bridge tool executor 发起 HTTP/SSE 请求（而非本地函数调用）
3. SSE 事件透传 — L2 的 tool_call/chart 事件包装为 source_* 事件
4. L1 自有工具 (find_nearby_things, aggregate, render_chart) 直接调用
"""

import asyncio
import datetime
import json
from typing import Any

from openai import AsyncOpenAI

import config
from tools import TOOL_SCHEMAS, TOOL_EXECUTORS
from bridge import query_agent_thing, query_rest_thing
from sse import SSESender

# ── L1 Bridge tool names ─────────────────────────────────
# These are tools that call L2 things via HTTP/SSE
BRIDGE_TOOL_NAMES = {
    "query_parking_lot_a", "query_parking_lot_b", "query_parking_lot_c",
    "query_cafeteria", "query_hospital",
}

SYSTEM_PROMPT = """你是城市数据整合助手。你可以访问多个城市设施的数据服务。

## 能力
- 搜索附近设施（find_nearby_things）
- 查询各设施的数据（通过对应工具）
- 聚合多源数据（aggregate）
- 生成对比图表（render_chart）

## 工作流程
1. 理解用户问题，识别空间范围和数据需求
2. 如需空间筛选 → find_nearby_things
3. 对筛选结果并行查询各设施数据
4. 如需跨源统计 → aggregate
5. 综合回答 + 图表

## 数据源说明
L2 Agent 会以 JSON 格式返回结构化数据。你需要从返回结果中提取数值字段，
必要时使用 aggregate 工具做跨源统计。你可以向停车场查询任何数据——剩余车位、
历史趋势、车辆详情等。L2 Agent 通过 SQL 工具几乎能回答所有停车场相关问题。

## 当前用户位置
纬度: {user_lat}, 经度: {user_lng}
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

    if tool_name.startswith("query_parking_lot"):
        query = arguments.get("query", "")
        return f"查询停车场数据{f': {query[:30]}...' if query else ''}"

    if tool_name in ("query_cafeteria", "query_hospital"):
        return "查询人数数据"

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
    from config import THING_MAP, TOOL_SCHEMA_MAP

    # Find which thing this tool belongs to
    thing_id = None
    for tid, schema in TOOL_SCHEMA_MAP.items():
        if schema["function"]["name"] == tool_name:
            thing_id = tid
            break

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

    for _ in range(config.MAX_ITERATIONS):
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
                else:
                    call_id, result = tr
                    content = json.dumps(result, ensure_ascii=False)

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
    """截断长结果用于 SSE 预览。"""
    s = json.dumps(result, ensure_ascii=False)
    if len(s) <= max_chars:
        return result
    preview = dict(result)
    for key in list(preview.keys()):
        val = preview[key]
        if isinstance(val, list) and len(val) > 5:
            preview[key] = f"[{len(val)} items]"
        elif isinstance(val, dict):
            for sub_key in list(val.keys()):
                if isinstance(val[sub_key], list) and len(val[sub_key]) > 5:
                    val[sub_key] = f"[{len(val[sub_key])} items]"
    return preview
