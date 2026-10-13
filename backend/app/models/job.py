"""job_runs —— 迭代任务的幂等锁。

为什么需要它：记忆迭代有三个时钟（轮次 / 定时 / 每日兜底），它们会**打架** ——
同一条用户消息触发"每 10 轮"的档迭代、同时 00:00 的兜底任务也在跑，
没有锁就是同一次迭代算两遍（白花钱，而且两次生成的结果会互相覆盖）。

做法：一张表 + (job, period_key) 唯一键。跑之前先想插一行，插得进就跑，
插不进说明这个周期的这次迭代已经跑过（或正在跑），直接跳过。

    job          tag_iter / portrait_iter / daily
    period_key   tag:40 / portrait:60 / daily:2026-10-11

刻意不引 APScheduler，也不引分布式锁：单用户单实例，一张表就够。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, DateTimeMicro
from app.utils import now_local

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        UniqueConstraint("job", "period_key", name="uq_job_run_period"),
        {"comment": "迭代任务的幂等锁——同一 (job, period) 只跑一次"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="任务名")
    period_key: Mapped[str] = mapped_column(String(64), nullable=False, comment="周期键：同一周期只跑一次")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_RUNNING)
    detail: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="结果备注（变更摘要等）")
    started_at: Mapped[datetime] = mapped_column(DateTimeMicro, default=now_local, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTimeMicro, nullable=True)
