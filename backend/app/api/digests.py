from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.digest import Digest
from app.models.user import User
from app.schemas.digest import DigestResponse
from app.services.deps import get_current_user

router = APIRouter(prefix="/api/digests", tags=["Digests"])


@router.get("/latest", response_model=Optional[DigestResponse])
async def get_latest_digest(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Digest)
        .where(Digest.user_id == user.id)
        .order_by(Digest.date.desc())
        .limit(1)
    )
    digest = result.scalar_one_or_none()
    if not digest:
        return None
    return DigestResponse.model_validate(digest)


@router.get("", response_model=DigestResponse)
async def get_digest_by_date(
    date: str = Query(..., description="Date in YYYY-MM-DD"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Digest).where(
            Digest.user_id == user.id,
            Digest.date == date,
        )
    )
    digest = result.scalar_one_or_none()
    if not digest:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Digest not found for this date")
    return DigestResponse.model_validate(digest)
