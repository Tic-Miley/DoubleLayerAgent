"""Pydantic models for request/response/SSE events."""

from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Request ───────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    history: Optional[list[dict]] = None  # 多轮对话历史 [{role, content}, ...]
    model: Optional[str] = None  # 前端可指定模型，覆盖 .env 默认值
    thinking_mode: Optional[str] = None  # "enabled" | "disabled"，覆盖 .env 默认值


# ── SSE Events ────────────────────────────────────────

class ToolCallEvent(BaseModel):
    tool_name: str
    status: str  # "running" | "done" | "error"
    arguments: Optional[dict[str, Any]] = None
    message: Optional[str] = None
    result_preview: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class TextEvent(BaseModel):
    token: str


class ChartEvent(BaseModel):
    chart_id: str
    chart_type: Optional[str] = None
    option: dict[str, Any]


class DoneEvent(BaseModel):
    status: str = "completed"  # "completed" | "stopped" | "error"
    usage: Optional[dict[str, int]] = None


class ErrorEvent(BaseModel):
    code: str
    message: str
    retryable: bool = False


# ── Internal ──────────────────────────────────────────

class ToolResult(BaseModel):
    """Wrapper for tool execution result."""
    success: bool = True
    data: Any = None
    error: Optional[str] = None
