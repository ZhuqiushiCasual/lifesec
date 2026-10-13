"""记忆接口 —— 画像（分节）、馆藏（索引卡）、手动迭代。

    GET  /api/memory            画像：分节正文 + 每节来源 + 最近变更摘要
    POST /api/memory/refresh    手动重算画像（force，不推 nudge——用户刚亲眼看过了）
    GET  /api/memory/library    馆藏：索引卡（标签 → 条数 → 最近 → 档首摘要）+ 版本历史
    POST /api/memory/tags/merge 标签归并（软归一的 ②③ 层：写别名表，不合并事件）
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.api import MemoryLibraryOut, MergeTagsOut, MemoryOut, TagCardOut
from app.services.deps import get_current_user
from app.services.memory import library
from app.services.memory import profile as mem_profile

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _to_out(row) -> MemoryOut:
    if not row:
        return MemoryOut(profile="", version=0, event_count=0, updated_at=None)
    sections = mem_profile.sections_of(row)
    return MemoryOut(
        profile=mem_profile.render(sections) or (row.content or ""),
        version=row.version,
        event_count=row.event_count,
        updated_at=row.updated_at,
        sections=sections,
        sources=dict(row.sources or {}),
        summary=row.summary,
        msg_count=row.msg_count or 0,
    )


@router.get("", response_model=MemoryOut)
async def get_memory(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOut:
    return _to_out(await mem_profile.get(db, user.id))


@router.post("/refresh", response_model=MemoryOut)
async def refresh_memory(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOut:
    # notify=False：用户此刻就在看结果，不需要再往窗口里塞一条 nudge
    row = await mem_profile.refresh(db, user.id, force=True, reason="manual", notify=False)
    if row is None:
        row = await mem_profile.get(db, user.id)
    return _to_out(row)


@router.get("/library", response_model=MemoryLibraryOut)
async def get_library(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryLibraryOut:
    rows = await library.card_rows(db, user.id)
    versions = await mem_profile.versions(db, user.id, limit=10)
    return MemoryLibraryOut(
        card=[TagCardOut(tag=r.tag, count=r.count, last_at=r.last_at, digest=r.digest) for r in rows],
        versions=[
            {
                "version": v.version,
                "summary": v.summary,
                "reason": v.reason,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in versions
        ],
    )


@router.post("/tags/merge", response_model=MergeTagsOut)
async def merge_tags(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MergeTagsOut:
    """标签归并：让模型给同义标签的合并建议，写进别名表（检索时按同一个键聚合）。"""
    return MergeTagsOut(applied=await library.merge_tags(db, user.id))
