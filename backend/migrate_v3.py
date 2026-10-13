"""把 v2 的库升到 v3 结构（一次性、幂等，SQLite / MySQL 都能跑）。

v3 做的事：记忆从「一段画像 + 一堆事件」变成 **画像（分节）+ 馆藏（索引卡）**。

表结构：
  1. memory_profile 加 sections / sources / summary / msg_count（已有就跳过）
  2. 新建 tag_index（索引卡）、tag_aliases（标签别名）、job_runs（迭代幂等锁）、
     profile_versions（画像版本历史）—— 走 create_all，只建缺失的表

数据：
  3. 老库的 content 是一整段画像，搬进 sections.insight（结论级洞察），不丢
  4. msg_count 置 0 —— 下一次迭代（轮次 / 定时 / 手动）会按新结构重新生成分节画像

用法：cd backend && python migrate_v3.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from sqlalchemy import func, inspect, select, text  # noqa: E402

from app.database import Base, async_session, engine  # noqa: E402
from app.models.memory import MemoryProfile  # noqa: E402
from app.utils import now_local  # noqa: E402

MYSQL = engine.dialect.name == "mysql"
JSON_TYPE = "JSON" if MYSQL else "TEXT"


async def _columns(table: str) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.run_sync(lambda c: inspect(c).get_columns(table))
    return {r["name"] for r in rows}


async def _tables() -> set[str]:
    async with engine.connect() as conn:
        return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))


async def migrate_schema() -> None:
    mp_cols = await _columns("memory_profile")
    stmts: list[str] = []
    if "sections" not in mp_cols:
        stmts.append(f"ALTER TABLE memory_profile ADD COLUMN sections {JSON_TYPE}")
    if "sources" not in mp_cols:
        stmts.append(f"ALTER TABLE memory_profile ADD COLUMN sources {JSON_TYPE}")
    if "summary" not in mp_cols:
        stmts.append("ALTER TABLE memory_profile ADD COLUMN summary TEXT")
    if "msg_count" not in mp_cols:
        stmts.append("ALTER TABLE memory_profile ADD COLUMN msg_count INTEGER NOT NULL DEFAULT 0")

    if stmts:
        async with engine.begin() as conn:
            for s in stmts:
                print(f"  [ALTER] {s}")
                await conn.execute(text(s))
    else:
        print("  memory_profile 已是 v3 结构，跳过 ALTER")

    # 新表：create_all 只建缺失的表，不会动已有表
    import app.models  # noqa: F401 —— 注册全部模型

    before = await _tables()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    after = await _tables()
    created = sorted(after - before)
    print(f"  [CREATE] 新建表：{created or '（无，已存在）'}")


async def migrate_data() -> None:
    """老的整段画像搬进 sections.insight；msg_count 归零，等下一次迭代重生成。"""
    async with async_session() as db:
        row = (await db.execute(select(MemoryProfile))).scalars().first()
        if row is None:
            print("  没有画像行，跳过数据搬迁")
            return

        if row.sections:
            print("  sections 已有内容，跳过数据搬迁")
        elif row.content:
            row.sections = {"insight": row.content.strip()}
            row.sources = {"insight": {"event_ids": [], "updated_at": None, "note": "migrate_v3 从旧 content 搬入"}}
            print(f"  旧画像（{len(row.content)} 字）已搬进 sections.insight，等待下次迭代重生成")
        else:
            print("  画像为空，跳过")

        row.msg_count = 0
        await db.commit()

        total = (await db.execute(select(func.count()).select_from(MemoryProfile))).scalar_one()
        print(f"  memory_profile 共 {total} 行，已处理")


async def main() -> None:
    print(f"数据库：{engine.dialect.name}  迁移开始 {now_local():%Y-%m-%d %H:%M:%S}")

    print("\n[1/2] 表结构")
    await migrate_schema()
    print("\n[2/2] 数据")
    await migrate_data()

    print("\n完成。记忆层现在是：画像（分节）+ 馆藏（索引卡）+ 迭代锁。")
    print("提示：索引卡是派生产物，重建用 `python eval_memory.py --rebuild-index`。")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
