"""采集层（消息推送的输入侧）—— 源配置、任务、运行记录。

边界（与 `services/ingest/` 一起看）：

    selfsec = 控制面 + 数据面
      工作台下发任务、保存源配置、展示执行情况、接收消息并展示
    Hermes  = 执行面
      通过 skill 领取任务、运行确定性采集、用 LLM 生成摘要、回调写消息

三张表只解决「谁在什么时候、用哪一级、抓了哪个源、结果如何」：

    ingest_sources  源配置（RSS / JSON / HTML / GitHub），加源 = 加一行
    ingest_tasks    一次采集任务（手动 / 定时），状态机见 constants
    ingest_runs     一次任务里、一个源的执行记录（失败也要留一条）

消息本身不在这里：仍然落 `events(source=hermes)` + `messages(kind=insight)`，
这样前台窗口、回溯、记忆层都不需要改数据来源。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, DateTimeMicro
from app.utils import now_local

# 任务状态
TASK_QUEUED = "queued"            # 已创建，等 Hermes 领取（pull）或正在推送（push）
TASK_DISPATCHED = "dispatched"    # 已成功 POST 给 Hermes webhook，等 Hermes 开始执行
TASK_RUNNING = "running"          # Hermes 已 claim
TASK_SUCCEEDED = "succeeded"
TASK_PARTIAL = "partial"          # 有源失败，但至少一个源成功
TASK_FAILED = "failed"
TASK_CANCELLED = "cancelled"

# 源 / 运行状态
RUN_RUNNING = "running"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"
RUN_SKIPPED = "skipped"

# 触发方式
TRIGGER_MANUAL = "manual"
TRIGGER_SCHEDULE = "schedule"


class IngestSource(Base):
    __tablename__ = "ingest_sources"
    __table_args__ = {"comment": "采集源配置——加一个源 = 加一行，不需要改代码"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="稳定标识：qbitai / jiqizhixin")
    name: Mapped[str] = mapped_column(String(128), comment="展示名：量子位")
    home_url: Mapped[str] = mapped_column(String(512), comment="站点首页")
    feed_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True, comment="RSS / API / 列表页")
    kind: Mapped[str] = mapped_column(String(32), comment="rss / json_api / html / github")
    level: Mapped[str] = mapped_column(String(8), default="L0", comment="声明的起点 L0/L1/L1.5/L2/L3")
    category: Mapped[str] = mapped_column(String(32), default="tech", comment="tech / finance")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    priority: Mapped[int] = mapped_column(Integer, default=5, comment="越大越靠前")
    max_items: Mapped[int] = mapped_column(Integer, default=12, comment="每次最多取几条")
    interval_minutes: Mapped[int] = mapped_column(Integer, default=1440, comment="预留：源级调度间隔")
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="解析细节：选择器 / 详情模板 / 查询词")
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTimeMicro, nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, onupdate=now_local)


class IngestTask(Base):
    __tablename__ = "ingest_tasks"
    __table_args__ = {"comment": "一次采集任务——手动触发或每日定时"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trigger: Mapped[str] = mapped_column(String(16), default=TRIGGER_MANUAL, comment="manual / schedule")
    status: Mapped[str] = mapped_column(String(16), default=TASK_QUEUED, index=True)
    source_keys: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, comment="本次要跑的源 key 列表；空 = 全部启用源")
    worker: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, comment="领取方：hermes / 本机 CLI")
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(DateTimeMicro, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTimeMicro, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTimeMicro, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stats: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="汇总：源数 / 条数 / 新增 / 更新 / 失败")
    created_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, onupdate=now_local)


class IngestRun(Base):
    __tablename__ = "ingest_runs"
    __table_args__ = {"comment": "任务里的单源执行记录——失败也必须留痕"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingest_tasks.id", ondelete="CASCADE"), index=True
    )
    source_key: Mapped[str] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default=RUN_RUNNING, index=True)
    fetch_level: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, comment="实际走到哪一级 L0-L3")
    items_found: Mapped[int] = mapped_column(Integer, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    items_failed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="耗时 / 首包 / 解析器 / 失败样本")
    started_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTimeMicro, nullable=True)
