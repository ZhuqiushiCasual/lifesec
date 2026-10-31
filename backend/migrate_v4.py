"""v3 → v4 迁移：plans 扩展 + 训练 / 出门玩新表（幂等）。

- 新表（exercises / workouts / workout_sets / outing_spots）由 create_all 建。
- plans 加可空字段：kind / scheduled_on / place / ref_type / ref_id / meta / source。
- SQLite 与 MySQL 都用 ADD COLUMN；已存在的列跳过。

用法：
    cd backend
    python migrate_v4.py
"""

import asyncio

from sqlalchemy import inspect, text

import app.models  # noqa: F401 —— 注册全部模型
from app.database import Base, engine

PLAN_COLUMNS = [
    ("kind", "ALTER TABLE plans ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'todo'"),
    ("scheduled_on", "ALTER TABLE plans ADD COLUMN scheduled_on DATE NULL"),
    ("place", "ALTER TABLE plans ADD COLUMN place VARCHAR(120) NOT NULL DEFAULT ''"),
    ("ref_type", "ALTER TABLE plans ADD COLUMN ref_type VARCHAR(16) NULL"),
    ("ref_id", "ALTER TABLE plans ADD COLUMN ref_id VARCHAR(36) NULL"),
    ("meta", "ALTER TABLE plans ADD COLUMN meta JSON NULL"),
    ("source", "ALTER TABLE plans ADD COLUMN source VARCHAR(16) NOT NULL DEFAULT 'chat'"),
]


def _plan_columns(sync_conn):
    inspector = inspect(sync_conn)
    if "plans" not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns("plans")}


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        existing = await conn.run_sync(_plan_columns)
        added = 0
        for name, ddl in PLAN_COLUMNS:
            if name in existing:
                continue
            await conn.execute(text(ddl))
            print(f"added plans.{name}")
            added += 1
        if added == 0:
            print("plans already up to date")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
