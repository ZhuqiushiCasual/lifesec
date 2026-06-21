from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.insight import Insight
from app.models.user import User
from app.schemas.insight import InsightListResponse, InsightResponse
from app.services.deps import get_current_user
from typing import Optional

router = APIRouter(prefix="/api/insights", tags=["Insights"])


@router.get("", response_model=InsightListResponse)
async def list_insights(
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    where = [Insight.user_id == user.id]
    if category:
        where.append(Insight.category == category)

    total_q = select(func.count(Insight.id)).where(*where)
    total = (await db.execute(total_q)).scalar()

    q = (
        select(Insight)
        .where(*where)
        .order_by(Insight.importance.is_(None).asc(), Insight.importance.desc(), Insight.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(q)
    items = result.scalars().all()

    return InsightListResponse(
        items=[InsightResponse.model_validate(i) for i in items],
        total=total,
    )


@router.get("/{insight_id}", response_model=InsightResponse)
async def get_insight(
    insight_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Insight).where(Insight.id == insight_id, Insight.user_id == user.id)
    )
    insight = result.scalar_one_or_none()
    if not insight:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Insight not found")
    return InsightResponse.model_validate(insight)
