"""date_photos —— 「约会挑餐厅」每家店的实拍图。

为什么单独一张表而不是塞进 `date_menu.photo` 一个字符串：

- 一张卡要能翻图集（前台浮层），一条记录只放得下一个地址；
- 图是外部素材（小红书笔记），要保留来源标题与链接，方便回查是哪篇笔记里的；
- 宽高一起存下来，前台卡片才能先按真实比例占位（瀑布流靠宽高不同错版，
  也让图片加载前后不跳）。

图片文件本身不进仓库：`backend/static/date_photos/<店>/NN.jpg`（gitignore），
线上靠 scp 传上去 —— 跟 `backend/media/` 一个待遇，数据库里只存访问路径。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, DateTimeMicro
from app.utils import now_local


class DatePhoto(Base):
    __tablename__ = "date_photos"
    __table_args__ = {"comment": "约会挑餐厅——每家店的实拍图（一行一张）"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 不建真外键：菜单项删了，图跟着清（API 里显式删），但不希望被数据库约束卡住迁移
    restaurant_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True, comment="date_menu.id"
    )

    path: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="站内路径，如 /date_photos/meixi/01.jpg"
    )
    w: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="原图宽（px）")
    h: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="原图高（px）")
    caption: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="来源笔记标题 / 一句说明（前台图右下角小字）"
    )
    source_url: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="来源笔记链接（供回查）"
    )

    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True, comment="图集顺序")
    created_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local)
