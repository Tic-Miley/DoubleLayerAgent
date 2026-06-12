"""
FastAPI 入口 — 停车场 AI Agent 演示系统。

提供 POST /api/chat SSE 端点。
"""

import asyncio
import json
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import config
from db import init_db
from models import ChatRequest
from agent import agent_loop
from sse import SSESender

app = FastAPI(title="ParkingLot AI Agent", version="1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    init_db()


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    SSE 流式对话端点。

    Request: { message: string, conversation_id?: string }
    Response: text/event-stream (SSE)
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()
        send_sse = SSESender(queue)

        # 创建后台任务运行 agent loop
        task = asyncio.create_task(
            agent_loop(
                user_message=request.message,
                history=request.history,
                send_sse=send_sse,
                model=request.model,
                thinking_mode=request.thinking_mode,
            )
        )

        try:
            while True:
                # 等待 SSE 事件或 agent 完成
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield data
                except asyncio.TimeoutError:
                    if task.done():
                        # agent 完成，排空队列中剩余事件
                        while not queue.empty():
                            yield queue.get_nowait()
                        # 检查是否有未捕获的异常
                        exc = task.exception()
                        if exc is not None:
                            # 记录异常到控制台日志
                            import traceback
                            print(f"[ERROR] agent_loop 异常: {type(exc).__name__}: {exc}", flush=True)
                            traceback.print_exception(exc)
                            error_msg = f"event: error\ndata: {json.dumps({'code': 'AGENT_ERROR', 'message': f'处理请求时遇到内部错误: {str(exc)}', 'retryable': False}, ensure_ascii=False)}\n\n"
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
    uvicorn.run("main:app", host="0.0.0.0", port=config.PORT, reload=True)
