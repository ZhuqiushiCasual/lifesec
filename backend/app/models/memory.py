"""memory_profile —— 4.1 长期画像（「总结意识」的产物）。

单用户单行：一段精炼的画像文本，version 递增保留演进痕迹。
对应 Hermes 的 user.md 设计思路——不在库里堆原始数据，而是定期压成一段"关于你的话"。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, DateTimeMicro
from app.utils import now_local


class MemoryProfile(Base):
    __tablename__ = "memory_profile"
    __table_args__ = {"comment": "长期画像表——「总结意识」的产物（单用户单行）"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, unique=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="画像正文（一段话）")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="版本号，每次重算 +1")
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="生成时依据的事件数（用于阈值判断）")
    updated_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, onupdate=now_local)
