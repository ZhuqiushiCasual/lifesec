"""工作台 API —— 给「后台」那一半人看：源配置、任务下发、执行情况、消息管理。

鉴权走 `X-Workbench-Password`（浏览器里手输一次，存在 sessionStorage），
**不挂 API_TOKEN**：工作台是给人用的页面，和 Hermes 的机器凭证分开。
密码为空时拒绝所有请求（不能默认放行，否则等于没有后台）。
"""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.ingest import IngestSource, IngestTask
from app.models.user import User
from app.schemas.ingest import (
    FinishIn,
    MessageBatchIn,
    MessageBatchOut,
    MessageMergeIn,
    MessageOut,
    MessagePatch,
    SourceCreate,
    SourceOut,
    SourceUpdate,
    TaskCreate,
    TaskOut,
)
from app.services.deps import get_current_user
from app.services.ingest import dispatch
from app.services.ingest import messages as message_service
from app.services.ingest import tasks as task_service
from app.services.ingest.sources import DEFAULT_SOURCES

router = APIRouter(prefix="/api/workbench", tags=["workbench"])

VALID_KINDS = {"rss", "json_api", "html", "github"}


def verify_workbench(x_workbench_password: str = Header("", alias="X-Workbench-Password")) -> None:
    expected = settings.workbench_password
    if not expected:
        raise HTTPException(status_code=503, detail="未配置 WORKBENCH_PASSWORD，工作台不可用")
    if not x_workbench_password or not secrets.compare_digest(
        x_workbench_password.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="工作台密码不正确")


@router.get("/check")
async def check(_: None = Depends(verify_workbench)):
    return {"ok": True}


def _source_out(src: IngestSource) -> SourceOut:
    return SourceOut.model_validate(src)


def _dispatch_info() -> dict:
    return {
        "configured": bool(settings.hermes_webhook_url and settings.hermes_webhook_secret),
        "url": settings.hermes_webhook_url or "",
        "api_base": settings.selfsec_public_url.rstrip("/"),
    }


@router.get("/overview")
async def overview(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
):
    data = await task_service.overview(db)
    data["config"] = {
        "schedule": {
            "enabled": settings.ingest_enabled,
            "hour": settings.ingest_hour,
            "minute": settings.ingest_minute,
            "lookback_hours": settings.ingest_lookback_hours,
            "max_items": settings.ingest_max_items,
        },
        "dispatch": _dispatch_info(),
    }
    return data


# ── 源 ───────────────────────────────────────────────────
@router.get("/sources", response_model=list[SourceOut])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
) -> list[SourceOut]:
    rows = (
        await db.execute(
            select(IngestSource).order_by(IngestSource.priority.desc(), IngestSource.key)
        )
    ).scalars().all()
    return [_source_out(s) for s in rows]


@router.post("/sources", response_model=SourceOut, status_code=201)
async def create_source(
    payload: SourceCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
) -> SourceOut:
    if payload.kind not in VALID_KINDS:
        raise HTTPException(status_code=422, detail=f"kind 只能是 {sorted(VALID_KINDS)}")
    exists = (
        await db.execute(select(IngestSource).where(IngestSource.key == payload.key))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail="这个 key 已经存在")
    src = IngestSource(**payload.model_dump())
    db.add(src)
    await db.commit()
    await db.refresh(src)
    return _source_out(src)


@router.patch("/sources/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: str,
    payload: SourceUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
) -> SourceOut:
    src = await db.get(IngestSource, source_id)
    if src is None:
        raise HTTPException(status_code=404, detail="没有这个源")
    data = payload.model_dump(exclude_unset=True)
    if data.get("kind") and data["kind"] not in VALID_KINDS:
        raise HTTPException(status_code=422, detail=f"kind 只能是 {sorted(VALID_KINDS)}")
    for key, value in data.items():
        setattr(src, key, value)
    await db.commit()
    await db.refresh(src)
    return _source_out(src)


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
):
    src = await db.get(IngestSource, source_id)
    if src is None:
        raise HTTPException(status_code=404, detail="没有这个源")
    await db.delete(src)
    await db.commit()
    return {"ok": True}


@router.post("/sources/{source_id}/run", response_model=TaskOut)
async def run_source(
    source_id: str,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
) -> TaskOut:
    src = await db.get(IngestSource, source_id)
    if src is None:
        raise HTTPException(status_code=404, detail="没有这个源")
    task = await task_service.create_task(db, source_keys=[src.key])
    if _dispatch_info()["configured"]:
        background.add_task(dispatch.dispatch_task_background, task.id)
    return task_service.task_out(task)


@router.post("/sources/seed")
async def reseed_sources(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
):
    """补回内置五个源里被删掉的（不覆盖已有配置）。"""
    existing = set((await db.execute(select(IngestSource.key))).scalars().all())
    added = []
    for item in DEFAULT_SOURCES:
        if item["key"] in existing:
            continue
        db.add(IngestSource(**item))
        added.append(item["key"])
    if added:
        await db.commit()
    return {"added": added}


# ── 任务 ─────────────────────────────────────────────────
@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    limit: int = Query(30, ge=1, le=200),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
) -> list[TaskOut]:
    return await task_service.list_tasks(db, limit=limit, status=status)


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(
    payload: TaskCreate,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
) -> TaskOut:
    keys = list(payload.source_keys or [])
    if keys:
        known = set((await db.execute(select(IngestSource.key))).scalars().all())
        unknown = [k for k in keys if k not in known]
        if unknown:
            raise HTTPException(status_code=422, detail=f"未知的源：{unknown}")
    task = await task_service.create_task(db, trigger=payload.trigger, source_keys=keys)
    if _dispatch_info()["configured"]:
        background.add_task(dispatch.dispatch_task_background, task.id)
    return task_service.task_out(task)


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
):
    try:
        task = await task_service.get_task(db, task_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "task": task_service.task_out(task).model_dump(mode="json"),
        "runs": [r.model_dump(mode="json") for r in await task_service.list_runs(db, task_id)],
    }


@router.post("/tasks/{task_id}/retry", response_model=TaskOut, status_code=201)
async def retry_task(
    task_id: str,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
) -> TaskOut:
    try:
        task = await task_service.retry_task(db, task_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if _dispatch_info()["configured"]:
        background.add_task(dispatch.dispatch_task_background, task.id)
    return task_service.task_out(task)


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
) -> TaskOut:
    try:
        return await task_service.cancel_task(db, task_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/tasks/{task_id}/dispatch")
async def dispatch_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
):
    task = await db.get(IngestTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="没有这个任务")
    return await dispatch.dispatch_task(task)


# ── 消息 ─────────────────────────────────────────────────
@router.get("/messages", response_model=list[MessageOut])
async def list_messages(
    limit: int = Query(100, ge=1, le=500),
    source_key: Optional[str] = Query(None),
    include_hidden: bool = Query(True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
) -> list[MessageOut]:
    return await message_service.list_events(
        db, user.id, limit=limit, source_key=source_key, include_hidden=include_hidden
    )


@router.post("/messages", response_model=MessageBatchOut)
async def upsert_messages(
    payload: MessageBatchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
) -> MessageBatchOut:
    """工作台「手工补一条」用的，和 Hermes 的批量写入是同一套逻辑。"""
    return await message_service.upsert_items(
        db, user.id, list(payload.items), task_id=payload.task_id
    )


@router.patch("/messages/{event_id}", response_model=MessageOut)
async def patch_message(
    event_id: str,
    payload: MessagePatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
) -> MessageOut:
    try:
        return await message_service.update_event(db, user.id, event_id, payload)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/messages/{event_id}")
async def delete_message(
    event_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
):
    try:
        await message_service.delete_event(db, user.id, event_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@router.post("/messages/merge", response_model=MessageOut)
async def merge_messages(
    payload: MessageMergeIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_workbench),
) -> MessageOut:
    try:
        return await message_service.merge_events(db, user.id, payload)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
