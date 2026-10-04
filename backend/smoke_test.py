"""端到端冒烟测试。

刻意不依赖外部服务：
  · 库用本地 SQLite（写在 smoke_test.db），不会碰 .env 里配置的生产库
  · 调度器关闭，改为手动触发，结果可复现
  · 模型不可用时回应生成会自动降级，所以离线也能跑通全链路

用法：cd backend && python smoke_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DB_FILE = HERE / "smoke_test.db"
DB_FILE.unlink(missing_ok=True)

# 必须在导入 app 之前设定（app.config 读取环境变量）
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_FILE.as_posix()}"
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["API_TOKEN"] = ""                   # 关闭鉴权，简化测试
os.environ["PROFILE_TRIGGER_EVENTS"] = "999"   # 避免中途自动刷画像，测试里手动触发

import httpx  # noqa: E402
from app.config import settings  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []
WARN: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def note(name: str, detail: str) -> None:
    WARN.append(name)
    print(f"  [注意] {name}  — {detail}")


async def setup() -> None:
    import app.models  # noqa: F401
    from app.database import Base, engine
    from app.services.deps import ensure_default_user

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_default_user()


async def run() -> None:
    from app.main import app
    from app.services import scheduler

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        print("\n[1] 健康检查")
        r = await c.get("/health")
        check("GET /health 200", r.status_code == 200, r.text)

        print("\n[2] 对话接口（记录）")
        r = await c.post("/api/chat", json={"content": "今天跑了 40 分钟步"})
        check("POST /api/chat 200", r.status_code == 200, r.text[:200])
        body = r.json()
        check("返回了回应", bool(body.get("reply")), f"reply={body.get('reply')!r}")
        check("返回了 message_id", bool(body.get("message_id")))
        if body.get("reply") == "记下了。":
            note("模型未生效", "回应走了本地降级（未配置 OPENAI_API_KEY 或调用失败）")
        else:
            check("回应来自真实模型", True, body.get("reply"))
            check("附了记录卡", (body.get("card") or {}).get("kind") == "record", str(body.get("card")))

        print("\n[3] 对话接口（规划）")
        r = await c.post("/api/chat", json={"content": "明天要交周报，别忘了"})
        check("POST /api/chat 200", r.status_code == 200)
        plan_body = r.json()

        print("\n[4] 待办")
        r = await c.get("/api/plans")
        plans = r.json()
        check("GET /api/plans 200", r.status_code == 200)
        if plans:
            check("识别出待办", True, plans[0]["title"])
            pid = plans[0]["id"]
            r = await c.patch(f"/api/plans/{pid}", json={"status": "done"})
            check("PATCH 勾选待办 200", r.status_code == 200 and r.json()["status"] == "done")
            r = await c.get("/api/plans")
            check("勾选后不在 open 列表", len(r.json()) == 0)
        else:
            note("未识别出待办", f"模型未生效时的预期行为；本次回应={plan_body.get('reply')!r}")

        print("\n[5] 洞察线（Hermes 回调）")
        news = {
            "title": "某公司扩招 Agent 方向工程师",
            "summary": "多家大厂同步开放 Agent 平台岗位，HC 数量环比上升。",
            "impact": "与你的跳槽计划直接相关，值得跟进 JD。",
            "category": "tech",
            "topics": ["招聘", "Agent"],
            "importance": 4,
            "source_url": "https://example.com/news/1",
            "source_name": "示例来源",
        }
        r = await c.post("/api/insights", json=news)
        check("POST /api/insights 200", r.status_code == 200, r.text[:200])
        first = r.json()
        check("首次推送被接受", first["accepted"] and not first["deduped"])
        check("生成了洞察消息", bool(first["message_id"]))

        r = await c.post("/api/insights", json=news)
        check("重复推送被幂等去重", r.json().get("deduped") is True)

        print("\n[6] 窗口流（用户轮 + 秘书轮合并）")
        r = await c.get("/api/messages")
        msgs = r.json()
        check("GET /api/messages 200", r.status_code == 200)
        check("流按时间正序",
              all(msgs[i]["created_at"] <= msgs[i + 1]["created_at"] for i in range(len(msgs) - 1)))
        roles = {m["role"] for m in msgs}
        check("两侧都在窗口里", {"me", "secretary"} <= roles, str(roles))
        kinds = {m["kind"] for m in msgs}
        check("含 reply 与 insight", {"reply", "insight"} <= kinds, str(kinds))
        insight_msgs = [m for m in msgs if m["kind"] == "insight"]
        check("洞察卡已附在消息上", bool(insight_msgs) and insight_msgs[0]["card"]["kind"] == "insight")

        print("\n[7] 内置调度（手动触发）")
        before = len(msgs)
        await scheduler.fire("morning")
        after = (await c.get("/api/messages")).json()
        check("问候已写入同一窗口", len(after) == before + 1, f"{before} → {len(after)}")
        check("问候是最新一条且带议程卡",
              after[-1]["kind"] == "greeting" and (after[-1]["card"] or {}).get("kind") == "greeting",
              after[-1]["content"])

        print("\n[8] 记忆层 · 总结意识")
        r = await c.post("/api/memory/refresh")
        check("POST /api/memory/refresh 200", r.status_code == 200, r.text[:200])
        mem = r.json()
        if mem["profile"]:
            check("画像已生成", True,
                  f"v{mem['version']} · 依据 {mem['event_count']} 条 · {len(mem['profile'])} 字")
        else:
            note("画像为空", "模型未生效时的预期行为（摘要生成失败会跳过本次刷新）")
        check("GET /api/memory 200", (await c.get("/api/memory")).status_code == 200)

        print("\n[9] 后续对话是否引用记忆")
        r = await c.post("/api/chat", json={"content": "今天又跑了 30 分钟"})
        check("第二次记录仍能回应", r.status_code == 200, r.json().get("reply", "")[:60])


async def main() -> None:
    print(f"数据库：{settings.database_url}")
    print(f"模型：  {settings.openai_model}    Key 已配置：{'是' if settings.openai_api_key else '否'}")
    await setup()
    await run()

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)}  失败 {len(FAIL)}  提示 {len(WARN)}")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
    print("=" * 56)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
