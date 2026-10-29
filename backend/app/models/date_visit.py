"""date_visits —— 约会 / 探店记录。

和 date_menu 的分工：

    date_menu    想去哪吃（人工维护的菜单，前台给另一半挑）
    date_visits  去过了哪、吃得怎么样（从对话里长出来的事实）

一条记录 = 一次「已经发生的吃饭 / 会面」，不是一条消息。
同一天对同一家店的多次补充会更新同一条记录，不会堆出重复行。

关联方式：

    restaurant_id  能对上菜单时指向 date_menu.id
    restaurant_name / branch / cuisine
                   落库时的店名快照 —— 菜单项后来改名或删掉，
                   这条历史记录仍然知道自己说的是哪家店

    event_id       来源事件。事件层的「同一天合并」仍是唯一权威，
                   这里的去重只按「人 + 店 + 就餐日期」兜一层，
                   避免模型漏合并时同一天冒出两条一样的探店记录。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, DateTimeMicro
from app.utils import now_local, today_local


class DateVisit(Base):
    __tablename__ = "date_visits"
    __table_args__ = {"comment": "约会探店记录——一次吃饭/会面，可关联到 date_menu 的店"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)

    # 来源事件：事件合并后仍保留第一次的 event_id；只用于回溯，不做展示主键
    event_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("events.id", ondelete="SET NULL"), nullable=True, index=True,
        comment="来源事件（当天的合并事件）",
    )

    # 菜单关联：认不出来时为空，但店名快照仍然保留
    restaurant_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("date_menu.id", ondelete="SET NULL"), nullable=True, index=True,
        comment="关联的约会菜单项；对不上菜单时为空",
    )
    restaurant_name: Mapped[str] = mapped_column(String(120), nullable=False, default="", comment="店名快照")
    branch: Mapped[str] = mapped_column(String(80), nullable=False, default="", comment="分店快照")
    cuisine: Mapped[str] = mapped_column(String(80), nullable=False, default="", comment="菜系快照")

    visited_on: Mapped[date] = mapped_column(
        Date, nullable=False, default=today_local, index=True, comment="就餐/会面日期（不是记录时间）"
    )
    rating: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="主观评分 1–5（可以是 4.5）；没提为空"
    )
    dishes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, comment="提到的具体菜名")
    companion: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, comment="同行人")
    occasion: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True, comment="场合：约会 / 会面 / 聚餐 / 工作餐 / 一个人"
    )
    review: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="对这次吃饭/会面的评价或要点")

    source: Mapped[str] = mapped_column(String(16), nullable=False, default="chat", comment="来源：chat / date-picker ...")

    created_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, onupdate=now_local)
