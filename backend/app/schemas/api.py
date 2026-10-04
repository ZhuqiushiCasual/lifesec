"""全部请求 / 响应模型（接口少，集中放一个文件）。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── 卡片：窗口里唯一的结构化输出形式 ──────────────────────
class Card(BaseModel):
    kind: str                                   # record / plan / insight / greeting
    title: Optional[str] = None
    lines: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


# ── POST /api/chat ────────────────────────────────────────
class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    reply: str
    card: Optional[Card] = None
    message_id: str


# ── POST /api/insights（Hermes 回调）──────────────────────
class InsightIn(BaseModel):
    title: str
    summary: str
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    category: Optional[str] = None      # tech / finance / ...
    impact: Optional[str] = None
    topics: list[str] = Field(default_factory=list)
    importance: int = 3
    published_at: Optional[datetime] = None


class InsightOut(BaseModel):
    accepted: bool
    deduped: bool = False
    event_id: Optional[str] = None
    message_id: Optional[str] = None


# ── GET /api/messages（窗口流：用户轮 + 秘书轮合并）──────────
class StreamItemOut(BaseModel):
    id: str
    role: str        # me | secretary
    kind: str        # user / reply / greeting / insight / nudge
    content: str
    card: Optional[Card] = None
    created_at: datetime


# ── /api/plans ────────────────────────────────────────────
class PlanOut(BaseModel):
    id: str
    title: str
    status: str
    due_date: Optional[date] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PlanPatch(BaseModel):
    status: str = Field(pattern="^(open|done)$")


# ── /api/memory ───────────────────────────────────────────
class MemoryOut(BaseModel):
    profile: str
    version: int
    event_count: int
    updated_at: Optional[datetime] = None
