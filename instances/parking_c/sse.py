"""SSE event sender for FastAPI streaming responses."""

import json
from typing import Any, AsyncIterator


def format_sse(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE event."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def sse_event(event: str, data: dict[str, Any]) -> str:
    """Return a formatted SSE event string (for async generator)."""
    return format_sse(event, data)


class SSESender:
    """
    SSE 事件发送器。封装 send 回调，供 agent loop 使用。

    使用方式：
        async def agent_loop(..., send_sse: SSESender):
            await send_sse.tool_call(...)
            await send_sse.text(...)
    """

    def __init__(self, queue):
        self._queue = queue
        self._chart_counter = 0

    async def _send(self, event: str, data: dict[str, Any]) -> None:
        await self._queue.put(format_sse(event, data))

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
