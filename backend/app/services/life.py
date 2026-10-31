"""生活档案 —— 只读投影。

不是第二套记忆：真相源仍然是 `events`（以及挂在它上面的 `date_visits`）。
这里只做三件事：

    ① 把事件 / 探店 / 洞察归一成同一种 LifeItem，供「回看」线路图使用
    ② 聚合地点（去过几次、上次哪天、评价），供「地点」筛选
    ③ 打开一个站点时，把当时的原话一起带出来

训练（workouts）在 V3.3 接入，这里先留出 domain=workout 的位置。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.date_menu import DateMenuItem
from app.models.date_visit import DateVisit
from app.models.event import SOURCE_HERMES, SOURCE_USER, Event
from app.models.exercise import Exercise
from app.models.message import KIND_INSIGHT, ROLE_ME, Message
from app.models.outing_spot import OutingSpot
from app.models.plan import Plan
from app.models.user import User
from app.models.workout import Workout, WorkoutSet
from app.services import fitness


def _clip(text: Any, limit: int = 48) -> str:
    value = str(text or "").strip().splitlines()[0] if str(text or "").strip() else ""
    return value if len(value) <= limit else value[:limit] + "…"


def _event_item(event: Event, visit: DateVisit | None, workout, raw_count: int) -> dict:
    place = None
    people = None
    if visit is not None:
        place = " · ".join(x for x in (visit.restaurant_name, visit.branch) if x)
        people = visit.companion
    if workout is not None and workout.place:
        place = workout.place
    domain = "workout" if workout is not None else "dining" if visit is not None else "general"

    return {
        "id": event.id,
        "item_kind": "event",
        "kind": event.type,
        "domain": domain,
        "type": event.type,
        "title": _clip(event.content),
        "summary": event.content,
        "content": event.content,
        "tags": list(event.tags or []),
        "occurred_on": event.occurred_on,
        "created_at": event.recorded_at or event.created_at,
        "merged_count": event.merged_count or 1,
        "place": place,
        "people": people,
        "ref": {
            "event_id": event.id,
            "date_visit_id": visit.id if visit is not None else None,
            "workout_id": workout.id if workout is not None else None,
        },
        "workout_id": workout.id if workout is not None else None,
        "card": None,
        "raw_count": raw_count,
    }


def _insight_meta(event: Event) -> dict:
    entities = event.entities or {}
    return {
        "event_id": event.id,
        "title": event.title or "",
        "summary": entities.get("summary") or event.content,
        "impact": entities.get("impact"),
        "category": entities.get("category"),
        "source_name": entities.get("source_name") or "外部消息",
        "source_url": entities.get("source_url") or event.dedup_key,
        "published_at": entities.get("published_at"),
        "importance": entities.get("importance") or 3,
        "tags": list(event.tags or []),
    }


def _insight_item(event: Event) -> dict:
    meta = _insight_meta(event)
    return {
        "id": event.id,
        "item_kind": "insight",
        "kind": "insight",
        "domain": "insight",
        "type": "insight",
        "title": meta["title"] or _clip(meta["summary"]),
        "summary": meta["summary"],
        "content": event.content,
        "tags": list(event.tags or []),
        "occurred_on": event.occurred_on,
        "created_at": event.recorded_at or event.created_at,
        "merged_count": 1,
        "place": None,
        "people": None,
        "ref": {"event_id": event.id},
        "card": {"kind": "insight", "title": meta["title"], "lines": [], "meta": meta},
        "raw_count": 0,
    }


async def _visits_by_event(
    db: AsyncSession, user: User, event_ids: list[str]
) -> dict[str, DateVisit]:
    if not event_ids:
        return {}
    rows = (
        await db.execute(
            select(DateVisit).where(
                DateVisit.user_id == user.id, DateVisit.event_id.in_(event_ids)
            )
        )
    ).scalars().all()
    return {row.event_id: row for row in rows if row.event_id}


async def _raw_counts(db: AsyncSession, user: User, event_ids: list[str]) -> dict[str, int]:
    if not event_ids:
        return {}
    rows = await db.execute(
        select(Message.ref_event_id, func.count())
        .where(
            Message.user_id == user.id,
            Message.role == ROLE_ME,
            Message.ref_event_id.in_(event_ids),
        )
        .group_by(Message.ref_event_id)
    )
    return {ref: count for ref, count in rows.all() if ref}


async def timeline(
    db: AsyncSession,
    user: User,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    domain: str | None = None,
    q: str | None = None,
    place: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """回看线路：事件 + 洞察，按记录时间倒序。"""
    stmt = select(Event).where(
        Event.user_id == user.id, Event.source.in_([SOURCE_USER, SOURCE_HERMES])
    )
    if date_from is not None:
        stmt = stmt.where(Event.occurred_on >= date_from)
    if date_to is not None:
        stmt = stmt.where(Event.occurred_on <= date_to)
    if domain == "insight":
        stmt = stmt.where(Event.source == SOURCE_HERMES)
    elif domain == "general":
        stmt = stmt.where(Event.source == SOURCE_USER)
    elif domain == "dining":
        stmt = stmt.where(Event.source == SOURCE_USER)
        stmt = stmt.where(
            Event.id.in_(
                select(DateVisit.event_id).where(
                    DateVisit.user_id == user.id, DateVisit.event_id.is_not(None)
                )
            )
        )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Event.content.like(like), Event.title.like(like)))
    if place:
        stmt = stmt.where(
            Event.id.in_(
                select(DateVisit.event_id).where(
                    DateVisit.user_id == user.id,
                    DateVisit.restaurant_name.like(f"%{place.strip()}%"),
                )
            )
        )

    stmt = stmt.order_by(Event.recorded_at.desc(), Event.id.desc()).limit(limit)
    events = (await db.execute(stmt)).scalars().all()

    event_ids = [e.id for e in events]
    visits = await _visits_by_event(db, user, event_ids)
    workouts = await fitness.by_events(db, user, event_ids)
    counts = await _raw_counts(db, user, event_ids)

    items: list[dict] = []
    for event in events:
        if event.source == SOURCE_HERMES:
            items.append(_insight_item(event))
        else:
            items.append(
                _event_item(
                    event,
                    visits.get(event.id),
                    workouts.get(event.id),
                    counts.get(event.id, 0),
                )
            )
    return items


def _sort_key(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


async def search(db: AsyncSession, user: User, query: str, *, limit: int = 40) -> list[dict]:
    """跨事件 / 洞察 / 探店 / 训练 / 计划搜索。"""
    q = (query or "").strip()
    if not q:
        return []
    like = f"%{q}%"
    results: list[dict] = []
    covered_events: set[str] = set()

    # 探店
    visits = (
        await db.execute(
            select(DateVisit)
            .where(
                DateVisit.user_id == user.id,
                or_(
                    DateVisit.restaurant_name.like(like),
                    DateVisit.review.like(like),
                    DateVisit.companion.like(like),
                ),
            )
            .order_by(DateVisit.visited_on.desc())
            .limit(limit)
        )
    ).scalars().all()
    for visit in visits:
        if visit.event_id:
            covered_events.add(visit.event_id)
        name = " · ".join(x for x in (visit.restaurant_name, visit.branch) if x)
        results.append(
            {
                "type": "dining",
                "id": visit.id,
                "title": name or "吃饭",
                "subtitle": f"{visit.visited_on} · {visit.review or visit.cuisine or ''}".strip(" ·"),
                "event_id": visit.event_id,
                "date_visit_id": visit.id,
                "_sort": _sort_key(visit.visited_on),
            }
        )

    # 训练（标题 / 场地 / 动作名）
    set_rows = (
        await db.execute(
            select(WorkoutSet.workout_id, WorkoutSet.exercise_name)
            .where(WorkoutSet.exercise_name.like(like))
            .distinct()
            .limit(limit * 4)
        )
    ).all()
    set_ids = {row[0] for row in set_rows}
    workout_conds = [Workout.title.like(like), Workout.place.like(like)]
    if set_ids:
        workout_conds.append(Workout.id.in_(set_ids))
    workouts = (
        await db.execute(
            select(Workout)
            .where(Workout.user_id == user.id, or_(*workout_conds))
            .order_by(Workout.performed_on.desc())
            .limit(limit)
        )
    ).scalars().all()
    exercise_names: dict[str, list[str]] = {}
    if workouts:
        rows = (
            await db.execute(
                select(WorkoutSet.workout_id, WorkoutSet.exercise_name).where(
                    WorkoutSet.workout_id.in_([w.id for w in workouts])
                )
            )
        ).all()
        for workout_id, name in rows:
            bucket = exercise_names.setdefault(workout_id, [])
            if name and name not in bucket:
                bucket.append(name)
    for workout in workouts:
        if workout.event_id:
            covered_events.add(workout.event_id)
        names = exercise_names.get(workout.id, [])
        extra = " / ".join(names[:4])
        results.append(
            {
                "type": "workout",
                "id": workout.id,
                "workout_id": workout.id,
                "event_id": workout.event_id,
                "title": workout.title or "训练",
                "subtitle": " · ".join(
                    x for x in (str(workout.performed_on), workout.place, extra) if x
                ),
                "_sort": _sort_key(workout.performed_on),
            }
        )

    # 事件 / 洞察
    events = (
        await db.execute(
            select(Event)
            .where(
                Event.user_id == user.id,
                Event.source.in_([SOURCE_USER, SOURCE_HERMES]),
                or_(Event.content.like(like), Event.title.like(like)),
            )
            .order_by(Event.recorded_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    for event in events:
        if event.id in covered_events:
            continue
        is_insight = event.source == SOURCE_HERMES
        tags = list(event.tags or [])
        results.append(
            {
                "type": "insight" if is_insight else "event",
                "id": event.id,
                "event_id": event.id,
                "title": (event.title if is_insight and event.title else _clip(event.content)),
                "subtitle": " · ".join(
                    x
                    for x in (
                        str(event.occurred_on or ""),
                        " / ".join(tags[:3]),
                    )
                    if x
                ),
                "_sort": _sort_key(event.recorded_at or event.created_at),
            }
        )

    # 计划
    plans = (
        await db.execute(
            select(Plan)
            .where(
                Plan.user_id == user.id,
                or_(Plan.title.like(like), Plan.place.like(like)),
            )
            .order_by(Plan.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    kind_label = {
        "workout": "训练计划",
        "meal": "吃饭计划",
        "outing": "出门计划",
        "travel": "出行计划",
        "goal": "目标",
        "todo": "待办",
    }
    for plan in plans:
        when = plan.scheduled_on or plan.due_date
        results.append(
            {
                "type": "plan",
                "id": plan.id,
                "plan_id": plan.id,
                "title": plan.title,
                "subtitle": " · ".join(
                    x for x in (kind_label.get(plan.kind, "计划"), str(when or "未定日期"), plan.place) if x
                ),
                "_sort": _sort_key(when or plan.created_at),
            }
        )

    results.sort(key=lambda item: item.get("_sort", ""), reverse=True)
    for item in results:
        item.pop("_sort", None)
    return results[:limit]


async def plan_detail(db: AsyncSession, user: User, plan_id: str) -> dict | None:
    """计划的执行视图：训练动作（含媒体）/ 餐厅 / 出门地点。"""
    plan = (
        await db.execute(select(Plan).where(Plan.id == plan_id, Plan.user_id == user.id))
    ).scalars().first()
    if plan is None:
        return None

    data = {
        "id": plan.id,
        "title": plan.title,
        "status": plan.status,
        "kind": plan.kind,
        "scheduled_on": plan.scheduled_on,
        "due_date": plan.due_date,
        "place": plan.place,
        "ref_type": plan.ref_type,
        "ref_id": plan.ref_id,
        "meta": plan.meta or {},
        "source": plan.source,
        "created_at": plan.created_at,
        "exercises": [],
        "food": None,
        "outing": None,
    }

    meta = plan.meta or {}
    names: list[str] = []
    for item in meta.get("exercises") or []:
        name = item.get("name") if isinstance(item, dict) else str(item)
        if name:
            names.append(name)
    if names:
        rows = (await db.execute(select(Exercise))).scalars().all()
        by_name = {row.name: row for row in rows}
        for item in meta.get("exercises") or []:
            name = item.get("name") if isinstance(item, dict) else str(item)
            exercise = by_name.get(name)
            data["exercises"].append(
                {
                    "name": name,
                    "exercise_id": exercise.id if exercise else (item.get("id") if isinstance(item, dict) else None),
                    "body_part": exercise.body_part if exercise else (item.get("body_part") if isinstance(item, dict) else ""),
                    "equipment": exercise.equipment if exercise else (item.get("equipment") if isinstance(item, dict) else ""),
                    "target": exercise.target if exercise else "",
                    "media_path": exercise.media_path if exercise else (item.get("media_path") if isinstance(item, dict) else ""),
                }
            )

    if plan.ref_type == "date_menu" and plan.ref_id:
        food = (
            await db.execute(select(DateMenuItem).where(DateMenuItem.id == plan.ref_id))
        ).scalars().first()
        if food is not None:
            data["food"] = {
                "id": food.id,
                "name": food.name,
                "branch": food.branch,
                "cuisine": food.cuisine,
                "reason": food.reason,
                "price": food.price,
                "score": food.score,
                "dist_km": food.dist_km,
                "photo": food.photo,
                "art": food.art,
                "accent_a": food.accent_a,
                "accent_b": food.accent_b,
            }

    if plan.ref_type == "outing_spot" and plan.ref_id:
        spot = (
            await db.execute(select(OutingSpot).where(OutingSpot.id == plan.ref_id))
        ).scalars().first()
        if spot is not None:
            data["outing"] = {
                "id": spot.id,
                "name": spot.name,
                "kind": spot.kind,
                "area": spot.area,
                "note": spot.note,
                "tags": list(spot.tags or []),
            }

    return data


async def places(db: AsyncSession, user: User, *, kind: str = "dining") -> list[dict]:
    """地点聚合：当前第一类是餐饮；训练场地在 V3.3 接入。"""
    if kind != "dining":
        return []
    rows = (
        await db.execute(
            select(DateVisit).where(DateVisit.user_id == user.id).order_by(
                DateVisit.visited_on.desc(), DateVisit.created_at.desc()
            )
        )
    ).scalars().all()

    groups: dict[str, dict] = {}
    for row in rows:
        name = (row.restaurant_name or "").strip()
        if not name:
            continue
        item = groups.setdefault(
            name,
            {
                "name": name,
                "kind": "dining",
                "count": 0,
                "last_on": None,
                "rating": None,
                "review": "",
                "restaurant_id": row.restaurant_id,
                "branch": row.branch or "",
                "cuisine": row.cuisine or "",
            },
        )
        item["count"] += 1
        if item["last_on"] is None or (row.visited_on and row.visited_on > item["last_on"]):
            item["last_on"] = row.visited_on
        if row.rating is not None:
            item["rating"] = row.rating
        if row.review:
            item["review"] = row.review

    return sorted(
        groups.values(),
        key=lambda x: x["last_on"] or date.min,
        reverse=True,
    )


async def experience_detail(
    db: AsyncSession, user: User, item_kind: str, item_id: str
) -> dict | None:
    """一个站点的详情：原话优先，结构化字段其次。"""
    event = (
        await db.execute(
            select(Event).where(Event.id == item_id, Event.user_id == user.id)
        )
    ).scalars().first()
    if event is None:
        return None

    if item_kind == "insight" or event.source == SOURCE_HERMES:
        messages = (
            await db.execute(
                select(Message)
                .where(
                    Message.user_id == user.id,
                    Message.kind == KIND_INSIGHT,
                    Message.ref_event_id == event.id,
                )
                .order_by(Message.created_at.asc())
            )
        ).scalars().all()
        item = _insight_item(event)
        visit_payload = None
    else:
        messages = (
            await db.execute(
                select(Message)
                .where(
                    Message.user_id == user.id,
                    Message.role == ROLE_ME,
                    Message.ref_event_id == event.id,
                )
                .order_by(Message.created_at.asc())
            )
        ).scalars().all()
        visit = (
            await db.execute(
                select(DateVisit).where(
                    DateVisit.user_id == user.id, DateVisit.event_id == event.id
                )
            )
        ).scalars().first()
        workouts = await fitness.by_events(db, user, [event.id])
        workout = workouts.get(event.id)
        item = _event_item(event, visit, workout, len(messages))
        visit_payload = None
        if visit is not None:
            visit_payload = {
                "id": visit.id,
                "restaurant_id": visit.restaurant_id,
                "restaurant_name": visit.restaurant_name,
                "branch": visit.branch,
                "cuisine": visit.cuisine,
                "visited_on": visit.visited_on,
                "rating": visit.rating,
                "dishes": list(visit.dishes or []),
                "companion": visit.companion,
                "occasion": visit.occasion,
                "review": visit.review,
            }

    workout_payload = (
        await fitness.detail(db, user, workout.id) if workout is not None else None
    )
    return {
        "item": item,
        "raw_messages": [
            {"id": m.id, "content": m.content, "created_at": m.created_at}
            for m in messages
        ],
        "date_visit": visit_payload,
        "workout": workout_payload,
    }
