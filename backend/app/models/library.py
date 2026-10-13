"""馆藏 —— 索引卡（tag_index）与标签别名（tag_aliases）。

**索引卡是派生产物，不是真相源。**
一行一个标签：「标签 → 条数 → 最近时间 → 一句话档首摘要」。
它可以从 events 重建（rebuild_index），丢了不心疼；events 里的事件原文永远是真相源。

为什么要有它：模型每轮只能看到 60 行目录，而不是几千条事件。
命中某个标签之后，才去取那一档的摘要与最近几条原文（渐进式加载）。

digest_count 记录"生成这份摘要时该标签有多少条"，
用来判断是否需要重算摘要（有新增才重算），避免每次迭代都重写全部标签。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, DateTimeMicro
from app.utils import now_local


class TagIndex(Base):
    """索引卡的一行（单用户单标签一行）。"""

    __tablename__ = "tag_index"
    __table_args__ = (
        UniqueConstraint("user_id", "tag", name="uq_tag_index_user_tag"),
        {"comment": "馆藏索引卡——按标签聚合的目录（派生产物，可从 events 重建）"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    tag: Mapped[str] = mapped_column(String(64), nullable=False, comment="规范化之后的标签名")
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="该标签下的事件条数")
    last_at: Mapped[Optional[datetime]] = mapped_column(DateTimeMicro, nullable=True, comment="该标签最近一次被提到的时间")

    digest: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="档首摘要——一句话，供索引卡使用")
    digest_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="生成这份摘要时该标签的条数")
    built_at: Mapped[Optional[datetime]] = mapped_column(DateTimeMicro, nullable=True, comment="摘要生成时间")

    # 可追溯：这份摘要依据了哪些事件（便于"为什么这么说"回溯与失效重算）
    built_from: Mapped[Optional[list]] = mapped_column(Text, nullable=True, comment="依据的事件 id（JSON 数组文本）")


class TagAlias(Base):
    """标签别名 → 规范名（软归一的落点）。

    标签由模型每次自由生成，同义不同名（水下摄影 / 潜水摄影）会让"按标签聚合"碎掉。
    这张表只做映射，**不合并事件本身**；内容由模型产生、人可修正，
    所以它不是"硬编码的标签字典表"——那件事本项目刻意不做。
    """

    __tablename__ = "tag_aliases"
    __table_args__ = (
        UniqueConstraint("user_id", "alias", name="uq_tag_alias_user_alias"),
        {"comment": "标签别名表——软归一用，不做标签枚举"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(64), nullable=False, comment="别名（模型生成的写法）")
    canonical: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="归并到的规范名")
    created_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local)
