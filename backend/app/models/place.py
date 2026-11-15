"""places —— 地点（餐厅 / 公园 / 街区 / 商场 都是一个东西）。

这张表只装「做拓扑需要的公共维度」：在哪、是什么类别、属于哪个更大的地方、
以及一个可扩展的 attrs（菜系 / 人均 / 标签 / 门票 / 营业时间…）。

业务字段继续留在各自的领域表里：

    date_menu      place_id → places.id   口味三轴、人均、点菜避坑、排序
    outing_spots   place_id → places.id   候选顺序、一句提示

为什么不合并成一张表：餐厅和玩点的差异字段比共有的多，合并的结果是一半列常年为空。
拓扑只认这张表，领域表负责前端卡片和计划落地（plans.ref_type 仍是 date_menu / outing_spot）。

**边上不建表**：距离、同商场、同区域都在查询时算（services/place.py）。
为可计算的东西建存储，就要同步、要重算、还要处理「人工边不被覆盖」，而这里只有几十个点。
元数据长一格（比如加了 indoor），拓扑就自动多一层关系——不需要迁移，也不需要重算任务。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, DateTimeMicro
from app.utils import now_local


class Place(Base):
    __tablename__ = "places"
    __table_args__ = {"comment": "地点（拓扑的唯一入口）：坐标 + 分类 + 可扩展属性"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 幂等键：规范化(名|分店)。回填、采集、人工录入都靠它 upsert，不会长重复行
    canonical_key: Mapped[str] = mapped_column(
        String(160), nullable=False, unique=True, index=True, comment="规范化(名称|分店)，upsert 用"
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    branch: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    category: Mapped[str] = mapped_column(
        String(16), nullable=False, default="play",
        comment="eat / play / park / street / exhibit / shop",
    )
    sub_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="", comment="景点 / 展馆 / 江浙菜…")

    area: Mapped[str] = mapped_column(String(40), nullable=False, default="", comment="行政区；取不到就留空")
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # 可空：查不到就留空，宁可不写距离，也不假装精确
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    metro_station: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    metro_walk_m: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 商场里的店 → 指向商场节点。同一个 parent 的两点按 2 分钟算（不按坐标算，否则都是 0 米）
    parent_place_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True, comment="所属更大范围：商场 / 景区"
    )

    # 可扩展元数据：tags / indoor / open_till / duration_min / cuisine / price / score / note …
    attrs: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", comment="active / hidden / merged"
    )
    # 来源：domain(从领域表回填) / nominate(地理编码补的) / manual / note
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="domain")
    source_ref: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True, comment="领域表 id（date_menu / outing_spots），用于回查与安排"
    )

    created_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, onupdate=now_local)

    # ── 便利属性 ──────────────────────────────────────────
    @property
    def has_geo(self) -> bool:
        return self.lng is not None and self.lat is not None

    @property
    def kind(self) -> str:
        """给前端 / 计划用：eat → food，其余 → outing。"""
        return "food" if self.category == "eat" else "outing"
