"""Hermes 执行面的回调 API。

这一组接口都挂在 `API_TOKEN` 鉴权下，给 Hermes skill 用（不进浏览器）：

    任务    GET  /api/ingest/tasks/next           pull：领最早一个 queued
            POST /api/ingest/tasks/{id}/claim     push：领指定任务（幂等）
            GET  /api/ingest/tasks/{id}           任务 + 各源运行记录
            POST /api/ingest/tasks/{id}/runs      上报单源执行结果
            GET  /api/ingest/tasks/{id}/runs      查询
            POST /api/ingest/tasks/{id}/finish    收尾

    源      GET  /api/ingest/sources              源配置（runner 也可直接读库）

    消息    POST   /api/ingest/messages           批量新增 / 更新（按 canonical URL 幂等）
            GET    /api/ingest/messages           列表
            GET    /api/ingest/messages/{id}      单条
            PATCH  /api/ingest/messages/{id}      修改
            DELETE /api/ingest/messages/{id}      删除
            POST   /api/ingest/messages/merge     合并重复

写消息只动 `events(source=hermes)` + 对应的那条 insight message，
不会碰用户自己记的事件。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.ingest import (
    ClaimOut,
    FinishIn,
    MessageBatchIn,
    MessageBatchOut,
    MessageMergeIn,
    MessageOut,
    MessagePatch,
    RunIn,
    RunOut,
    SourceOut,
    TaskOut,
)
from app.services.deps import get_current_user
from app.services.ingest import messages as message_service
from app.services.ingest import tasks as task_service

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


def _claim_body(task, sources) -> ClaimOut:
    return ClaimOut(
        task=task_service.task_out(task),
        sources=[SourceOut.model_validate(s) for s in sources],
        api_base=settings.selfsec_public_url.rstrip("/"),
    )


async def _claimed(db: AsyncSession, task) -> ClaimOut:
    return _claim_body(task, await task_service.sources_for_task(db, task))


# ── 任务 ─────────────────────────────────────────────────
@router.get("/tasks/next")
async def next_task(
    worker: str = Query("hermes", max_length=64),
    db: AsyncSession = Depends(get_db),
):
    """pull 模式：没有任务时返回 `{"task": null}`，让 Hermes 安静地空跑一次。"""
    task = await task_service.claim_next(db, worker=worker)
    if task is None:
        return {"task": None, "sources": [], "api_base": settings.selfsec_public_url.rstrip("/")}
    return (await _claimed(db, task)).model_dump(mode="json")


@router.post("/tasks/{task_id}/claim", response_model=ClaimOut)
async def claim_task(
    task_id: str,
    worker: str = Query("hermes", max_length=64),
    db: AsyncSession = Depends(get_db),
) -> ClaimOut:
    try:
        task = await task_service.claim_task(db, task_id, worker=worker)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return await _claimed(db, task)


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    try:
        task = await task_service.get_task(db, task_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    runs = await task_service.list_runs(db, task_id)
    return {
        "task": task_service.task_out(task).model_dump(mode="json"),
        "runs": [r.model_dump(mode="json") for r in runs],
    }


@router.post("/tasks/{task_id}/runs", response_model=RunOut)
async def report_run(
    task_id: str,
    payload: RunIn,
    db: AsyncSession = Depends(get_db),
) -> RunOut:
    try:
        return await task_service.report_run(db, task_id, payload)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/tasks/{task_id}/runs", response_model=list[RunOut])
async def list_runs(task_id: str, db: AsyncSession = Depends(get_db)) -> list[RunOut]:
    try:
        await task_service.get_task(db, task_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return await task_service.list_runs(db, task_id)


@router.post("/tasks/{task_id}/finish", response_model=TaskOut)
async def finish_task(
    task_id: str,
    payload: FinishIn,
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    try:
        return await task_service.finish_task(db, task_id, payload)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── 源 ───────────────────────────────────────────────────
@router.get("/sources", response_model=list[SourceOut])
async def list_sources(
    enabled_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> list[SourceOut]:
    from sqlalchemy import select

    from app.models.ingest import IngestSource

    stmt = select(IngestSource).order_by(IngestSource.priority.desc(), IngestSource.key)
    if enabled_only:
        stmt = stmt.where(IngestSource.enabled.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return [SourceOut.model_validate(s) for s in rows]


# ── 消息 ─────────────────────────────────────────────────
@router.post("/messages", response_model=MessageBatchOut)
async def upsert_messages(
    payload: MessageBatchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageBatchOut:
    return await message_service.upsert_items(
        db, user.id, list(payload.items), task_id=payload.task_id
    )


@router.get("/messages", response_model=list[MessageOut])
async def list_messages(
    limit: int = Query(100, ge=1, le=500),
    source_key: Optional[str] = Query(None),
    include_hidden: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    return await message_service.list_events(
        db, user.id, limit=limit, source_key=source_key, include_hidden=include_hidden
    )


@router.get("/messages/{event_id}", response_model=MessageOut)
async def get_message(
    event_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    try:
        return await message_service.get_event_out(db, user.id, event_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/messages/{event_id}", response_model=MessageOut)
async def patch_message(
    event_id: str,
    payload: MessagePatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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
) -> MessageOut:
    try:
        return await message_service.merge_events(db, user.id, payload)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
