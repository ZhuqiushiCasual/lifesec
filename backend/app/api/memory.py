"""记忆接口 —— 查看长期画像 / 手动触发「总结意识」。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.api import MemoryOut
from app.services.deps import get_current_user
from app.services.memory import profile as mem_profile

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("", response_model=MemoryOut)
async def get_memory(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOut:
    row = await mem_profile.get(db, user.id)
    if not row:
        return MemoryOut(profile="", version=0, event_count=0, updated_at=None)
    return MemoryOut(
        profile=row.content, version=row.version, event_count=row.event_count, updated_at=row.updated_at
    )


@router.post("/refresh", response_model=MemoryOut)
async def refresh_memory(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOut:
    row = await mem_profile.refresh(db, user.id, force=True)
    if not row:
        return MemoryOut(profile="", version=0, event_count=0, updated_at=None)
    return MemoryOut(
        profile=row.content, version=row.version, event_count=row.event_count, updated_at=row.updated_at
    )
