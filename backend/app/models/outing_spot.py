"""outing_spots —— 出门玩的候选（景点 / 展馆 / 公园 / 街区 / 活动）。

只描述「可以去哪」，不是已经发生的经历；经历仍然由 events / 后续的 experiences 承载。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, DateTimeMicro
from app.utils import now_local


class OutingSpot(Base):
    __tablename__ = "outing_spots"
    __table_args__ = {"comment": "出门玩的候选地点（种子 + 可增删）"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="景点", comment="景点 / 展馆 / 公园 / 街区 / 活动"
    )
    area: Mapped[str] = mapped_column(String(40), nullable=False, default="", comment="区域")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="一句提示")
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    sort: Mapped[int] = mapped_column(default=0, nullable=False, index=True)
    hidden: Mapped[bool] = mapped_column(default=False, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="seed")
    created_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local)
