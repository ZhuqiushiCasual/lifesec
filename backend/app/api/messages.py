"""窗口流 —— 聊天窗口拉取的全部内容。

一个接口，三种用法：

  主视图   filter=all      窗口里的全部对话（我说的 + 它说的），按时间正序
  回溯     filter=record   只看「合并后的事件」（今天跑过的、记下的那些事，带标签）
          filter=insight   只看「推来的洞察」（messages kind=insight，自带卡片）
          这两者用 order=desc + before 游标翻页（新的在上，"加载更早"往下追加）

窗口流现在是**单表查询**（messages 收了角色两边的全部消息）。
以前是 events + messages 跨表归并，同秒落库时先后不可靠——那个问题从结构上没有了。

关于 limit：**取的是「最近 N 条」，不是「最早的 N 条」**。
LIMIT 作用在时间轴新的一头（先倒序取，需要正序时整体翻转）——
反过来的话，攒够 N 条之后新记的东西就永远进不了窗口，
表现是「我说了、它没回应」，而库里其实每条都在。

不做独立页面：回溯是只读的回忆，弹层就够，不违背"一个窗口"。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import SOURCE_USER, Event
from app.models.message import KIND_INSIGHT, ROLE_ME, Message
from app.models.user import User
from app.schemas.api import StreamItemOut
from app.services.deps import get_current_user

router = APIRouter(prefix="/api/messages", tags=["messages"])


def _order_cols(col) -> tuple:
    """对话排序键（**倒序**）：(时间, 轮次, id)。

    只按时间排不够稳：库里时间戳精度不足时（MySQL 的 DATETIME 默认只到秒），
    同一次对话落下的两条会完全相等，先后就变成随机的。
    加上「轮次」（它说的在我说的之前，翻转后就是我们对外的「我说的在前」）、
    再用 id 兜底，次序就与库的精度无关了。

    也正因为这里是**含 id 的严格全序**，翻转它得到的正是对应的正序，
    并列项的先后不会被打乱（可以放心 reversed）。
    """
    rank = case((Message.role == ROLE_ME, 0), else_=1)
    return (col.desc(), rank.desc(), Message.id.desc())


def _latest(rows, asc: bool):
    """把「最近 N 条（倒序）」调整成调用方要的方向。"""
    return list(reversed(rows)) if asc else list(rows)


def _event_item(e: Event) -> StreamItemOut:
    """事件在回溯里的形态：时间点是"第一次记到它"，并带上标签与合并次数。"""
    return StreamItemOut(
        id=e.id,
        role="event",
        kind=e.type,
        content=e.content,
        card=None,
        tags=list(e.tags or []),
        merged_count=e.merged_count or 1,
        occurred_on=e.occurred_on,
        created_at=e.recorded_at or e.created_at,
    )


def _message_item(m: Message) -> StreamItemOut:
    return StreamItemOut(
        id=m.id,
        role=m.role,
        kind=m.kind,
        content=m.content,
        card=m.card,
        created_at=m.created_at,
    )


@router.get("", response_model=list[StreamItemOut])
async def list_stream(
    limit: int = Query(60, ge=1, le=200),
    filter: str = Query("all", pattern="^(all|record|insight)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    before: datetime | None = Query(None, description="游标：只取该时间之前的记录，用于回溯翻页"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[StreamItemOut]:
    asc = order == "asc"

    # LIMIT 一律作用在时间轴**新**的那一头：先按倒序取最近 N 条，需要正序时整体翻转。
    # 反过来（按正序 LIMIT）取到的是最早的 N 条，攒够 N 条之后新记的东西就再也进不了窗口：
    # 表现是「我说了没反应」，而库里每条都在。窗口与「加载更早」都靠这一条保证方向。

    # 事件线：合并后的事件（记忆），不是消息
    if filter == "record":
        stmt = select(Event).where(Event.user_id == user.id, Event.source == SOURCE_USER)
        if before is not None:
            stmt = stmt.where(Event.recorded_at < before)
        rows = (
            await db.execute(
                stmt.order_by(Event.recorded_at.desc(), Event.id.desc()).limit(limit)
            )
        ).scalars().all()
        return [_event_item(e) for e in _latest(rows, asc)]

    # 对话线：单表，role 直接来自列
    stmt = select(Message).where(Message.user_id == user.id)
    if filter == "insight":
        stmt = stmt.where(Message.kind == KIND_INSIGHT)
    if before is not None:
        stmt = stmt.where(Message.created_at < before)
    rows = (
        await db.execute(stmt.order_by(*_order_cols(Message.created_at)).limit(limit))
    ).scalars().all()
    return [_message_item(m) for m in _latest(rows, asc)]
