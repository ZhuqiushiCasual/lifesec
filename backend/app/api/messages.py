"""窗口流 —— 聊天窗口拉取的全部内容。

窗口里既要看见自己说过的话，也要看见它回的话，所以这里把两侧合并：
  events(source=user)  → role=me         （我说的话）
  messages             → role=secretary  （它说的话，可能带卡片）

没有物化视图，就是两次查询 + 一次按时间归并——
单用户数据量小，够用且不用维护额外状态。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import SOURCE_USER, Event
from app.models.message import Message
from app.models.user import User
from app.schemas.api import StreamItemOut
from app.services.deps import get_current_user

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("", response_model=list[StreamItemOut])
async def list_stream(
    limit: int = Query(60, ge=1, le=300),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[StreamItemOut]:
    events = (
        await db.execute(
            select(Event)
            .where(Event.user_id == user.id, Event.source == SOURCE_USER)
            .order_by(Event.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    messages = (
        await db.execute(
            select(Message).where(Message.user_id == user.id).order_by(Message.created_at.desc()).limit(limit)
        )
    ).scalars().all()

    items = [
        StreamItemOut(id=e.id, role="me", kind="user", content=e.content, card=None, created_at=e.created_at)
        for e in events
    ]
    items += [
        StreamItemOut(id=m.id, role="secretary", kind=m.kind, content=m.content, card=m.card, created_at=m.created_at)
        for m in messages
    ]
    items.sort(key=lambda i: i.created_at)
    return items
