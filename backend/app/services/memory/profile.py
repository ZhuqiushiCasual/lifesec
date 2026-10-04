"""4.1 长期画像 ·「总结意识」。

它是这个项目"记得住"的底座：不在每次对话里塞原始记录，而是定期把全部事件
压成一段「关于你的话」，之后每次组装 Context 都注入这一段。

三种触发（architecture ④.1）：
  ① 定时      —— 每晚调度器调用（force=True）
  ② 阈值      —— 新增事件数达到 PROFILE_TRIGGER_EVENTS 时自动重算
  ③ 手动      —— POST /api/memory/refresh

单用户数据量小，所以「扫描全部事件」直接全量取，不做采样、不做向量检索——
这是刻意的简化：先让机制成立，再谈规模。
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.event import Event
from app.models.memory import MemoryProfile
from app.services.ai.profile import summarize

log = logging.getLogger("selfsec.memory")

MAX_EVENTS = 500  # 档案上限；单用户很难触及


async def get(db: AsyncSession, user_id: str) -> MemoryProfile | None:
    return (
        await db.execute(select(MemoryProfile).where(MemoryProfile.user_id == user_id))
    ).scalar_one_or_none()


async def text(db: AsyncSession, user_id: str) -> str:
    row = await get(db, user_id)
    return row.content if row else ""


def _line(e: Event) -> str:
    when = e.recorded_at.strftime("%Y-%m-%d") if e.recorded_at else "?"
    return f"[{when}] ({e.type}) {e.content}"


async def refresh(db: AsyncSession, user_id: str, *, force: bool = False) -> MemoryProfile | None:
    """重算画像。未达阈值且非强制时直接返回 None（表示这次不刷新）。"""
    total = (
        await db.execute(select(func.count()).select_from(Event).where(Event.user_id == user_id))
    ).scalar_one()

    row = await get(db, user_id)
    if not force and row and (total - row.event_count) < settings.profile_trigger_events:
        return None
    if total == 0:
        return None

    events = (
        await db.execute(
            select(Event).where(Event.user_id == user_id).order_by(Event.recorded_at.asc()).limit(MAX_EVENTS)
        )
    ).scalars().all()

    content = await summarize([_line(e) for e in events])
    if not content:
        log.warning("画像刷新跳过：摘要生成未返回内容")
        return None

    if row is None:
        row = MemoryProfile(user_id=user_id, content=content, version=1, event_count=total)
        db.add(row)
    else:
        row.content = content
        row.version += 1
        row.event_count = total

    await db.commit()
    await db.refresh(row)
    log.info("画像已刷新 v%s（依据 %s 条事件）", row.version, total)
    return row
