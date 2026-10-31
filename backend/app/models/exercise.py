"""exercises —— 动作库（训练的结构化锚点）。

只存元数据，不随仓库分发演示媒体：
  media_path 指向本地 `backend/media/exercises/...`，没有文件时前端降级成文字。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, DateTimeMicro
from app.utils import now_local


class Exercise(Base):
    __tablename__ = "exercises"
    __table_args__ = {"comment": "动作库——训练动作的元数据与别名"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(80), nullable=False, index=True, comment="中文名")
    name_en: Mapped[str] = mapped_column(String(120), nullable=False, default="", comment="英文名")
    body_part: Mapped[str] = mapped_column(
        String(16), nullable=False, default="全身", index=True, comment="胸 / 背 / 腿 / 臀 / 肩 / 手臂 / 核心 / 全身"
    )
    equipment: Mapped[str] = mapped_column(
        String(16), nullable=False, default="其他", index=True, comment="杠铃 / 哑铃 / 器械 / 绳索 / 自重 / 其他"
    )
    target: Mapped[str] = mapped_column(String(80), nullable=False, default="", comment="主要肌群")
    aliases: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, comment="别名 / 英文检索词")
    media_path: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", comment="本地演示媒体相对路径；不存在时降级为文字"
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="seed", comment="seed / user")
    created_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local)
