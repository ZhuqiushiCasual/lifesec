"""采集层请求 / 响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── 源配置 ───────────────────────────────────────────────
class SourceBase(BaseModel):
    name: str
    home_url: str
    feed_url: Optional[str] = None
    kind: str = "rss"                 # rss / json_api / html / github
    level: str = "L0"
    category: str = "tech"
    enabled: bool = True
    priority: int = 5
    max_items: int = 12
    interval_minutes: int = 1440
    config: dict[str, Any] = Field(default_factory=dict)


class SourceCreate(SourceBase):
    key: str


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    home_url: Optional[str] = None
    feed_url: Optional[str] = None
    kind: Optional[str] = None
    level: Optional[str] = None
    category: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    max_items: Optional[int] = None
    interval_minutes: Optional[int] = None
    config: Optional[dict[str, Any]] = None


class SourceOut(SourceBase):
    id: str
    key: str
    last_run_at: Optional[datetime] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None

    class Config:
        from_attributes = True


# ── 任务 ─────────────────────────────────────────────────
class TaskCreate(BaseModel):
    source_keys: list[str] = Field(default_factory=list, description="空 = 全部启用源")
    trigger: str = "manual"


class TaskOut(BaseModel):
    id: str
    trigger: str
    status: str
    source_keys: list[str] = Field(default_factory=list)
    worker: Optional[str] = None
    dispatched_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    stats: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ClaimOut(BaseModel):
    task: TaskOut
    sources: list[SourceOut] = Field(default_factory=list)
    api_base: str
    message_api: str = "/api/ingest/messages"


class RunIn(BaseModel):
    source_key: str
    source_name: str = ""
    status: str = "succeeded"          # running / succeeded / failed / skipped
    fetch_level: Optional[str] = None
    items_found: int = 0
    items_new: int = 0
    items_updated: int = 0
    items_failed: int = 0
    error: Optional[str] = None
    detail: dict[str, Any] = Field(default_factory=dict)


class RunOut(RunIn):
    id: str
    task_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FinishIn(BaseModel):
    status: str = "succeeded"          # succeeded / partial / failed
    error: Optional[str] = None
    stats: dict[str, Any] = Field(default_factory=dict)


# ── 消息（洞察）───────────────────────────────────────────
class MessageIn(BaseModel):
    source_key: Optional[str] = None
    source_name: Optional[str] = None
    title: str
    summary: str = ""
    detail: Optional[str] = None
    source_url: Optional[str] = None
    url: Optional[str] = None           # runner 中间格式用的字段名；有 source_url 时以它为准
    published_at: Optional[datetime] = None
    category: Optional[str] = None
    topics: list[str] = Field(default_factory=list)
    impact: Optional[str] = None
    importance: int = 3
    content: Optional[str] = None       # 原文纯文本（截断后入库）
    fetch_level: Optional[str] = None
    raw_hash: Optional[str] = None
    batch_id: Optional[str] = None


class MessageBatchIn(BaseModel):
    task_id: Optional[str] = None
    items: list[MessageIn] = Field(default_factory=list)


class MessagePatch(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    detail: Optional[str] = None
    impact: Optional[str] = None
    category: Optional[str] = None
    topics: Optional[list[str]] = None
    importance: Optional[int] = None
    status: Optional[str] = None        # new / read / hidden
    source_url: Optional[str] = None
    source_name: Optional[str] = None


class MessageMergeIn(BaseModel):
    primary_id: str
    duplicate_ids: list[str] = Field(default_factory=list)
    title: Optional[str] = None


class MessageOut(BaseModel):
    event_id: str
    message_id: Optional[str] = None
    title: str
    summary: str
    detail: Optional[str] = None
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    source_key: Optional[str] = None
    category: Optional[str] = None
    topics: list[str] = Field(default_factory=list)
    impact: Optional[str] = None
    importance: int = 3
    published_at: Optional[datetime] = None
    status: str = "new"
    tags: list[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MessageBatchOut(BaseModel):
    accepted: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    event_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
