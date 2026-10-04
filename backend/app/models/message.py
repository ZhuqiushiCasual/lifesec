"""messages —— 它说的话。

系统对用户的每一次回应都落在这里：记录反馈、问候、洞察提示、抚慰。
card 让前端不用再 join events 就能渲染卡片（简易优先）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils import now_local

# kind 取值
KIND_REPLY = "reply"        # 对用户输入的回应
KIND_GREETING = "greeting"  # 定时问候
KIND_INSIGHT = "insight"    # 洞察提示
KIND_NUDGE = "nudge"        # 追问 / 抚慰


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = {"comment": "消息表——系统说的话（所有回应）"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default=KIND_REPLY)
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="回应正文（一句话）")
    card: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="附带的卡片（JSON，可空）")
    ref_event_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, comment="关联事件（不设外键，避免牵连删除）")
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="已读时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, index=True)
