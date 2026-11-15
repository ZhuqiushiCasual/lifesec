"""v4 → v5 迁移：地点拓扑（幂等）。

- 新表 `places` 由 create_all 建。
- `date_menu` / `outing_spots` 各加一列 `place_id`：拓扑只读 places，
  领域表靠这一列知道自己是谁；`plans.ref_type` 保持不动（计划永远指向业务实体）。
- 跨库都支持 ADD COLUMN；已有的列跳过，可以反复跑。

用法：
    cd backend
    python migrate_v5.py
"""

import asyncio

from sqlalchemy import inspect, text

import app.models  # noqa: F401 —— 注册全部模型
from app.database import Base, engine

COLUMNS = [
    ("date_menu", "place_id", "ALTER TABLE date_menu ADD COLUMN place_id VARCHAR(36) NULL"),
    ("outing_spots", "place_id", "ALTER TABLE outing_spots ADD COLUMN place_id VARCHAR(36) NULL"),
]


def _existing(sync_conn, table: str):
    inspector = inspect(sync_conn)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        added = 0
        for table, column, ddl in COLUMNS:
            if column in await conn.run_sync(_existing, table):
                print(f"{table}.{column} 已存在")
                continue
            await conn.execute(text(ddl))
            print(f"added {table}.{column}")
            added += 1
        if added == 0:
            print("已是最新")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
