"""messages —— 窗口里的全部消息（我说的 + 它说的）。

一张表覆盖整个窗口，是历史对话渲染的唯一来源：

    role=me         我说的每一句。**原样保留、永不改写**，时间点就是 created_at；
                    它归入哪条事件由 ref_event_id 表示
    role=secretary  它说的每一句（回应 / 问候 / 洞察 / 抚慰）

窗口流只查这一张表，不再跨表归并，因而同一秒落库也不会错序。
「合并后的事件」在 events 里，那属于记忆层，不参与窗口渲染。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, DateTimeMicro
from app.utils import now_local

# role 取值
ROLE_ME = "me"                 # 我说的
ROLE_SECRETARY = "secretary"   # 它说的

# kind 取值
KIND_USER = "user"          # 我说的（role 恒为 me）
KIND_REPLY = "reply"        # 对用户输入的回应
KIND_GREETING = "greeting"  # 定时问候
KIND_INSIGHT = "insight"    # 洞察提示
KIND_NUDGE = "nudge"        # 追问 / 抚慰


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = {"comment": "消息表——窗口里的全部消息（我说的 + 它说的）"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=ROLE_SECRETARY, comment="me / secretary")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default=KIND_REPLY)
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="原话 / 回应正文（一句话）")
    card: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="附带的卡片（JSON，可空）")
    ref_event_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, comment="关联事件：我说的这条归入的事件 / 这条回应所回应的事件"
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTimeMicro, nullable=True, comment="已读时间")
    # 时间点标记：窗口里「什么时候说的」完全由它决定
    created_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, index=True)
