"""用户表——单用户项目，仅作外键锚点，无注册/登录。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils import now_local


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"comment": "用户表（单用户，仅作外键锚点）"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="用户 UUID")
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="我", comment="昵称")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, comment="创建时间")
