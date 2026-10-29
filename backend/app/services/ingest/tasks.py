"""采集任务的创建 / 领取 / 上报 / 收尾。

任务是一个很轻的状态机，只有两个入口：

    工作台（或每日调度） create_task → queued
    Hermes skill          claim_next  → running
    Hermes skill          report_run  × N（每个源一条）
    Hermes skill          finish      → succeeded / partial / failed

`queued` 同时服务两种下发方式：
    push  工作台选中任务 → HMAC webhook 喊 Hermes 来领
    pull  Hermes 定时 cron 自己来 `claim_next`（能穿 NAT，是兜底）
所以「建了任务但 Hermes 没收到」不会丢，最多等到下一个 cron 周期。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SOURCE_HERMES, Event
from app.models.ingest import (
    RUN_FAILED,
    RUN_RUNNING,
    RUN_SUCCEEDED,
    TASK_CANCELLED,
    TASK_DISPATCHED,
    TASK_FAILED,
    TASK_PARTIAL,
    TASK_QUEUED,
    TASK_RUNNING,
    TASK_SUCCEEDED,
    TRIGGER_MANUAL,
    IngestRun,
    IngestSource,
    IngestTask,
)
from app.schemas.ingest import FinishIn, RunIn, RunOut, TaskOut
from app.utils import now_local

FINAL_TASK_STATUS = {TASK_SUCCEEDED, TASK_PARTIAL, TASK_FAILED, TASK_CANCELLED}


def task_out(task: IngestTask) -> TaskOut:
    return TaskOut(
        id=task.id,
        trigger=task.trigger,
        status=task.status,
        source_keys=list(task.source_keys or []),
        worker=task.worker,
        dispatched_at=task.dispatched_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        error=task.error,
        stats=dict(task.stats or {}),
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def run_out(run: IngestRun) -> RunOut:
    return RunOut(
        id=run.id,
        task_id=run.task_id,
        source_key=run.source_key,
        source_name=run.source_name,
        status=run.status,
        fetch_level=run.fetch_level,
        items_found=run.items_found,
        items_new=run.items_new,
        items_updated=run.items_updated,
        items_failed=run.items_failed,
        error=run.error,
        detail=dict(run.detail or {}),
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


async def create_task(
    db: AsyncSession,
    *,
    trigger: str = TRIGGER_MANUAL,
    source_keys: Optional[list[str]] = None,
) -> IngestTask:
    keys = list(dict.fromkeys(k for k in (source_keys or []) if k))
    task = IngestTask(trigger=trigger, status=TASK_QUEUED, source_keys=keys or None)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def get_task(db: AsyncSession, task_id: str) -> IngestTask:
    task = await db.get(IngestTask, task_id)
    if task is None:
        raise LookupError("没有这个任务")
    return task


async def sources_for_task(db: AsyncSession, task: IngestTask) -> list[IngestSource]:
    stmt = select(IngestSource).where(IngestSource.enabled.is_(True))
    keys = list(task.source_keys or [])
    if keys:
        stmt = stmt.where(IngestSource.key.in_(keys))
    rows = (await db.execute(stmt.order_by(IngestSource.priority.desc(), IngestSource.key))).scalars().all()
    return list(rows)


async def claim_next(db: AsyncSession, *, worker: str = "hermes") -> Optional[IngestTask]:
    """领取最早的一个 queued 任务。用条件 UPDATE 抢占，避免两个 worker 拿同一个。"""
    for _ in range(3):
        task = (
            await db.execute(
                select(IngestTask)
                .where(IngestTask.status == TASK_QUEUED)
                .order_by(IngestTask.created_at.asc(), IngestTask.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if task is None:
            return None

        now = now_local()
        result = await db.execute(
            update(IngestTask)
            .where(IngestTask.id == task.id, IngestTask.status == TASK_QUEUED)
            .values(
                status=TASK_RUNNING,
                worker=worker,
                started_at=now,
                dispatched_at=task.dispatched_at or now,
            )
        )
        await db.commit()
        if result.rowcount == 1:
            await db.refresh(task)
            return task
    return None


async def claim_task(db: AsyncSession, task_id: str, *, worker: str = "hermes") -> IngestTask:
    """领取指定任务（push 链路）。重复 claim 是幂等的，方便 Hermes 重试。"""
    task = await get_task(db, task_id)
    if task.status in FINAL_TASK_STATUS:
        raise ValueError(f"任务已结束（{task.status}）")
    if task.status == TASK_RUNNING:
        return task

    now = now_local()
    result = await db.execute(
        update(IngestTask)
        .where(
            IngestTask.id == task_id,
            IngestTask.status.in_((TASK_QUEUED, TASK_DISPATCHED)),
        )
        .values(
            status=TASK_RUNNING,
            worker=worker,
            started_at=now,
            dispatched_at=task.dispatched_at or now,
        )
    )
    await db.commit()
    if result.rowcount != 1:
        await db.refresh(task)
        if task.status == TASK_RUNNING:
            return task
        raise ValueError(f"任务状态已变化（{task.status}），无法领取")
    await db.refresh(task)
    return task


async def mark_dispatched(db: AsyncSession, task: IngestTask) -> None:
    if task.status != TASK_QUEUED:
        return
    task.status = TASK_DISPATCHED
    task.dispatched_at = now_local()
    await db.commit()


async def mark_queue_again(db: AsyncSession, task: IngestTask, error: str) -> None:
    """push 失败不回滚任务：退回 queued，等 Hermes 的 pull 兜底。"""
    task.status = TASK_QUEUED
    task.error = f"推送 Hermes 失败，等待 pull 兜底：{error}"[:500]
    await db.commit()


async def report_run(db: AsyncSession, task_id: str, payload: RunIn) -> RunOut:
    task = await get_task(db, task_id)
    if task.status in FINAL_TASK_STATUS:
        raise ValueError(f"任务已结束（{task.status}），不再接收执行记录")

    run = (
        await db.execute(
            select(IngestRun)
            .where(IngestRun.task_id == task_id, IngestRun.source_key == payload.source_key)
            .order_by(IngestRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    now = now_local()
    if run is None:
        run = IngestRun(
            task_id=task_id,
            source_key=payload.source_key,
            source_name=payload.source_name or payload.source_key,
            started_at=now,
        )
        db.add(run)

    run.source_name = payload.source_name or run.source_name or payload.source_key
    run.status = payload.status
    run.fetch_level = payload.fetch_level
    run.items_found = max(0, int(payload.items_found or 0))
    run.items_new = max(0, int(payload.items_new or 0))
    run.items_updated = max(0, int(payload.items_updated or 0))
    run.items_failed = max(0, int(payload.items_failed or 0))
    run.error = (payload.error or None) and str(payload.error)[:2000]
    run.detail = payload.detail or {}
    if payload.status != RUN_RUNNING:
        run.finished_at = now

    src = (
        await db.execute(select(IngestSource).where(IngestSource.key == payload.source_key))
    ).scalar_one_or_none()
    if src is not None and payload.status != RUN_RUNNING:
        src.last_run_at = now
        src.last_status = payload.status
        src.last_error = (payload.error or None) and str(payload.error)[:1000]

    if task.status in (TASK_QUEUED, TASK_DISPATCHED):
        task.status = TASK_RUNNING
        task.started_at = task.started_at or now

    await db.commit()
    await db.refresh(run)
    return run_out(run)


async def list_runs(db: AsyncSession, task_id: str) -> list[RunOut]:
    rows = (
        await db.execute(
            select(IngestRun)
            .where(IngestRun.task_id == task_id)
            .order_by(IngestRun.started_at.asc(), IngestRun.id.asc())
        )
    ).scalars().all()
    return [run_out(r) for r in rows]


def _aggregate(runs: list[IngestRun]) -> dict[str, Any]:
    return {
        "sources": len(runs),
        "found": sum(r.items_found for r in runs),
        "new": sum(r.items_new for r in runs),
        "updated": sum(r.items_updated for r in runs),
        "failed_items": sum(r.items_failed for r in runs),
        "succeeded": sum(1 for r in runs if r.status == RUN_SUCCEEDED),
        "failed": sum(1 for r in runs if r.status == RUN_FAILED),
        "skipped": sum(1 for r in runs if r.status not in (RUN_SUCCEEDED, RUN_FAILED)),
    }


async def finish_task(db: AsyncSession, task_id: str, payload: FinishIn) -> TaskOut:
    task = await get_task(db, task_id)
    if task.status == TASK_CANCELLED:
        return task_out(task)

    runs = (
        await db.execute(select(IngestRun).where(IngestRun.task_id == task_id))
    ).scalars().all()
    stats = {**_aggregate(runs), **dict(payload.stats or {})}

    status = payload.status if payload.status in (TASK_SUCCEEDED, TASK_PARTIAL, TASK_FAILED) else TASK_SUCCEEDED
    if runs and status == TASK_SUCCEEDED:
        if stats["succeeded"] == 0 and stats["failed"] > 0:
            status = TASK_FAILED
        elif stats["failed"] > 0:
            status = TASK_PARTIAL

    task.status = status
    task.stats = stats
    task.error = (payload.error or None) and str(payload.error)[:2000]
    task.finished_at = now_local()
    await db.commit()
    await db.refresh(task)
    return task_out(task)


async def list_tasks(db: AsyncSession, *, limit: int = 30, status: Optional[str] = None) -> list[TaskOut]:
    stmt = select(IngestTask).order_by(IngestTask.created_at.desc(), IngestTask.id.desc()).limit(limit)
    if status:
        stmt = stmt.where(IngestTask.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return [task_out(t) for t in rows]


async def retry_task(db: AsyncSession, task_id: str) -> IngestTask:
    old = await get_task(db, task_id)
    return await create_task(db, trigger=TRIGGER_MANUAL, source_keys=list(old.source_keys or []))


async def cancel_task(db: AsyncSession, task_id: str) -> TaskOut:
    task = await get_task(db, task_id)
    if task.status in FINAL_TASK_STATUS:
        return task_out(task)
    task.status = TASK_CANCELLED
    task.finished_at = now_local()
    task.error = task.error or "工作台手动取消"
    await db.commit()
    await db.refresh(task)
    return task_out(task)


async def overview(db: AsyncSession) -> dict[str, Any]:
    """工作台首屏：任务 / 源健康 / 消息量。全部来自本地表，不调模型。"""
    task_rows = (
        await db.execute(select(IngestTask.status, func.count()).group_by(IngestTask.status))
    ).all()
    task_counts = {status: int(n) for status, n in task_rows}

    source_rows = (await db.execute(select(IngestSource))).scalars().all()
    sources = {
        "total": len(source_rows),
        "enabled": sum(1 for s in source_rows if s.enabled),
        "error": sum(1 for s in source_rows if s.last_status == RUN_FAILED),
    }

    total = int(
        (await db.execute(select(func.count()).select_from(Event).where(Event.source == SOURCE_HERMES))).scalar()
        or 0
    )
    since = now_local() - timedelta(hours=24)
    last_24h = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Event)
                .where(Event.source == SOURCE_HERMES, Event.recorded_at >= since)
            )
        ).scalar()
        or 0
    )
    recent_events = (
        await db.execute(
            select(Event)
            .where(Event.source == SOURCE_HERMES)
            .order_by(Event.recorded_at.desc(), Event.id.desc())
            .limit(500)
        )
    ).scalars().all()
    by_status: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for event in recent_events:
        ent = event.entities or {}
        status = ent.get("status") or "new"
        by_status[status] = by_status.get(status, 0) + 1
        key = ent.get("source_key") or "unknown"
        by_source[key] = by_source.get(key, 0) + 1

    return {
        "tasks": task_counts,
        "sources": sources,
        "messages": {
            "total": total,
            "last_24h": last_24h,
            "new": by_status.get("new", 0),
            "read": by_status.get("read", 0),
            "hidden": by_status.get("hidden", 0),
            "by_source": by_source,
        },
        "recent_tasks": [task_out(t) for t in (
            await db.execute(
                select(IngestTask).order_by(IngestTask.created_at.desc()).limit(8)
            )
        ).scalars().all()],
        "recent_runs": [
            run_out(r)
            for r in (
                await db.execute(
                    select(IngestRun).order_by(IngestRun.started_at.desc()).limit(20)
                )
            ).scalars().all()
        ],
    }
