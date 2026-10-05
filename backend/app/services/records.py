"""记录层 —— 事件的新建与合并。

一条输入进来，先回答一个问题：**它是今天已有事件的重复/补充，还是一件新事？**

判定不在这里做——它由那唯一一次 LLM 调用顺带给出（merge_event_id）。
这一层只做两件事：

    ① 把「今天已有的事件」整理成候选清单，给模型判断（render_candidates）
    ② 校验模型的决定（id 必须命中候选），然后合并或新建（apply）

校验收紧的理由：模型的幻觉不能改写历史数据。id 不在候选里就当新建——
多一条冗余事件，好过把两件不相干的事揉成一条。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SOURCE_USER, Event
from app.models.user import User
from app.utils import now_local, today_local

# 只把最近这几条今天的事件交给模型判断，避免 Context 无限膨胀
MAX_CANDIDATES = 10
MAX_TAGS = 5


async def today_candidates(db: AsyncSession, user_id: str, limit: int = MAX_CANDIDATES) -> list[Event]:
    """今天的事件（source=user），最近被补充的排在前面。"""
    stmt = (
        select(Event)
        .where(Event.user_id == user_id, Event.source == SOURCE_USER, Event.occurred_on == today_local())
        .order_by(func.coalesce(Event.last_at, Event.recorded_at).desc(), Event.id.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


def render_candidates(items: list[Event]) -> str:
    """给模型看的候选清单——带上 id（它要回填 merge_event_id）与时间点。"""
    if not items:
        return "【今天已有的事件】\n（今天还没有事件，这次输入会是新的一条。）"

    lines = []
    for e in items:
        at = e.last_at or e.recorded_at
        tags = "、".join(e.tags or []) or "无"
        lines.append(f"- id={e.id}  最近记于 {at:%H:%M}  [{e.type}]  标签：{tags}  内容：{e.content}")
    return "【今天已有的事件】\n" + "\n".join(lines)


def clean_tags(raw) -> list[str]:
    """标签清洗：去 #、去空白、去重、限长限量（模型爱加 # 和重复项）。"""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        s = str(item).strip().lstrip("#").strip()
        if not s or len(s) > 12 or s in out:
            continue
        out.append(s)
        if len(out) >= MAX_TAGS:
            break
    return out


async def apply(
    db: AsyncSession,
    user: User,
    *,
    content: str,
    etype: str,
    entities: dict | None,
    tags: list[str],
    merge_id: str | None,
    candidates: list[Event],
) -> tuple[Event, bool]:
    """按模型的决定落库：命中候选就合并，否则新建。返回 (事件, 是否合并)。

    合并是**整体替换**而不是追加：模型给的 content/entities/tags 就是合并后的完整版本。
    这样同一条事件被补充多少次，结果都是确定的，不依赖补充的先后顺序。
    """
    now = now_local()
    target = next((e for e in candidates if e.id == merge_id), None) if merge_id else None

    if target is not None:
        target.type = etype
        target.content = content
        if entities:
            target.entities = entities
        if tags:
            target.tags = tags
        target.last_at = now
        target.merged_count = (target.merged_count or 1) + 1
        return target, True

    event = Event(
        user_id=user.id,
        source=SOURCE_USER,
        type=etype,
        content=content,
        entities=entities or None,
        tags=tags or None,
        occurred_on=today_local(),
        recorded_at=now,
        last_at=now,
        merged_count=1,
    )
    db.add(event)
    await db.flush()
    return event, False
