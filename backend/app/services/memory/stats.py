"""4.2 事实与统计 —— 聚合 SQL / 对比 SQL / 全量历史。

**这一层不过 LLM。** 它回答的是"多少次""比上周多吗"这类确定性问题，
用 SQL 直接算，又快又不会说谎。

它是「比较档」回应的数据来源：
    确认档  "记下了"
    比较档  "这周第三次，比上周多"   ← 这一层提供
    追问档  "上次你说要跑，跑了吗"   ← 4.1 画像 + 4.4 会话
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SOURCE_USER, Event
from app.utils import now_local

TYPE_LABELS = {
    "record": "记录",
    "plan": "待办",
    "finance": "记账",
    "feeling": "心情",
    "insight": "洞察",
}


async def collect(db: AsyncSession, user_id: str, days: int = 7) -> dict:
    """本周 / 上周的对比统计 + 按类型分布 + 连续记录天数。只统计用户自己产生的。"""
    now = now_local()
    week_start = now - timedelta(days=days)
    last_week_start = now - timedelta(days=days * 2)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    base = [Event.user_id == user_id, Event.source == SOURCE_USER]

    async def count_between(start, end=None):
        cond = [*base, Event.recorded_at >= start]
        if end is not None:
            cond.append(Event.recorded_at < end)
        return (await db.execute(select(func.count()).select_from(Event).where(*cond))).scalar_one()

    week_total = await count_between(week_start)
    last_week_total = await count_between(last_week_start, week_start)
    today_total = await count_between(day_start)

    rows = await db.execute(
        select(Event.type, func.count())
        .where(*base, Event.recorded_at >= week_start)
        .group_by(Event.type)
        .order_by(func.count().desc())
    )
    by_type = {t: c for t, c in rows.all()}

    # 连续记录天数：取最近 60 天的活跃日期，从今天往前数
    date_rows = await db.execute(
        select(func.date(Event.recorded_at))
        .where(*base, Event.recorded_at >= now - timedelta(days=60))
        .group_by(func.date(Event.recorded_at))
    )
    active = {str(r[0]) for r in date_rows.all()}
    streak, cursor = 0, now.date()
    while str(cursor) in active:
        streak += 1
        cursor -= timedelta(days=1)

    return {
        "week_total": week_total,
        "last_week_total": last_week_total,
        "today_total": today_total,
        "by_type": by_type,
        "streak_days": streak,
    }


def render(s: dict) -> str:
    """把统计压成一句话——这是注入 Context 的形式，也是「比较档」的原话。"""
    if s["week_total"] == 0 and s["last_week_total"] == 0:
        return "还没有任何记录。"

    delta = s["week_total"] - s["last_week_total"]
    if delta > 0:
        cmp_text = f"比上周多 {delta} 条"
    elif delta < 0:
        cmp_text = f"比上周少 {abs(delta)} 条"
    else:
        cmp_text = "和上周持平"

    parts = [f"本周 {s['week_total']} 条，{cmp_text}"]

    if s["by_type"]:
        top = "、".join(f"{TYPE_LABELS.get(k, k)} {v}" for k, v in list(s["by_type"].items())[:3])
        parts.append(f"其中 {top}")

    if s["streak_days"] > 1:
        parts.append(f"已连续记录 {s['streak_days']} 天")

    return "；".join(parts) + "。"
