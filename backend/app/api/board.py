from datetime import date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.digest import Digest
from app.models.event import Event
from app.models.insight import Insight
from app.models.user import User
from app.schemas.board import TodayBoardResponse
from app.services.deps import get_current_user

router = APIRouter(prefix="/api/board", tags=["Board"])


@router.get("/today", response_model=TodayBoardResponse)
async def get_today_board(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())

    event_count_q = select(func.count(Event.id)).where(
        Event.user_id == user.id,
        Event.recorded_at >= today_start,
    )
    today_event_count = (await db.execute(event_count_q)).scalar()

    today_events_q = (
        select(Event)
        .where(Event.user_id == user.id, Event.recorded_at >= today_start)
        .order_by(Event.recorded_at)
    )
    today_events = (await db.execute(today_events_q)).scalars().all()

    sport_done = any(e.type == "sport" for e in today_events)
    mood = None
    for e in reversed(today_events):
        if e.type == "mood" and e.sentiment:
            mood = e.sentiment
            break

    water_warning = not any(
        e.type == "health"
        and e.entities
        and "饮水" in str(e.entities)
        for e in today_events
    )

    insights_q = (
        select(Insight)
        .where(Insight.user_id == user.id)
        .order_by(Insight.created_at.desc())
        .limit(3)
    )
    latest_insights = (await db.execute(insights_q)).scalars().all()

    digest_q = (
        select(Digest)
        .where(Digest.user_id == user.id)
        .order_by(Digest.date.desc())
        .limit(1)
    )
    latest_digest = (await db.execute(digest_q)).scalar_one_or_none()

    hour = datetime.utcnow().hour
    greeting = "早上好" if hour < 12 else "下午好" if hour < 18 else "晚上好"

    return TodayBoardResponse(
        greeting=f"{greeting}，{user.name or '朋友'}",
        date=today.isoformat(),
        today_event_count=today_event_count,
        sport_done=sport_done,
        mood=mood,
        water_warning=water_warning,
        recent_events=[
            {
                "id": str(e.id),
                "type": e.type,
                "content": e.content,
                "recorded_at": e.recorded_at.isoformat(),
            }
            for e in today_events[-5:]
        ],
        latest_insights=[
            {
                "id": str(i.id),
                "title": i.title,
                "category": i.category,
                "summary": i.summary,
            }
            for i in latest_insights
        ],
        has_latest_digest=latest_digest is not None,
        digest_date=latest_digest.date if latest_digest else None,
    )
