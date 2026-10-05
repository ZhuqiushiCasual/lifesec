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
    event_id: Optional[str] = None    # 这条输入归入/新建的事件
    merged: bool = False              # 是并入了今天已有的事件，还是新建了一条


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


# ── GET /api/messages（窗口流 / 回溯）─────────────────────
class StreamItemOut(BaseModel):
    id: str
    role: str                        # me | secretary | event
    kind: str                        # user / reply / greeting / insight / nudge | record / plan / ...
    content: str
    card: Optional[Card] = None
    tags: list[str] = Field(default_factory=list)   # 事件才带（AI 生成的标签）
    merged_count: int = 1            # 事件才带：这一天里被合并进来的消息条数
    occurred_on: Optional[date] = None              # 事件才带：归属日期
    created_at: datetime             # 消息=说话时间点；事件=第一次记到它的时间点


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
