"""窗口流 —— 聊天窗口拉取的全部内容。

一个接口，三种用法：

  主视图   filter=all      用户轮 + 秘书轮合并，按时间正序（窗口从旧到新往下滚）
  回溯     filter=record   只看"我说过的话"（events source=user）
          filter=insight   只看"推来的洞察"（messages kind=insight，自带卡片）
          这两者用 order=desc + before 游标翻页（新的在上，"加载更早"往下追加）

不做独立页面：回溯是只读的回忆，弹层就够，不违背"一个窗口"。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import SOURCE_USER, Event
from app.models.message import KIND_INSIGHT, Message
from app.models.user import User
from app.schemas.api import StreamItemOut
from app.services.deps import get_current_user

router = APIRouter(prefix="/api/messages", tags=["messages"])


def _event_item(e: Event) -> StreamItemOut:
    return StreamItemOut(id=e.id, role="me", kind="user", content=e.content, card=None, created_at=e.created_at)


def _message_item(m: Message) -> StreamItemOut:
    return StreamItemOut(id=m.id, role="secretary", kind=m.kind, content=m.content, card=m.card, created_at=m.created_at)


@router.get("", response_model=list[StreamItemOut])
async def list_stream(
    limit: int = Query(60, ge=1, le=200),
    filter: str = Query("all", pattern="^(all|record|insight)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    before: datetime | None = Query(None, description="游标：只取该时间之前的记录，用于回溯翻页"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[StreamItemOut]:
    asc = order == "asc"

    def shape(stmt, col):
        if before is not None:
            stmt = stmt.where(col < before)
        return stmt.order_by(col.asc() if asc else col.desc()).limit(limit)

    if filter == "record":
        stmt = select(Event).where(Event.user_id == user.id, Event.source == SOURCE_USER)
        rows = (await db.execute(shape(stmt, Event.created_at))).scalars().all()
        return [_event_item(e) for e in rows]

    if filter == "insight":
        stmt = select(Message).where(Message.user_id == user.id, Message.kind == KIND_INSIGHT)
        rows = (await db.execute(shape(stmt, Message.created_at))).scalars().all()
        return [_message_item(m) for m in rows]

    # filter == all：两侧各取一批，按时间归并后截断到 limit。
    # 先按最新取、再截断，保证 before 游标不会漏掉更早的记录。
    ev = select(Event).where(Event.user_id == user.id, Event.source == SOURCE_USER)
    ms = select(Message).where(Message.user_id == user.id)
    if before is not None:
        ev = ev.where(Event.created_at < before)
        ms = ms.where(Message.created_at < before)
    ev = ev.order_by(Event.created_at.desc()).limit(limit)
    ms = ms.order_by(Message.created_at.desc()).limit(limit)

    items = [_event_item(e) for e in (await db.execute(ev)).scalars().all()]
    items += [_message_item(m) for m in (await db.execute(ms)).scalars().all()]
    items.sort(key=lambda i: i.created_at, reverse=True)
    items = items[:limit]
    if asc:
        items.reverse()
    return items
