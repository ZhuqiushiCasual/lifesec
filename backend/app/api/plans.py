"""待办 —— 从对话里长出来的计划，可勾选。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.plan import Plan
from app.models.user import User
from app.schemas.api import PlanOut, PlanPatch
from app.services.deps import get_current_user

router = APIRouter(prefix="/api/plans", tags=["plans"])


@router.get("", response_model=list[PlanOut])
async def list_plans(
    include_done: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Plan]:
    stmt = select(Plan).where(Plan.user_id == user.id)
    if not include_done:
        stmt = stmt.where(Plan.status == "open")
    rows = (await db.execute(stmt.order_by(Plan.created_at.desc()))).scalars().all()
    return list(rows)


@router.patch("/{plan_id}", response_model=PlanOut)
async def patch_plan(
    plan_id: str,
    patch: PlanPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Plan:
    plan = (
        await db.execute(select(Plan).where(Plan.id == plan_id, Plan.user_id == user.id))
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    plan.status = patch.status
    await db.commit()
    await db.refresh(plan)
    return plan
