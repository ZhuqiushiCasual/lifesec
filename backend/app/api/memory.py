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


@router.get("/weekly")
async def get_weekly_trends(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import date, datetime, timedelta

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    result = await db.execute(
        select(Event).where(
            Event.user_id == user.id,
            Event.recorded_at >= datetime.combine(week_start, datetime.min.time()),
            Event.recorded_at < datetime.combine(week_end + timedelta(days=1), datetime.min.time()),
        )
    )
    events = result.scalars().all()

    days = [(week_start + timedelta(days=i)) for i in range(7)]
    day_labels = ["一", "二", "三", "四", "五", "六", "日"]

    type_day: dict[str, list[list[Event]]] = {}
    for e in events:
        day_idx = (e.recorded_at.date() - week_start).days
        if 0 <= day_idx < 7:
            t = e.type
            if t not in type_day:
                type_day[t] = [[] for _ in range(7)]
            type_day[t][day_idx].append(e)

    def _num(entities: dict | None, key: str) -> float:
        if not entities:
            return 0.0
        val = entities.get(key)
        if val is None:
            return 0.0
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    chart_configs = {
        "sport": {
            "title": "🏃 运动时长",
            "unit": "分钟",
            "color": "primary",
            "aggregate": lambda day_evs: sum(_num(e.entities, "duration") for e in day_evs),
            "summary": lambda data: f"{sum(1 for v in data if v > 0)}次 · 共{int(sum(data))}分钟",
        },
        "sleep": {
            "title": "😴 睡眠时长",
            "unit": "小时",
            "color": "accentLavender",
            "target": 8,
            "aggregate": lambda day_evs: max(
                (_num(e.entities, "duration") for e in day_evs), default=0
            ),
            "summary": lambda data: f"日均{round(sum(data) / max(sum(1 for v in data if v > 0), 1), 1)}小时",
        },
        "dietary": {
            "title": "🍽️ 每日热量",
            "unit": "kcal",
            "color": "accentWheat",
            "target": 2000,
            "aggregate": lambda day_evs: sum(_num(e.entities, "calories") for e in day_evs),
            "summary": lambda data: f"日均{int(sum(data) / max(sum(1 for v in data if v > 0), 1))}kcal",
        },
        "mood": {
            "title": "😊 心情指数",
            "unit": "/5",
            "color": "accentPeach",
            "aggregate": lambda day_evs: round(
                sum(_num(e.entities, "score") for e in day_evs) / len(day_evs), 1
            ) if day_evs else 0,
            "summary": lambda data: f"日均{round(sum(v for v in data if v > 0) / max(sum(1 for v in data if v > 0), 1), 1)}分",
        },
        "event": {
            "title": "📝 事件记录",
            "unit": "次",
            "color": "accentSky",
            "aggregate": lambda day_evs: len(day_evs),
            "summary": lambda data: f"共{int(sum(data))}条记录",
        },
    }

    charts = []
    for t, cfg in chart_configs.items():
        if t not in type_day:
            continue
        day_lists = type_day[t]
        data = [cfg["aggregate"](day_lists[i]) for i in range(7)]
        if all(v == 0 for v in data):
            continue
        chart = {
            "type": t,
            "title": cfg["title"],
            "unit": cfg["unit"],
            "color": cfg["color"],
            "data": data,
            "summary": cfg["summary"](data),
        }
        if "target" in cfg:
            chart["target"] = cfg["target"]
        charts.append(chart)

    chart_types = {c["type"] for c in charts}
    health_events = [
        {
            "id": str(e.id),
            "type": e.type,
            "content": e.content,
            "recorded_at": e.recorded_at.isoformat(),
        }
        for e in sorted(events, key=lambda x: x.recorded_at)
        if e.type in ("health", "sleep")
    ]

    return {
        "week_start": week_start.isoformat(),
        "days": [d.isoformat() for d in days],
        "day_labels": day_labels,
        "charts": [c for c in charts if c["type"] != "health"],
        "health_events": health_events,
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
