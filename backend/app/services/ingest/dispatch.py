"""把「有个任务要跑」告诉 Hermes。

两种下发方式，共用同一份 queued 任务：

    push  这里直接 POST Hermes webhook（HMAC V2 签名），Hermes 收到后 claim
    pull  Hermes 的 cron 周期性 `GET /api/ingest/tasks/next`（穿 NAT 的兜底）

push 失败不是错误：任务留在 queued，pull 会把它捡走。所以工作台只需要
展示「已推送 / 等待领取」，不需要重试按钮也能自愈。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models.ingest import IngestTask
from app.services.ingest import tasks as task_service

log = logging.getLogger("selfsec.ingest.dispatch")


def _signature(secret: str, timestamp: str, body: str) -> str:
    """Hermes webhook 的 V2 签名：hex(HMAC-SHA256(secret, `<timestamp>.<body>`))。"""
    message = f"{timestamp}.{body}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def build_payload(task: IngestTask) -> dict[str, Any]:
    return {
        "event": "selfsec.ingest.task",
        "task_id": task.id,
        "task": task_service.task_out(task).model_dump(mode="json"),
        "api_base": settings.selfsec_public_url.rstrip("/"),
        "hint": "调用 /api/ingest/tasks/{task_id}/claim 领取，再按 skill 的流程执行",
    }


async def post_to_hermes(payload: dict[str, Any]) -> tuple[bool, str]:
    url = settings.hermes_webhook_url
    secret = settings.hermes_webhook_secret
    if not url:
        return False, "未配置 HERMES_WEBHOOK_URL"
    if not secret:
        return False, "未配置 HERMES_WEBHOOK_SECRET"

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Signature-V2": _signature(secret, timestamp, body),
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(url, content=body.encode("utf-8"), headers=headers)
        if 200 <= resp.status_code < 300:
            return True, f"HTTP {resp.status_code}"
        return False, f"HTTP {resp.status_code}: {resp.text[:300]}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]


async def dispatch_task(task: IngestTask) -> dict[str, Any]:
    payload = build_payload(task)
    ok, detail = await post_to_hermes(payload)
    async with async_session() as db:
        fresh = await db.get(IngestTask, task.id)
        if fresh is not None:
            if ok:
                await task_service.mark_dispatched(db, fresh)
            else:
                await task_service.mark_queue_again(db, fresh, detail)
    log.info("任务 %s 下发：%s（%s）", task.id, "成功" if ok else "失败", detail)
    return {"dispatched": ok, "detail": detail, "task_id": task.id}


async def dispatch_task_background(task_id: str) -> None:
    """给 FastAPI BackgroundTasks / 调度器用：自己开 session，吞掉异常。"""
    try:
        async with async_session() as db:
            task = await db.get(IngestTask, task_id)
        if task is None:
            return
        await dispatch_task(task)
    except Exception as e:  # noqa: BLE001
        log.warning("任务 %s 下发异常：%s", task_id, e)


async def dispatch_queued(limit: int = 5) -> int:
    """兜底批处理：把积压的 queued 任务再推一遍（pull 之外的主动性）。"""
    async with async_session() as db:
        rows = (
            await db.execute(
                select(IngestTask)
                .where(IngestTask.status == "queued")
                .order_by(IngestTask.created_at.asc())
                .limit(limit)
            )
        ).scalars().all()
    for task in rows:
        await dispatch_task(task)
    return len(rows)


def schedule_background(task_id: str) -> None:
    """调度器里没有请求上下文，直接起一个短命任务。"""
    asyncio.create_task(dispatch_task_background(task_id))
