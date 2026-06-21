from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from typing import Optional


class Digest(Base):
    __tablename__ = "digests"
    __table_args__ = {"comment": "日报表——每日自动生成的用户生活总结"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), comment="日报唯一标识 UUID")
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, comment="关联用户 ID")
    date: Mapped[date] = mapped_column(Date, nullable=False, comment="日报日期")
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="当日生活评分（0~100）")
    highlights: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="今日亮点（JSON 结构体）")
    problems: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="今日问题（JSON 结构体）")
    suggestions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="改进建议（JSON 结构体）")
    trends: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="趋势分析（JSON 结构体）")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="记录创建时间")

    user = relationship("User", back_populates="digests")
