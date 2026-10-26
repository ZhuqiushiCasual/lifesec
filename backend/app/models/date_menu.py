"""date_menu —— 「约会挑餐厅」菜单。

一张独立的小表，和记忆层无关：它只是给前端那张挑餐厅的页面提供内容 + 排序。
为什么单独建表而不是塞进配置或 JSON 文件：

- 后台要能增删改、上移下移（`api/date.py` 的管理端点），配置改不了运行时；
- 数量少、结构扁，不值得拆成"餐厅 + 评价"两张表；
- 口味三轴（清淡 / 辣 / 油）分开存 0–5，前端画进度条时不用解析字符串。

`sort` 是唯一的展示顺序来源：管理端上移/下移只是重排这个整数，
GET 一律 `ORDER BY sort, id`，保证顺序稳定（sort 相同时按 id，不抖）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, DateTimeMicro
from app.utils import now_local


class DateMenuItem(Base):
    __tablename__ = "date_menu"
    __table_args__ = {"comment": "约会挑餐厅——菜单项（后台可增删改排序）"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # ── 内容 ──────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(120), nullable=False, comment="店名")
    branch: Mapped[str] = mapped_column(String(80), nullable=False, default="", comment="分店名")
    cuisine: Mapped[str] = mapped_column(String(80), nullable=False, default="", comment="菜系")
    price: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="人均（门市价口径）")
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0, comment="点评评分，0 = 未取到")

    # 口味三轴：0–5，前端直接映射成进度条宽度
    taste_light: Mapped[int] = mapped_column(Integer, nullable=False, default=3, comment="清淡度 0–5")
    taste_spicy: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="辣度 0–5")
    taste_oil: Mapped[int] = mapped_column(Integer, nullable=False, default=2, comment="油度 0–5")
    taste_label: Mapped[str] = mapped_column(String(24), nullable=False, default="清淡", comment="角标文案")
    taste_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="light", comment="角标配色：light/spicy/oil")

    reason: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="上榜理由")
    metro: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="最近地铁站 + 出口 + 步行")
    reach: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="从三花国际怎么过去")
    tip: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="点菜 / 避坑")

    dist_km: Mapped[float] = mapped_column(Float, nullable=False, default=0, comment="离三花国际直线距离（km）")

    # ── 视觉 ──────────────────────────────────────────────
    art: Mapped[str] = mapped_column(
        String(24), nullable=False, default="porridge",
        comment="占位插画：porridge/beefpot/sushi/thai/grill/western/chinese",
    )
    accent_a: Mapped[str] = mapped_column(String(16), nullable=False, default="#FDF1E7", comment="插画渐变起色")
    accent_b: Mapped[str] = mapped_column(String(16), nullable=False, default="#F8E2D2", comment="插画渐变止色")
    photo: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="实拍图地址；留空则用插画")

    # ── 展示控制 ──────────────────────────────────────────
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True, comment="展示顺序，越小越靠前")
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="隐藏（前台不出现，后台仍可见）")

    created_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, onupdate=now_local)
