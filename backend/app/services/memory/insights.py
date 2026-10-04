"""4.3 洞察记忆 —— 外部世界进来的部分。

不单独建表：Hermes 推来的消息落在 events(source=hermes)，这一层就是一个读取视图。
**外部驱动写入，系统不可自造**——这是它和 4.1/4.2 的根本区别。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SOURCE_HERMES, Event


async def recent(db: AsyncSession, user_id: str, limit: int = 3) -> list[Event]:
    return (
        await db.execute(
            select(Event)
            .where(Event.user_id == user_id, Event.source == SOURCE_HERMES)
            .order_by(Event.recorded_at.desc())
            .limit(limit)
        )
    ).scalars().all()


def render(items: list[Event]) -> str:
    if not items:
        return ""
    lines = []
    for e in items:
        impact = (e.entities or {}).get("impact")
        head = e.title or e.content[:40]
        lines.append(f"- {head}" + (f"（影响：{impact}）" if impact else ""))
    return "外部动态：\n" + "\n".join(lines)
