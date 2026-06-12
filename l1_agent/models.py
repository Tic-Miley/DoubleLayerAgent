"""Pydantic models for L1 Agent request/response."""

from typing import Optional
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    history: Optional[list[dict]] = None
    model: Optional[str] = None
    thinking_mode: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = "ok"
