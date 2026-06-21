from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from typing import Optional


class Insight(Base):
    __tablename__ = "insights"
    __table_args__ = {"comment": "信息洞察表——存储 AI 提取的知识、观点、文章摘要"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), comment="洞察唯一标识 UUID")
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, comment="关联用户 ID")
    title: Mapped[str] = mapped_column(String(500), nullable=False, comment="洞察标题")
    summary: Mapped[str] = mapped_column(Text, nullable=False, comment="核心摘要")
    impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="对我生活/工作的影响分析")
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="洞察类别（如 tech / finance / health / career）"
    )
    topics: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True, comment="相关主题标签（JSON 数组）")
    importance: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="重要程度（1~5）")
    source_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True, comment="来源链接")
    source_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, comment="来源名称（如 知乎 / 公众号）")
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="原文发布时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="记录创建时间")

    user = relationship("User", back_populates="insights")
