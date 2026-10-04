"""洞察接口 —— Hermes 的回调入口。

边界（architecture 5.3）：selfsec **不自建抓取管线**，只接收结果。
落库后立刻生成一条 message，于是洞察会像别的东西一样出现在同一个窗口里。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import SOURCE_HERMES, TYPE_INSIGHT, Event
from app.models.message import KIND_INSIGHT, Message
from app.models.user import User
from app.schemas.api import InsightIn, InsightOut
from app.services.deps import get_current_user

router = APIRouter(prefix="/api/insights", tags=["insights"])


def _dedup_key(item: InsightIn) -> str:
    return (item.source_url or item.title or "").strip()[:255]


@router.post("", response_model=InsightOut)
async def push_insight(
    item: InsightIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InsightOut:
    key = _dedup_key(item)

    if key:
        existing = (
            await db.execute(
                select(Event).where(Event.user_id == user.id, Event.dedup_key == key)
            )
        ).scalar_one_or_none()
        if existing:
            return InsightOut(accepted=True, deduped=True, event_id=existing.id)

    event = Event(
        user_id=user.id,
        source=SOURCE_HERMES,
        type=TYPE_INSIGHT,
        content=item.summary,
        title=item.title[:255],
        dedup_key=key or None,
        entities={
            "category": item.category,
            "impact": item.impact,
            "topics": item.topics,
            "importance": item.importance,
            "source_url": item.source_url,
            "source_name": item.source_name,
            "published_at": item.published_at.isoformat() if item.published_at else None,
        },
    )
    db.add(event)
    await db.flush()

    lines = [item.summary]
    if item.impact:
        lines.append(f"影响：{item.impact}")

    msg = Message(
        user_id=user.id,
        kind=KIND_INSIGHT,
        content=item.title,
        card={
            "kind": "insight",
            "title": item.title,
            "lines": lines,
            "meta": {
                "source_url": item.source_url,
                "source_name": item.source_name,
                "category": item.category,
                "importance": item.importance,
            },
        },
        ref_event_id=event.id,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    return InsightOut(accepted=True, deduped=False, event_id=event.id, message_id=msg.id)
