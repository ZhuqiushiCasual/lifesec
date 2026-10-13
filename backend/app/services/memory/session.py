"""4.4 会话短期 —— 最近 N 轮，用于指代消解。

两种形态，各有各的用途：

    as_history   最近几轮的**完整对话**（我说的 + 它说的），走 messages 通道，
                 给模型当多轮上下文——这是对话连贯性需要的
    user_turns   Block C：近 USER_TURN_WINDOW 轮「用户提问」，**只取我说的**，
                 带时间锚与主题。它比 messages 看得更远，而且便宜得多
                 （同行里 GPT 的四桶也是只给用户侧消息）。

窗口消息已经收在一张表里（messages，role=me/secretary），所以这里只是普通查询，
不再跨表归并——也就不存在"同一秒的两条谁先谁后"这种问题。
"""

from __future__ import annotations

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.event import Event
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


async def user_turns(db: AsyncSession, user_id: str, limit: int | None = None) -> list[dict]:
    """Block C 的原料：近 N 轮用户提问（只取我说的），带时间锚与主题。

    主题 = 这条消息归入的事件身上的第一个标签（没有就留空）。
    两个必须做的细节（都是抄 GPT 的）：
      · 只给用户侧消息——回复通常长好几倍，带上就是花 token 买噪声
      · 每条都要有时间锚，否则几十轮混在一起，模型做不了时间推理
    """
    n = limit or settings.user_turn_window
    rows = (
        await db.execute(
            select(Message.content, Message.created_at, Message.ref_event_id)
            .where(Message.user_id == user_id, Message.role == ROLE_ME)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(n)
        )
    ).all()

    ids = [r[2] for r in rows if r[2]]
    topics: dict[str, str] = {}
    if ids:
        ev_rows = (await db.execute(select(Event.id, Event.tags).where(Event.id.in_(ids)))).all()
        for eid, tags in ev_rows:
            if tags:
                topics[eid] = str(tags[0])

    return [
        {"at": created_at, "topic": topics.get(eid or "", ""), "content": content}
        for content, created_at, eid in reversed(rows)
    ]


def render_user_turns(items: list[dict]) -> str:
    """Block C 的文本形态。格式：`0912T[09:12] 主题：他说的话`。"""
    if not items:
        return ""
    lines = []
    for it in items:
        at = it.get("at")
        stamp = f"{at:%m%d}T[{at:%H:%M}]" if at else "—"
        topic = (it.get("topic") or "").strip()
        head = f"#{topic} " if topic else ""
        lines.append(f"{stamp} {head}{it.get('content') or ''}")
    return (
        f"【近 {len(items)} 轮你说过的话（只取你说的，按时间正序；用时间锚做指代消解）】\n"
        + "\n".join(lines)
    )
