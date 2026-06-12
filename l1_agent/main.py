"""
FastAPI 入口 — Layer 1 Orchestrator Agent。

提供 POST /api/chat SSE 端点 + GET /api/health。
"""

import asyncio
import json
import time
import traceback
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import config
from models import ChatRequest
from agent import agent_loop
from sse import SSESender

app = FastAPI(title="DoubleLayerAgent L1", version="1.0")

# CORS — allow frontend dev server (backup, main path is Vite proxy)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _generate_message_id() -> str:
    """Generate a unique message ID for SSE event binding."""
    return f"msg_{int(time.time() * 1000)}_{id(object()) % 10000:04d}"


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    SSE 流式对话端点。

    Request: { message, conversation_id?, history?, model?, thinking_mode? }
    Response: text/event-stream (SSE)
    """
    message_id = _generate_message_id()

    async def event_generator() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()
        send_sse = SSESender(queue)

        task = asyncio.create_task(
            agent_loop(
                user_message=request.message,
                history=request.history,
                send_sse=send_sse,
                model=request.model,
                thinking_mode=request.thinking_mode,
                message_id=message_id,
            )
        )

        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield data
                except asyncio.TimeoutError:
                    if task.done():
                        while not queue.empty():
                            yield queue.get_nowait()
                        exc = task.exception()
                        if exc is not None:
                            print(f"[ERROR] agent_loop 异常: {type(exc).__name__}: {exc}", flush=True)
                            traceback.print_exception(exc)
                            error_msg = (
                                f"event: error\ndata: {json.dumps({'code': 'AGENT_ERROR', 'message': f'处理请求时遇到内部错误: {str(exc)}', 'retryable': False}, ensure_ascii=False)}\n\n"
                            )
                            yield error_msg
                        break
        except asyncio.CancelledError:
            task.cancel()
            yield f"event: done\ndata: {json.dumps({'status': 'stopped'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=config.L1_PORT, reload=True)
