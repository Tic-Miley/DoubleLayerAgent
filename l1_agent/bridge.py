"""
L2 物桥接层 — HTTP/SSE Tool Executor 工厂。

为每个 L2 物创建 executor，统一返回：
{
    source: str,
    structured: dict | None,
    summary: str,
    tool_results?: list[dict],
    charts?: list[dict],
    error?: str,
}
"""

import json
import logging
from typing import Any

import httpx

import config
from sse import SSESender

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict | None:
    """
    从文本中提取最后一个顶级 JSON 对象。

    算法：
    1. 在 text 中定位所有顶级 `{` 及其匹配的 `}`
    2. 对每个括号对，尝试 json.loads()；解析成功则记为候选
    3. 存在多个候选 → 取最后一个（L2 System Prompt 要求摘要 JSON 在末尾）
    4. text 为空或无合法 JSON → 返回 None
    """
    if not text:
        return None

    candidates = []
    depth = 0
    start = -1

    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    obj = json.loads(text[start:i + 1])
                    if isinstance(obj, dict):
                        candidates.append(obj)
                except json.JSONDecodeError:
                    pass
                start = -1

    if not candidates:
        logger.warning(f"_extract_json: no valid JSON found in text ({len(text)} chars)")
        return None

    return candidates[-1]


async def query_agent_thing(
    thing: dict,
    message: str,
    history: list[dict] | None = None,
    message_id: str = "",
    send_sse: SSESender | None = None,
) -> dict:
    """
    通过 SSE 调用 Agent 类 L2 物。

    Args:
        thing: things.yaml 中的物元数据
        message: 转发给 L2 的自然语言查询
        history: 可选透传的对话历史
        message_id: 前端消息 ID（用于 source_* 事件绑定）
        send_sse: SSE 事件发送器

    Returns:
        {source, tool_results, charts, summary, structured, error?}
    """
    source_id = thing["id"]
    endpoint = thing["endpoint"]
    tool_name = f"query_{source_id}"

    # Notify frontend: source_start (BEFORE the HTTP request)
    if send_sse:
        await send_sse.source_start(
            message_id=message_id,
            source_id=source_id,
            source_name=thing["name"],
            tool_name=tool_name,
        )

    request_body: dict[str, Any] = {"message": message}
    if history:
        request_body["history"] = history

    tool_results: list[dict] = []
    charts: list[dict] = []
    final_text = ""

    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", endpoint,
                json=request_body,
                timeout=config.L2_TIMEOUT_SECONDS,
            ) as response:
                event_type = "message"
                data_buffer: list[str] = []

                async for line in response.aiter_lines():
                    if line == "":
                        # Empty line = event boundary → flush buffer
                        if data_buffer and event_type != "text":
                            data_str = "\n".join(data_buffer)
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                logger.warning(
                                    f"L2 {source_id} SSE parse error, "
                                    f"skipping event {event_type}: {data_str[:200]}"
                                )
                                event_type = "message"
                                data_buffer = []
                                continue

                            if event_type == "tool_call":
                                tool_results.append(data)
                                if send_sse:
                                    await send_sse.source_tool_call(
                                        message_id=message_id,
                                        source_id=source_id,
                                        tool_name=data.get("tool_name", ""),
                                        status=data.get("status", "running"),
                                        arguments=data.get("arguments"),
                                        result_preview=data.get("result_preview"),
                                        error=data.get("error"),
                                    )
                            elif event_type == "chart":
                                charts.append(data)
                                if send_sse:
                                    await send_sse.source_chart(
                                        message_id=message_id,
                                        source_id=source_id,
                                        chart_id=data.get("chart_id", ""),
                                        chart_type=data.get("chart_type", ""),
                                        option=data.get("option", {}),
                                    )
                            elif event_type == "done":
                                final_text = data.get("final_text", "")
                            elif event_type == "error":
                                l2_error = data.get("error", "L2 unknown error")
                                logger.error(f"L2 {source_id} error: {l2_error}")
                                if not final_text:
                                    final_text = f"[L2 Error] {l2_error}"

                        event_type = "message"
                        data_buffer = []
                    elif line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_buffer.append(line[5:].strip())

        # Extract structured JSON from final text
        structured = _extract_json(final_text)

        result = {
            "source": source_id,
            "tool_results": tool_results,
            "charts": charts,
            "chart_types": list({c.get("chart_type") for c in charts if c.get("chart_type")}),
            "summary": final_text,
            "structured": structured,
        }

        if send_sse:
            await send_sse.source_done(
                message_id=message_id,
                source_id=source_id,
                status="done",
                summary=final_text[:500] if final_text else None,
            )

        return result

    except httpx.TimeoutException:
        error_msg = f"查询超时（超过 {config.L2_TIMEOUT_SECONDS} 秒）"
        logger.error(f"L2 {source_id}: {error_msg}")
        if send_sse:
            await send_sse.source_error(message_id, source_id, error_msg)
        return {
            "source": source_id,
            "error": "timeout",
            "message": error_msg,
            "structured": None,
            "summary": error_msg,
            "tool_results": [],
            "charts": [],
        }

    except httpx.ConnectError:
        error_msg = "数据源不可用"
        logger.error(f"L2 {source_id}: {error_msg}")
        if send_sse:
            await send_sse.source_error(message_id, source_id, error_msg)
        return {
            "source": source_id,
            "error": "unavailable",
            "message": error_msg,
            "structured": None,
            "summary": error_msg,
            "tool_results": [],
            "charts": [],
        }

    except Exception as e:
        error_msg = f"查询失败: {str(e)}"
        logger.error(f"L2 {source_id}: {error_msg}")
        if send_sse:
            await send_sse.source_error(message_id, source_id, error_msg)
        return {
            "source": source_id,
            "error": "unknown",
            "message": error_msg,
            "structured": None,
            "summary": error_msg,
            "tool_results": [],
            "charts": [],
        }


async def query_rest_thing(
    thing: dict,
    message_id: str = "",
    send_sse: SSESender | None = None,
) -> dict:
    """
    通过 HTTP GET 调用简单物。

    Returns:
        {source, structured, summary, timestamp}
    """
    source_id = thing["id"]
    endpoint = thing["endpoint"]
    tool_name = f"query_{source_id}"

    if send_sse:
        await send_sse.source_start(
            message_id=message_id,
            source_id=source_id,
            source_name=thing["name"],
            tool_name=tool_name,
        )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(endpoint, timeout=5.0)
            resp.raise_for_status()
            data = resp.json()

        result = {
            "source": source_id,
            "structured": {
                "value": data.get("value", 0),
                "capacity": data.get("capacity", 0),
            },
            "summary": f"当前{data.get('value', 0)}人 (容量{data.get('capacity', 0)})",
            "timestamp": data.get("timestamp", ""),
        }

        if send_sse:
            await send_sse.source_done(
                message_id=message_id,
                source_id=source_id,
                status="done",
                summary=result["summary"],
            )

        return result

    except httpx.TimeoutException:
        error_msg = "查询超时"
        logger.error(f"REST {source_id}: {error_msg}")
        if send_sse:
            await send_sse.source_error(message_id, source_id, error_msg)
        return {"source": source_id, "error": "timeout", "message": error_msg, "structured": None, "summary": error_msg}

    except httpx.ConnectError:
        error_msg = "数据源不可用"
        logger.error(f"REST {source_id}: {error_msg}")
        if send_sse:
            await send_sse.source_error(message_id, source_id, error_msg)
        return {"source": source_id, "error": "unavailable", "message": error_msg, "structured": None, "summary": error_msg}

    except Exception as e:
        error_msg = f"查询失败: {str(e)}"
        logger.error(f"REST {source_id}: {error_msg}")
        if send_sse:
            await send_sse.source_error(message_id, source_id, error_msg)
        return {"source": source_id, "error": "unknown", "message": error_msg, "structured": None, "summary": error_msg}
