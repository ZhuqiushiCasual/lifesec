from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from typing import Optional


class Event(Base):
    __tablename__ = "events"
    __table_args__ = {"comment": "事件记录表——记录用户生活事件（语音/文字输入）"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), comment="事件唯一标识 UUID")
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, comment="关联用户 ID")
    type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="事件类型（如 life_habit / social / work / health）"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="事件原始内容文本")
    entities: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="提取的实体信息（JSON）")
    sentiment: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="情感倾向（positive / neutral / negative）")
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="情感得分（0~1）")
    tags: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True, comment="标签列表（JSON 数组）")
    voice_source: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否来自语音输入")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="事件发生时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="记录创建时间")

    user = relationship("User", back_populates="events")
