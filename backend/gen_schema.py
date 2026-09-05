"""从 SQLAlchemy 模型生成 MySQL 建表 SQL（供 docker-compose 首次初始化使用）。

用法：cd backend && python gen_schema.py
输出：docker-init/01-schema.sql（mysql 容器首次启动时自动执行，仅空数据卷时跑一次）

之所以需要它：mock_data.sql 只有 INSERT，而 mysql 容器的初始化脚本
（/docker-entrypoint-initdb.d）运行时应用还没启动过、表尚不存在，
因此必须先把模型对应的 DDL 生成出来一起灌入。
改了 app/models/ 后请重新运行本脚本。
"""

from pathlib import Path

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.database import Base
from app.models import digest, event, finance, insight, user  # noqa: F401 – 注册模型

OUT = Path(__file__).resolve().parent / "docker-init" / "01-schema.sql"


def main() -> None:
    dialect = mysql.dialect()
    parts = [
        "-- 本文件由 backend/gen_schema.py 自动生成，请勿手改；改模型后重新生成",
        "CREATE DATABASE IF NOT EXISTS life_secretary;",
        "USE life_secretary;",
        "",
    ]
    for table in Base.metadata.sorted_tables:
        parts.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            parts.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
        parts.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"[OK] {len(Base.metadata.tables)} tables -> {OUT}")


if __name__ == "__main__":
    main()
