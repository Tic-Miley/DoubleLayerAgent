"""SSE event sender for L1 — extends ParkingLotAgent SSESender with source_* events."""

import asyncio
import json
from typing import Any


def format_sse(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE event."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class SSESender:
    """
    L1 SSE 事件发送器。

    新增 source_* 事件用于 L2 物状态透传：
    - source_start: L1 开始调用某个 L2 物
    - source_tool_call: L2 内部的工具调用状态
    - source_chart: L2 生成的图表
    - source_done: L2 查询完成
    - source_error: L2 查询失败
    """

    def __init__(self, queue: asyncio.Queue):
        self._queue = queue
        self._lock = asyncio.Lock()
        self._chart_counter = 0

    async def _send(self, event: str, data: dict[str, Any]) -> None:
        """Thread-safe SSE event send."""
        async with self._lock:
            await self._queue.put(format_sse(event, data))

    # ── L1 自有事件 ──────────────────────────────────────
    async def tool_call(self, tool_name: str, status: str, **kwargs) -> None:
        data = {"tool_name": tool_name, "status": status}
        data.update(kwargs)
        await self._send("tool_call", data)

    async def text(self, token: str) -> None:
        await self._send("text", {"token": token})

    async def chart(self, chart_id: str, chart_type: str, option: dict) -> None:
        await self._send("chart", {
            "chart_id": chart_id,
            "chart_type": chart_type,
            "option": option,
        })

    async def done(self, usage: dict | None = None, status: str = "completed") -> None:
        data = {"status": status}
        if usage:
            data["usage"] = usage
        await self._send("done", data)

    async def error(self, code: str, message: str, retryable: bool = False) -> None:
        await self._send("error", {
            "code": code,
            "message": message,
            "retryable": retryable,
        })

    # ── L2 透传事件 (source_*) ────────────────────────────
    async def source_start(
        self, message_id: str, source_id: str, source_name: str, tool_name: str
    ) -> None:
        await self._send("source_start", {
            "message_id": message_id,
            "source_id": source_id,
            "source_name": source_name,
            "tool_name": tool_name,
        })

    async def source_tool_call(
        self, message_id: str, source_id: str, tool_name: str,
        status: str, arguments: dict | None = None,
        message: str | None = None,
        result_preview: str | None = None, error: str | None = None,
    ) -> None:
        data = {
            "message_id": message_id,
            "source_id": source_id,
            "tool_name": tool_name,
            "status": status,
        }
        if arguments:
            data["arguments"] = arguments
        if message:
            data["message"] = message
        if result_preview:
            data["result_preview"] = result_preview
        if error:
            data["error"] = error
        await self._send("source_tool_call", data)

    async def source_chart(
        self, message_id: str, source_id: str,
        chart_id: str, chart_type: str, option: dict,
    ) -> None:
        await self._send("source_chart", {
            "message_id": message_id,
            "source_id": source_id,
            "chart_id": chart_id,
            "chart_type": chart_type,
            "option": option,
        })

    async def source_done(
        self, message_id: str, source_id: str,
        status: str = "done", summary: str | None = None,
    ) -> None:
        data = {
            "message_id": message_id,
            "source_id": source_id,
            "status": status,
        }
        if summary:
            data["summary"] = summary
        await self._send("source_done", data)

    async def source_error(
        self, message_id: str, source_id: str, error: str,
    ) -> None:
        await self._send("source_error", {
            "message_id": message_id,
            "source_id": source_id,
            "error": error,
        })
