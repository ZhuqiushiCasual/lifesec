"""events —— 进来的东西。

两个来源（source）：
  user   用户自己说的话（记录 / 规划 / 情绪）
  hermes 外部系统推来的消息（洞察）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, DateTimeMicro
from app.utils import now_local

# source 取值
SOURCE_USER = "user"
SOURCE_HERMES = "hermes"

# type 取值
TYPE_RECORD = "record"    # 生活记录
TYPE_PLAN = "plan"        # 待办 / 目标
TYPE_FINANCE = "finance"  # 财务（由原独立模块降级而来）
TYPE_INSIGHT = "insight"  # 外部洞察
TYPE_FEELING = "feeling"  # 情绪表达


class Event(Base):
    __tablename__ = "events"
    __table_args__ = {"comment": "事件表——进来的东西（用户输入 / Hermes 推送）"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default=SOURCE_USER, comment="user / hermes")
    type: Mapped[str] = mapped_column(String(32), nullable=False, default=TYPE_RECORD, comment="record/plan/finance/insight/feeling")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="原始文本（用户原话 / 洞察摘要）")
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="标题（洞察卡用）")
    entities: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="结构化字段（JSON）")

    # 去重键：Hermes 同一条新闻重复推送时按它幂等
    dedup_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    # 用 Python 侧默认值而不是 func.now()：后者只到「秒」，
    # 同一秒内落库的多条记录时间戳相同，ORDER BY 会不稳定；
    # 配合 DateTimeMicro（MySQL 侧 DATETIME(6)）才有足够分辨率
    recorded_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, index=True, comment="事件发生时间")
    created_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, comment="记录创建时间")
