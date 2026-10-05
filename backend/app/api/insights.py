"""洞察接口 —— Hermes 的回调入口。

边界（architecture 5.3）：selfsec **不自建抓取管线**，只接收结果。
落库后立刻生成一条 message，于是洞察会像别的东西一样出现在同一个窗口里。

洞察走 events(source=hermes)，**不参与"同一天合并"**——它是外部推来的一条独立消息，
一条就是一个事件；标签直接用推送方给的 category / topics，好让回溯和标签统计不分家。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import SOURCE_HERMES, TYPE_INSIGHT, Event
from app.models.message import KIND_INSIGHT, ROLE_SECRETARY, Message
from app.models.user import User
from app.schemas.api import InsightIn, InsightOut
from app.services.deps import get_current_user
from app.utils import now_local

router = APIRouter(prefix="/api/insights", tags=["insights"])


def _dedup_key(item: InsightIn) -> str:
    return (item.source_url or item.title or "").strip()[:255]


def _tags_from(item: InsightIn) -> list[str]:
    """category + topics 就是这条洞察现成的标签。"""
    tags = [t for t in ([item.category] + list(item.topics)) if t]
    seen: list[str] = []
    for t in tags:
        s = str(t).strip()
        if s and s not in seen:
            seen.append(s)
    return seen[:5]


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

    now = now_local()
    event = Event(
        user_id=user.id,
        source=SOURCE_HERMES,
        type=TYPE_INSIGHT,
        content=item.summary,
        title=item.title[:255],
        dedup_key=key or None,
        tags=_tags_from(item) or None,
        occurred_on=now.date(),
        recorded_at=now,
        last_at=now,
        merged_count=1,
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
        role=ROLE_SECRETARY,
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
                "tags": event.tags or [],
                "event_id": event.id,
            },
        },
        ref_event_id=event.id,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    return InsightOut(accepted=True, deduped=False, event_id=event.id, message_id=msg.id)
