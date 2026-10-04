"""4.4 会话短期 —— 最近 N 轮，用于指代消解。

边界（architecture ④.4）：**不无限增长，不做自由陪聊。**
只取最近 SESSION_WINDOW 轮，够消解"那个""上次说的那件事"就行。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.event import SOURCE_USER, Event
from app.models.message import Message


async def as_history(db: AsyncSession, user_id: str, limit: int | None = None) -> list[dict]:
    """返回 OpenAI messages 格式的最近对话（用户轮 + 秘书轮，按时间合并）。"""
    n = limit or settings.session_window

    msgs = (
        await db.execute(
            select(Message).where(Message.user_id == user_id).order_by(Message.created_at.desc()).limit(n)
        )
    ).scalars().all()

    events = (
        await db.execute(
            select(Event)
            .where(Event.user_id == user_id, Event.source == SOURCE_USER)
            .order_by(Event.created_at.desc())
            .limit(n)
        )
    ).scalars().all()

    turns = [{"at": m.created_at, "role": "assistant", "content": m.content} for m in msgs]
    turns += [{"at": e.created_at, "role": "user", "content": e.content} for e in events]
    turns.sort(key=lambda t: (t["at"] is None, t["at"]))

    return [{"role": t["role"], "content": t["content"]} for t in turns[-n * 2 :]]
