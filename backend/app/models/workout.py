"""workouts / workout_sets —— 一次训练和它的组明细。

一次训练 = 一条 workouts（挂到当天的事件上），每个动作的每一组落一行 workout_sets。
动作库匹配不到时保留 exercise_name 快照，不阻塞记录。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, DateTimeMicro
from app.utils import now_local, today_local


class Workout(Base):
    __tablename__ = "workouts"
    __table_args__ = {"comment": "一次训练——挂在当天的合并事件上"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    event_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("events.id", ondelete="SET NULL"), nullable=True, index=True,
        comment="来源事件（当天的合并事件）",
    )
    performed_on: Mapped[date] = mapped_column(
        Date, nullable=False, default=today_local, index=True, comment="训练日期"
    )
    place: Mapped[str] = mapped_column(String(120), nullable=False, default="", comment="场地快照")
    duration_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="时长（分钟）")
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="训练", comment="训练标题")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="chat", comment="chat / manual")
    created_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, onupdate=now_local)


class WorkoutSet(Base):
    __tablename__ = "workout_sets"
    __table_args__ = {"comment": "一组训练明细——动作 / 重量 / 次数 / 时长"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workout_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exercise_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("exercises.id", ondelete="SET NULL"), nullable=True, index=True
    )
    exercise_name: Mapped[str] = mapped_column(String(120), nullable=False, default="", comment="动作名快照")
    exercise_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="动作在同一次训练里的顺序")
    set_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="第几组，从 1 开始")
    weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="计时动作（平板支撑等）")
    rpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_warmup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str] = mapped_column(String(120), nullable=False, default="")
