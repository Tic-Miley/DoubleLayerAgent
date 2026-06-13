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

SYSTEM_PROMPT = """你是城市数据整合助手。你可以访问多个城市设施的数据服务。

## 能力
- 搜索附近设施（find_nearby_things）
- 查询各设施的数据（通过对应工具）
- 聚合多源数据（aggregate）——支持 sum/avg/min/max/count/median/std，
  field 使用点号分隔的嵌套路径，如 structured.occupancy_rate
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

每个 L2 返回结果中可能包含 chart_types 字段，表明该源生成的图表类型。
各 L2 生成的独立图表会自动在前端展示，你无需为它们重新生成。

aggregate 工具的返回结果中包含 _chart_hint 字段（值为 bar/line/pie），
这是根据数据形状推断的推荐图表类型，生成 render_chart 时应优先参考。

## 图表策略
- 跨源对比图表推荐使用 bar 或 line（支持多系列），pie 只适合单源占比展示
- 从 aggregate 返回的数值结果构建图表 option，不要直接合并各 L2 的原始 chart option
- 当各源数据维度无法统一到单一图表时（如 A 源=时序趋势、B 源=车型分布、C 源=比例构成），
  **不要强制生成图表**——改为输出文字对比分析，引用各源的具体数值
- 图表是可选辅助手段，有实质内容的文字分析才是核心输出

### 处理数据维度不匹配
1. 若 2/3 源数据维度兼容，为兼容源生成对比图表，不兼容源在文字中单独讨论
2. 若没有任何源的数据维度兼容：输出纯文字分析，逐一引用各源的结构化数值
3. 可针对特定 L2 发送补充查询获取兼容数据（如 "请给出按车型分类的当前在场车辆数"），
   但注意每次重查询耗时较长，优先使用已有数据做文字分析

## 查询时间范围建议
- 默认查询"当前"或"今天"的数据，避免不必要的大范围历史查询
- 历史趋势查询建议限定在最近 7-30 天，按日聚合即可
- 除非用户明确要求，不要查询超过 90 天的历史数据

## 错误恢复
- L2 数据源返回 timeout 或 unavailable 错误：在文字中注明该源不可用，使用其余源
  继续分析，不要反复重试同一不可用源
- render_chart 连续失败 2 次后：立即停止尝试生成图表
- 转为纯文字分析——利用各 L2 返回的结构化数值做跨源对比
- 即使没有对比图表，也必须输出有实质内容的分析，引用具体数字
- 其他工具错误：修正参数重试一次，连续失败后跳过并在文字中说明

## 当前用户位置
纬度: {user_lat}, 经度: {user_lng}

## 当前时间
{current_datetime}
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
