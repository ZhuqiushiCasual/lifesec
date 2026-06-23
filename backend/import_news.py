"""
将 *_news_*.json 导入 MySQL insights 表。支持单次导入 / 定时守护模式。

用法:
    python import_news.py                                  # 单次: 自动匹配最新的 *_news_*.json 并导入
    python import_news.py ../ai_news_2026-06-23.json       # 单次: 指定 JSON 文件导入
    python import_news.py --daemon                         # 守护: 每天 07:00 自动研究新闻 → 写 JSON → 入库

依赖:
    pip install asyncmy
"""

import asyncio
import glob
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, date, timedelta
from urllib.parse import urlparse

import asyncmy

# ── 从项目配置导入数据库连接 ──────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.config import settings

# ── opencode 研究新闻的 prompt ───────────────────────────
RESEARCH_PROMPT = """使用anysearch研究今天的金融新闻和AI新闻，总结输出为json格式。

要求:
1. 搜索今天({today})发布的金融(finance)和AI(tech)领域重要新闻
2. 每个类别各找最重要的 5-8 条
3. 每条新闻包含: title、summary、impact(对用户的影响分析)、category(finance或tech)、topics(标签数组)、importance(1-5)、source_url、source_name、published_at
example:每条新闻的 published_at 格式为: %Y-%m-%d %H:%M:%S
        [
          {
            
            "title": "OpenAI 发布 GPT-5.5-Cyber：AI 漏洞发现速度超越人类",
            "summary": "OpenAI ...",
            "impact": "...",
            "category": "tech",
            "topics": ["AI安全"],
            "importance": 5,
            "source_url": "https://...",
            "source_name": "Times Now",
            "published_at": "2026-06-23 08:49:00"
          }
        ]
4. 分别输出为 ai_news_{today}.json 和 finance_news_{today}.json，保存到当前目录"""


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


async def import_news(json_path: str) -> int:
    """读取 JSON 并写入 insights 表，返回写入条数"""
    with open(json_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    print(f"[{datetime.now():%H:%M:%S}] 读取到 {len(records)} 条记录: {json_path}")

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
                r.get("user_id", "u0010000-0000-4000-8000-000000000001"),
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
    print(f"[{datetime.now():%H:%M:%S}] 完成: {inserted} 条已写入 insights 表.")
    return inserted


def find_latest_json(pattern: str = "*_news_*.json") -> str | None:
    """自动查找最新匹配的 JSON（当前目录 & 上级目录）"""
    files = []
    for p in [pattern, f"../{pattern}"]:
        files.extend(glob.glob(p))
    files = sorted(set(files), reverse=True)
    return files[0] if files else None


def find_today_jsons(today: str) -> list[str]:
    """查找今天生成的 *_news_*.json 文件"""
    patterns = [f"*_news_{today}.json", f"../*_news_{today}.json"]
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    return sorted(set(files))


def run_opencode(today: str) -> bool:
    """调用 opencode run 生成当天的新闻 JSON；返回是否成功"""
    prompt = RESEARCH_PROMPT.format(today=today)
    print(f"[{datetime.now():%H:%M:%S}] 开始执行 opencode run ...")
    try:
        result = subprocess.run(
            ["opencode", "run", prompt],
            capture_output=True, text=True,
            timeout=600,  # 10 分钟超时
        )
        if result.returncode != 0:
            print(f"opencode 返回非零: {result.returncode}")
            if result.stderr:
                print(f"stderr: {result.stderr[:500]}")
            return False
        print(f"[{datetime.now():%H:%M:%S}] opencode 执行完成")
        if result.stdout:
            print(result.stdout[:500])
        return True
    except subprocess.TimeoutExpired:
        print("opencode 执行超时 (10min)")
        return False
    except FileNotFoundError:
        print("错误: 找不到 opencode 命令，请确认已安装并在 PATH 中")
        return False


async def daily_job():
    """每日任务: opencode 研究新闻 → 写入 JSON → 导入数据库"""
    today = date.today().isoformat()
    print(f"\n{'='*60}")
    print(f"[{datetime.now():%H:%M:%S}] ⏰ 开始执行每日任务 ({today})")

    # 1. 调用 opencode 生成新闻 JSON
    ok = run_opencode(today)
    if not ok:
        print("opencode 执行失败，跳过入库步骤")
        return

    # 2. 查找生成的 JSON 并入库
    jsons = find_today_jsons(today)
    if not jsons:
        # opencode 可能输出到其他路径，尝试模糊匹配
        jsons = find_today_jsons(today.replace("-", "*"))
        # 还找不到则用最新文件兜底
        if not jsons:
            latest = find_latest_json()
            if latest:
                jsons = [latest]
                print(f"未找到今天({today})的文件，使用最新: {latest}")

    if not jsons:
        print("未找到任何 *_news_*.json 文件")
        return

    total = 0
    for f in jsons:
        n = await import_news(f)
        total += n

    print(f"[{datetime.now():%H:%M:%S}] ✅ 每日任务完成，共入库 {total} 条")


async def daemon():
    """守护进程: 每天 07:00 执行一次 daily_job"""
    print(f"守护模式已启动，每天 07:00 自动执行新闻研究+入库")
    print(f"当前时间: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("按 Ctrl+C 退出\n")

    today_done = None  # 记录今天是否已执行

    while True:
        now = datetime.now()

        # 每天 07:00 ~ 07:01 之间触发，且当天未执行过
        if now.hour == 7 and now.minute == 0 and today_done != now.date():
            today_done = now.date()
            await daily_job()

        # 每 30 秒检查一次
        await asyncio.sleep(30)


# ── CLI ──────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        try:
            asyncio.run(daemon())
        except KeyboardInterrupt:
            print("\n守护模式已退出.")
    else:
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
