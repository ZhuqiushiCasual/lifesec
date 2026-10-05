"""窗口流 —— 聊天窗口拉取的全部内容。

一个接口，三种用法：

  主视图   filter=all      用户轮 + 秘书轮合并，按时间正序（窗口从旧到新往下滚）
  回溯     filter=record   只看"我说过的话"（events source=user）
          filter=insight   只看"推来的洞察"（messages kind=insight，自带卡片）
          这两者用 order=desc + before 游标翻页（新的在上，"加载更早"往下追加）

不做独立页面：回溯是只读的回忆，弹层就够，不违背"一个窗口"。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import SOURCE_USER, Event
from app.models.message import KIND_INSIGHT, Message
from app.models.user import User
from app.schemas.api import StreamItemOut
from app.services.deps import get_current_user

router = APIRouter(prefix="/api/messages", tags=["messages"])

# 同一时刻下，用户轮永远排在秘书轮前面。
# 一次 /api/chat 会先后落一条 event（我发的）和一条 message（它的回应），两者时间只差几毫秒——
# 只要库里时间戳精度不够（MySQL 的 DATETIME 默认只到秒），它们就会完全相等；
# 此时"谁先谁后"只能靠这个次序键定，交给 ORDER BY 是不可靠的。
_ROLE_RANK = {"me": 0, "secretary": 1}


def _event_item(e: Event) -> StreamItemOut:
    return StreamItemOut(id=e.id, role="me", kind="user", content=e.content, card=None, created_at=e.created_at)


def _message_item(m: Message) -> StreamItemOut:
    return StreamItemOut(id=m.id, role="secretary", kind=m.kind, content=m.content, card=m.card, created_at=m.created_at)


def _order_key(item: StreamItemOut) -> tuple:
    """归并次序：(时间, 轮次, id)。id 只用来把同一时刻的多条排成稳定次序。"""
    return (item.created_at, _ROLE_RANK.get(item.role, 9), item.id)


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

    def shape(stmt, col, model):
        # id 只用于把同一时刻的多条记录排成稳定次序，不表达业务含义
        if before is not None:
            stmt = stmt.where(col < before)
        key = col.asc() if asc else col.desc()
        return stmt.order_by(key, model.id.asc() if asc else model.id.desc()).limit(limit)

    if filter == "record":
        stmt = select(Event).where(Event.user_id == user.id, Event.source == SOURCE_USER)
        rows = (await db.execute(shape(stmt, Event.created_at, Event))).scalars().all()
        return [_event_item(e) for e in rows]

    if filter == "insight":
        stmt = select(Message).where(Message.user_id == user.id, Message.kind == KIND_INSIGHT)
        rows = (await db.execute(shape(stmt, Message.created_at, Message))).scalars().all()
        return [_message_item(m) for m in rows]

    # filter == all：两侧各取一批，归并后取最新的 limit 条。
    # 先按最新取、再截断，保证 before 游标不会漏掉更早的记录。
    ev = select(Event).where(Event.user_id == user.id, Event.source == SOURCE_USER)
    ms = select(Message).where(Message.user_id == user.id)
    if before is not None:
        ev = ev.where(Event.created_at < before)
        ms = ms.where(Message.created_at < before)
    ev = ev.order_by(Event.created_at.desc()).limit(limit)
    ms = ms.order_by(Message.created_at.desc()).limit(limit)

    items = [_event_item(e) for e in (await db.execute(ev)).scalars().all()]
    items += [_message_item(m) for m in (await db.execute(ms)).scalars().all()]

    # 直接升序排、再取尾部 limit 条：并列项的先后由 _order_key 定。
    # 不能先降序排、取完再整体 reverse —— 那样会把并列项的先后翻过来，
    # 表现为"它的回应跑到了我发送的消息上面"。
    items.sort(key=_order_key)
    items = items[-limit:]
    if not asc:
        items.reverse()
    return items
