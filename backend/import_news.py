"""
将 *_news_*.json（如 ai_news / finance_news）导入 MySQL insights 表。

用法:
    python import_news.py                                 # 自动匹配最新的 *_news_*.json
    python import_news.py ../ai_news_2026-06-23.json      # 指定 JSON 文件

依赖:
    pip install asyncmy
"""

import asyncio
import glob
import json
import os
import sys
import uuid
from datetime import datetime
from urllib.parse import urlparse

import asyncmy

# ── 从项目配置导入数据库连接 ──────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.config import settings


def parse_db_url(url: str) -> dict:
    """解析 mysql+asyncmy://user:pass@host:port/db 为连接参数"""
    parsed = urlparse(url)
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": parsed.username,
        "password": parsed.password,
        "database": parsed.path.lstrip("/"),
    }


async def import_news(json_path: str):
    """读取 JSON 并写入 insights 表（INSERT ... ON DUPLICATE KEY UPDATE，按 title 去重）"""
    with open(json_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    print(f"读取到 {len(records)} 条记录: {json_path}")

    db = parse_db_url(settings.database_url)
    conn = await asyncmy.connect(**db, charset="utf8mb4")

    insert_sql = """
        INSERT INTO insights
            (id, user_id, title, summary, impact, category, topics, importance,
             source_url, source_name, published_at, created_at)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE
            summary      = VALUES(summary),
            impact       = VALUES(impact),
            topics       = VALUES(topics),
            importance   = VALUES(importance),
            source_url   = VALUES(source_url),
            source_name  = VALUES(source_name),
            published_at = VALUES(published_at)
    """

    inserted = 0
    async with conn.cursor() as cur:
        for r in records:
            published_at = None
            if r.get("published_at"):
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        published_at = datetime.strptime(r["published_at"], fmt)
                        break
                    except ValueError:
                        continue

            await cur.execute(insert_sql, (
                str(uuid.uuid4()),
                "u0010000-0000-4000-8000-000000000001",
                r["title"],
                r["summary"],
                r.get("impact"),
                r["category"],
                json.dumps(r.get("topics", []), ensure_ascii=False),
                r.get("importance"),
                r.get("source_url"),
                r.get("source_name"),
                published_at,
            ))
            inserted += 1

    await conn.commit()
    conn.close()
    print(f"完成: {inserted} 条已写入 insights 表.")


def find_latest_json() -> str | None:
    """自动查找最新的 *_news_*.json（当前目录 & 上级目录）"""
    patterns = ["*_news_*.json", "../*_news_*.json"]
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    files = sorted(set(files), reverse=True)
    return files[0] if files else None


if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        path = find_latest_json()
        if not path:
            print("错误: 未找到 *_news_*.json 文件，请手动指定路径。")
            print("用法: python import_news.py <json文件路径>")
            sys.exit(1)

    if not os.path.exists(path):
        print(f"错误: 文件不存在 - {path}")
        sys.exit(1)

    asyncio.run(import_news(path))
