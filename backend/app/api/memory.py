from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import Event
from app.models.user import User
from app.schemas.event import EventListResponse, EventResponse
from app.services.deps import get_current_user

router = APIRouter(prefix="/api/memory", tags=["Memory"])


@router.get("/trends")
async def get_trends(
    days: int = Query(30, ge=7, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timedelta

    since = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(
        select(Event).where(
            Event.user_id == user.id,
            Event.recorded_at >= since,
        )
    )
    events = result.scalars().all()

    type_counts: dict[str, int] = {}
    sentiment_scores: list[float] = []
    for e in events:
        type_counts[e.type] = type_counts.get(e.type, 0) + 1
        if e.sentiment_score is not None:
            sentiment_scores.append(e.sentiment_score)

    avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0

    return {
        "period_days": days,
        "total_events": len(events),
        "by_type": type_counts,
        "avg_sentiment": round(avg_sentiment, 2),
    }


@router.get("/review")
async def get_review(
    date: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timedelta

    target_date = datetime.strptime(date, "%Y-%m-%d")
    result = await db.execute(
        select(Event).where(
            Event.user_id == user.id,
            Event.recorded_at >= target_date,
            Event.recorded_at < target_date + timedelta(days=1),
        )
    )
    events = result.scalars().all()
    return {
        "date": date,
        "events": [EventResponse.model_validate(e) for e in events],
        "total": len(events),
    }
