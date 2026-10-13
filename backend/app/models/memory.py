"""memory_profile —— 4.1 长期画像（「总结意识」的产物）+ 版本历史。

单用户单行。对应 Hermes 的 user.md 的思路——不在库里堆原始数据，
而是定期压成"关于你的话"，之后每次组装 Context 都注入这一段。

v3 之后画像从"一段自由文本"变成**分节结构**，抄的是 Gemini 的核心洞察：
各节的"半衰期"不同（身份几乎不变、正在做的事每周在变），
分开存才能**只重算变了的那一节**，而不是每天重新描写一遍你的人生。

    content    渲染后的全文（接口 / 兜底用，也是给人看的形态）
    sections   分节正文：identity / style / avoid / current / insight
    sources    每节的来源事件 id 与更新时间（provenance，回答"你凭什么这么说"）
    summary    最近一次迭代的变更摘要（+新增 / ~修正 / -删除），会作为 nudge 推给用户
    msg_count  生成时的用户消息总数——"每 20 轮"这个时钟的判断依据

硬上限：整段画像 ≤ PORTRAIT_CHAR_LIMIT（默认 1500 字符）。
画像越长越不被遵守，而且这份 token 每轮都要付——所以宁可少写、定期重写。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, DateTimeMicro
from app.utils import now_local


class MemoryProfile(Base):
    __tablename__ = "memory_profile"
    __table_args__ = {"comment": "长期画像表——「总结意识」的产物（单用户单行，分节）"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, unique=True, index=True)

    content: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="画像正文（分节渲染后的全文）")
    sections: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="分节画像：identity / style / avoid / current / insight"
    )
    sources: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="每节的来源事件 id 与更新时间（provenance）"
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="最近一次迭代的变更摘要")

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="版本号，每次重算 +1")
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="生成时依据的事件数（用于阈值判断）")
    msg_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="生成时的用户消息总数（「每 20 轮」的判断依据）"
    )
    updated_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, onupdate=now_local)


class ProfileVersion(Base):
    """画像的版本历史——每次迭代留一份，可回溯、可回滚。

    防漂移的最后一环：画像每次重算都是 LLM 生成、非确定性的，
    留历史才能回答"它对我的理解是什么时候变的、变成什么样了"。
    """

    __tablename__ = "profile_versions"
    __table_args__ = {"comment": "画像版本历史——每次迭代留一份，可回溯 / 可回滚"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, comment="对应的画像版本号")
    sections: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="该版本的分节正文")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="该版本渲染后的全文")
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="相对上一版的变更摘要")
    reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, comment="触发原因：turn / daily / manual / questionnaire")
    created_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, index=True)
