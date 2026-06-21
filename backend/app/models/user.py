from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from typing import Optional


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"comment": "用户表——存储用户账号信息"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), comment="用户唯一标识 UUID")
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, comment="登录邮箱")
    name: Mapped[str] = mapped_column(String(100), nullable=True, comment="用户昵称")
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希值（SHA-256）")
    preferences: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="用户偏好设置（JSON 字符串）")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="账号是否启用")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="最后更新时间"
    )

    events = relationship("Event", back_populates="user", lazy="selectin")
    finance_txns = relationship("FinanceTxn", back_populates="user", lazy="selectin")
    insights = relationship("Insight", back_populates="user", lazy="selectin")
    digests = relationship("Digest", back_populates="user", lazy="selectin")
