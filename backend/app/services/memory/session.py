"""4.4 会话短期 —— 最近 N 轮，用于指代消解。

边界（architecture ④.4）：**不无限增长，不做自由陪聊。**
只取最近 SESSION_WINDOW 轮，够消解"那个""上次说的那件事"就行。

窗口消息已经收在一张表里（messages，role=me/secretary），所以这里只是一次普通查询，
不再跨表归并——也就不存在"同一秒的两条谁先谁后"这种问题。
"""

from __future__ import annotations

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.message import ROLE_ME, Message


async def as_history(db: AsyncSession, user_id: str, limit: int | None = None) -> list[dict]:
    """返回 OpenAI messages 格式的最近对话，按时间正序。"""
    n = limit or settings.session_window

    # 排序键 (时间, 轮次, id)：同一秒落下的两条也要稳定地"先我说的、再它说的"
    rank = case((Message.role == ROLE_ME, 0), else_=1)
    rows = (
        await db.execute(
            select(Message)
            .where(Message.user_id == user_id)
            .order_by(Message.created_at.desc(), rank.desc(), Message.id.desc())
            .limit(n * 2)
        )
    ).scalars().all()

    return [
        {"role": "user" if m.role == ROLE_ME else "assistant", "content": m.content}
        for m in reversed(rows)
    ]
