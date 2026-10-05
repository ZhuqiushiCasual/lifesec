"""events —— 合并后的事件（记忆），不是每一条消息。

一次对话里「今天跑了 40 分钟」和「又跑了 30 分钟」是**同一件事**，
所以要合并成一条事件，而不是堆成两条记录。

两个来源（source）：
  user   用户自己产生的事件（同一天合并后的结果，由 services/records.py 写）
  hermes 外部系统推来的消息（洞察，一条一事件，不参与合并）

与合并相关的字段：
  occurred_on   归属日期——「同一天才合并」的判定基准，也让统计可以纯 SQL 按天分组
  tags          AI 每次生成的标签（自由命名，不从固定清单里挑）
  recorded_at   第一次记到它的时间点
  last_at       最近一次被补充的时间点
  merged_count  这一天里被合并进来的消息条数（1 = 没合并过）
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, ForeignKey, Integer, JSON, String, Text
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
    __table_args__ = {"comment": "事件表——同一天合并后的事件（用户） / 外部洞察"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default=SOURCE_USER, comment="user / hermes")
    type: Mapped[str] = mapped_column(String(32), nullable=False, default=TYPE_RECORD, comment="record/plan/finance/insight/feeling")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="事件当前的完整表述（合并时整体替换）")
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="标题（洞察卡用）")
    entities: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="结构化字段（JSON）")
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, comment="AI 每次生成的标签（自由命名）")

    # 归属日期：同一天才合并；统计与回溯按它分组
    occurred_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True, comment="归属日期")

    # 去重键：Hermes 同一条新闻重复推送时按它幂等
    dedup_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    # 用 Python 侧默认值而不是 func.now()：后者只到「秒」，
    # 同一秒内落库的多条记录时间戳相同，ORDER BY 会不稳定；
    # 配合 DateTimeMicro（MySQL 侧 DATETIME(6)）才有足够分辨率
    recorded_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, index=True, comment="第一次记到它的时间点")
    last_at: Mapped[Optional[datetime]] = mapped_column(DateTimeMicro, nullable=True, index=True, comment="最近一次被补充的时间点")
    merged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1", comment="这一天里被合并进来的消息条数")
    created_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, comment="记录创建时间")
