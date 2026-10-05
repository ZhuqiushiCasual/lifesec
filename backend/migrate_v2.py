"""把 v1 的数据搬到 v2 结构（一次性、幂等，SQLite / MySQL 都能跑）。

v1：每条用户消息 = 一条 events(source=user)；messages 只放秘书说的话。
v2：messages 放窗口里的**全部**消息（role=me/secretary）；
    events 只放**事件**（以后同一天的重复 / 补充会自动合并进来）。

做的事：
  1. messages 加 role 列（已有就跳过），旧行标成 secretary
  2. events 加 occurred_on / tags / last_at / merged_count（已有就跳过）并回填
  3. 若窗口里还没有「我说的」消息：把 events(source=user) 一条一条搬进
     messages(role=me)，并指向它自己那条事件

**刻意不做跨消息合并**：v1 每行是模型当时判定的"一条记录"，哪几条属于同一件事的信息
已经没了；按天机械合并会把「跑步」和「想念」揉成一条（线上真实数据就是这样）。
合并是给**以后**的新输入用的——迁移完的历史事件照样在"今天已有的事件"候选里，
新消息该并进哪条，由模型判断。

用法：cd backend && python migrate_v2.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from sqlalchemy import func, inspect, select, text  # noqa: E402

from app.database import async_session, engine  # noqa: E402
from app.models.event import SOURCE_USER, Event  # noqa: E402
from app.models.message import KIND_USER, ROLE_ME, Message  # noqa: E402
from app.utils import now_local  # noqa: E402

MYSQL = engine.dialect.name == "mysql"
JSON_TYPE = "JSON" if MYSQL else "TEXT"
DT_TYPE = "DATETIME(6)" if MYSQL else "DATETIME"


async def _columns(table: str) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.run_sync(lambda c: inspect(c).get_columns(table))
    return {r["name"] for r in rows}


async def _counts() -> dict:
    """注意：v1 的库还没有 role 列，所以这一步必须先看列存不存在——
    否则统计自己就会先把迁移脚本干崩。"""
    has_role = "role" in await _columns("messages")
    async with async_session() as db:
        out = {}
        out["events_all"] = (await db.execute(select(func.count()).select_from(Event))).scalar_one()
        out["events_user"] = (
            await db.execute(select(func.count()).select_from(Event).where(Event.source == SOURCE_USER))
        ).scalar_one()
        out["messages_all"] = (await db.execute(select(func.count()).select_from(Message))).scalar_one()
        if has_role:
            roles = (await db.execute(select(Message.role, func.count()).group_by(Message.role))).all()
            for role, n in roles:
                out[f"messages_{role}"] = n
        return out


async def migrate_schema() -> None:
    msg_cols = await _columns("messages")
    ev_cols = await _columns("events")

    stmts: list[str] = []
    if "role" not in msg_cols:
        stmts.append("ALTER TABLE messages ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'secretary'")
    if "occurred_on" not in ev_cols:
        stmts.append("ALTER TABLE events ADD COLUMN occurred_on DATE")
    if "tags" not in ev_cols:
        stmts.append(f"ALTER TABLE events ADD COLUMN tags {JSON_TYPE}")
    if "last_at" not in ev_cols:
        stmts.append(f"ALTER TABLE events ADD COLUMN last_at {DT_TYPE}")
    if "merged_count" not in ev_cols:
        stmts.append("ALTER TABLE events ADD COLUMN merged_count INTEGER NOT NULL DEFAULT 1")

    if not stmts:
        print("  表和列都已经是 v2 结构，跳过 ALTER")
        return

    async with engine.begin() as conn:
        for s in stmts:
            print(f"  [ALTER] {s}")
            await conn.execute(text(s))

    # 回填：老的 events 行没有这些值
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE events SET last_at = recorded_at WHERE last_at IS NULL"))
        await conn.execute(text("UPDATE events SET occurred_on = DATE(recorded_at) WHERE occurred_on IS NULL"))
        await conn.execute(text("UPDATE events SET merged_count = 1 WHERE merged_count IS NULL"))
    print("  已回填 occurred_on / last_at / merged_count")


async def migrate_data() -> None:
    async with async_session() as db:
        has_me = (
            await db.execute(select(func.count()).select_from(Message).where(Message.role == ROLE_ME))
        ).scalar_one()
        if has_me:
            print("  messages 里已经有「我说的」消息，跳过数据搬迁")
            return

        rows = (
            await db.execute(
                select(Event).where(Event.source == SOURCE_USER).order_by(Event.recorded_at.asc())
            )
        ).scalars().all()
        if not rows:
            print("  没有用户事件需要搬迁")
            return

        for e in rows:
            db.add(
                Message(
                    user_id=e.user_id,
                    role=ROLE_ME,
                    kind=KIND_USER,
                    content=e.content,
                    ref_event_id=e.id,
                    created_at=e.recorded_at,
                )
            )
            e.occurred_on = e.recorded_at.date() if e.recorded_at else e.occurred_on
            e.last_at = e.recorded_at
            e.merged_count = 1

        await db.commit()
        print(f"  搬迁 {len(rows)} 条原话进 messages(role=me)；历史事件一条对一条，不做跨消息合并")


async def main() -> None:
    print(f"数据库：{engine.dialect.name}  迁移开始 {now_local():%Y-%m-%d %H:%M:%S}")
    before = await _counts()
    print(f"  迁移前：{before}")

    print("\n[1/2] 表结构")
    await migrate_schema()
    print("\n[2/2] 数据")
    await migrate_data()

    after = await _counts()
    print(f"\n  迁移后：{after}")
    print("\n完成。窗口渲染现在只读 messages；events 只剩「事件」+ 外部洞察。")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
