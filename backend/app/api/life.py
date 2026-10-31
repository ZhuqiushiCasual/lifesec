"""生活档案：回看 / 地点 / 经历详情（只读）。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.date_menu import DateMenuItem
from app.models.plan import Plan
from app.models.user import User
from app.schemas.api import PlanCreate, PlanLifePatch, PlanOut
from app.services import fitness, life, outing
from app.services.deps import get_current_user

router = APIRouter(prefix="/api/life", tags=["life"])


@router.get("/timeline")
async def get_timeline(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    domain: str | None = Query(None, pattern="^(general|dining|workout|insight)$"),
    q: str | None = Query(None, max_length=100),
    place: str | None = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=300),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await life.timeline(
        db,
        user,
        date_from=date_from,
        date_to=date_to,
        domain=domain,
        q=q,
        place=place,
        limit=limit,
    )


@router.get("/search")
async def search_life(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(40, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await life.search(db, user, q, limit=limit)


@router.get("/places")
async def get_places(
    kind: str = Query("dining", pattern="^(dining|workout)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await life.places(db, user, kind=kind)


@router.get("/exercises")
async def get_exercises(
    q: str | None = Query(None, max_length=60),
    body_part: str | None = Query(None, max_length=16),
    equipment: str | None = Query(None, max_length=16),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await fitness.options(db, q=q, body_part=body_part, equipment=equipment)


@router.get("/options")
async def get_options(
    kind: str = Query("workout", pattern="^(workout|food|outing)$"),
    q: str | None = Query(None, max_length=60),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """安排页候选池：训练动作 / 餐厅 / 出门地点。"""
    if kind == "workout":
        rows = await fitness.options(db, q=q)
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "subtitle": f'{row["body_part"]} · {row["equipment"]}',
                "tags": [row["body_part"], row["equipment"]],
                "meta": row,
            }
            for row in rows
        ]

    if kind == "food":
        stmt = select(DateMenuItem).where(DateMenuItem.hidden.is_(False))
        if q:
            stmt = stmt.where(DateMenuItem.name.like(f"%{q.strip()}%"))
        rows = (
            await db.execute(stmt.order_by(DateMenuItem.sort, DateMenuItem.id))
        ).scalars().all()
        return [
            {
                "id": row.id,
                "name": row.name,
                "subtitle": " · ".join(x for x in (row.cuisine, row.branch) if x),
                "tags": [row.cuisine] if row.cuisine else [],
                "meta": {
                    "reason": row.reason,
                    "dist_km": row.dist_km,
                    "dist_work_km": row.dist_work_km,
                    "price": row.price,
                    "score": row.score,
                    "taste_label": row.taste_label,
                    "photo": row.photo,
                    "art": row.art,
                    "accent_a": row.accent_a,
                    "accent_b": row.accent_b,
                },
            }
            for row in rows
        ]

    if kind == "outing":
        rows = await outing.options(db, q)
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "subtitle": f'{row["area"]} · {row["kind"]}',
                "tags": row["tags"],
                "meta": row,
            }
            for row in rows
        ]

    return []


@router.get("/workouts/last")
async def get_last_workout(
    exercise: str = Query(..., min_length=1, max_length=60),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await fitness.last_for_exercise(db, user, exercise) or {}


@router.get("/workouts/stats")
async def get_workout_stats(
    exercise: str | None = Query(None, max_length=60),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await fitness.stats(
        db, user, exercise=exercise, date_from=date_from, date_to=date_to
    )


@router.get("/workouts/{workout_id}")
async def get_workout(
    workout_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await fitness.detail(db, user, workout_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Workout not found")
    return data


@router.get("/plans", response_model=list[PlanOut])
async def list_life_plans(
    status: str = Query("open", pattern="^(open|done|all)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Plan).where(Plan.user_id == user.id)
    if status != "all":
        stmt = stmt.where(Plan.status == status)
    rows = (
        await db.execute(
            stmt.order_by(
                Plan.scheduled_on.is_(None),
                Plan.scheduled_on.asc(),
                Plan.created_at.desc(),
            )
        )
    ).scalars().all()
    return [PlanOut.model_validate(row) for row in rows]


@router.get("/plans/{plan_id}")
async def get_life_plan(
    plan_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await life.plan_detail(db, user, plan_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return data


@router.post("/plans", response_model=PlanOut)
async def create_life_plan(
    payload: PlanCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """从候选（动作 / 餐厅 / 出门地点）生成一条计划。"""
    plan = Plan(
        user_id=user.id,
        title=payload.title,
        status="open",
        due_date=payload.scheduled_on,
        scheduled_on=payload.scheduled_on,
        kind=payload.kind,
        place=payload.place,
        ref_type=payload.ref_type,
        ref_id=payload.ref_id,
        meta=payload.meta or None,
        source=payload.source,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return PlanOut.model_validate(plan)


@router.patch("/plans/{plan_id}", response_model=PlanOut)
async def patch_life_plan(
    plan_id: str,
    payload: PlanLifePatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan = (
        await db.execute(
            select(Plan).where(Plan.id == plan_id, Plan.user_id == user.id)
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    if payload.title is not None:
        plan.title = payload.title
    if payload.status is not None:
        plan.status = payload.status
    if payload.scheduled_on is not None:
        plan.scheduled_on = payload.scheduled_on
        plan.due_date = payload.scheduled_on
    if payload.place is not None:
        plan.place = payload.place
    await db.commit()
    await db.refresh(plan)
    return PlanOut.model_validate(plan)


@router.get("/experiences/{item_kind}/{item_id}")
async def get_experience(
    item_kind: str,
    item_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if item_kind not in ("event", "insight"):
        raise HTTPException(status_code=400, detail="item_kind must be event or insight")
    data = await life.experience_detail(db, user, item_kind, item_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Experience not found")
    return data
