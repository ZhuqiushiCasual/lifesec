"""洞察接口 —— Hermes 的旧版单条回调入口。

边界（architecture 5.3）：selfsec **不自建抓取管线**，只接收结果。
落库后立刻生成一条 message，于是洞察会像别的东西一样出现在同一个窗口里。

新版链路（`/api/ingest/messages`）支持批量、摘要/详情/原文分级、修改与合并；
这个接口保留兼容，内部走同一套消息服务，保证卡片字段一致。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.api import InsightIn, InsightOut
from app.services.deps import get_current_user
from app.services.ingest import messages as message_service

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.post("", response_model=InsightOut)
async def push_insight(
    item: InsightIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InsightOut:
    result = await message_service.upsert_items(
        db,
        user.id,
        [
            {
                "title": item.title,
                "summary": item.summary,
                "source_url": item.source_url,
                "source_name": item.source_name,
                "category": item.category,
                "impact": item.impact,
                "topics": item.topics,
                "importance": item.importance,
                "published_at": item.published_at,
            }
        ],
    )

    event_id = result.event_ids[0] if result.event_ids else None
    message_id = None
    if event_id:
        out = await message_service.get_event_out(db, user.id, event_id)
        message_id = out.message_id

    return InsightOut(
        accepted=result.accepted > 0 or result.skipped > 0,
        deduped=result.created == 0 and result.updated == 0,
        event_id=event_id,
        message_id=message_id,
    )
