"""plans —— 待办 / 目标（从 events 中提炼）。"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import JSON, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, DateTimeMicro
from app.utils import now_local

STATUS_OPEN = "open"
STATUS_DONE = "done"


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = {"comment": "待办 / 目标表"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_OPEN, comment="open / done")
    # due_date 保留给旧数据 / 旧接口；新计划同时写 scheduled_on
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    scheduled_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True, comment="计划日期")
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="todo", comment="todo / goal / meal / outing / travel / workout"
    )
    place: Mapped[str] = mapped_column(String(120), nullable=False, default="", comment="地点快照")
    ref_type: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, comment="来源类型：date_menu / outing_spot / workout / event"
    )
    ref_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, comment="来源 id")
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="动作列表等附加信息")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="chat", comment="chat / recall / manual")
    ref_event_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, onupdate=now_local)
