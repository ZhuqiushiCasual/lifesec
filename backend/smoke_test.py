"""端到端冒烟测试。

刻意不依赖外部服务：
  · 库用本地 SQLite（写在 smoke_test.db），不会碰 .env 里配置的生产库
  · 调度器关闭，改为手动触发，结果可复现
  · 模型不可用时回应生成会自动降级，所以离线也能跑通全链路

v2 之后重点覆盖：

  · 完整窗口表：一次输入落两条消息（我说的 + 它说的），都指向同一条事件
  · 事件带 **AI 每次生成的标签**
  · 同一天的两条输入会**合并**到同一条事件（模型认定 + 代码侧的确定性校验，两条路都测）
  · 模型给的 merge_event_id 不在候选里时，绝不能改写历史

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

# 默认用本地 SQLite；若外部已指定 DATABASE_URL（例如指向 MySQL 验证方言），则尊重它
if "DATABASE_URL" not in os.environ:
    DB_FILE.unlink(missing_ok=True)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_FILE.as_posix()}"

os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["API_TOKEN"] = ""                   # 关闭鉴权，简化测试
os.environ["PROFILE_TRIGGER_EVENTS"] = "999"   # 避免中途自动刷画像，测试里手动触发

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402
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
    from app.database import async_session
    from app.main import app
    from app.models.message import KIND_USER, ROLE_ME, ROLE_SECRETARY, Message
    from app.models.user import User
    from app.services import records, scheduler
    from app.services.deps import DEFAULT_USER_ID
    from app.utils import now_local

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
        check("返回了 event_id", bool(body.get("event_id")))
        check("今天第一条 → 新建事件而不是合并", body.get("merged") is False)
        first_event = body.get("event_id")
        if body.get("reply") == "记下了。":
            note("模型未生效", "回应走了本地降级（未配置 OPENAI_API_KEY 或调用失败）")
        else:
            check("回应来自真实模型", True, body.get("reply"))
            card = body.get("card") or {}
            tags = (card.get("meta") or {}).get("tags") or []
            check("卡片上带着 AI 生成的标签", bool(tags), f"tags={tags}")
            check("记录卡字段来自事件", (card.get("meta") or {}).get("event_id") == first_event)

        print("\n[3] 同一天的补充：能不能并进同一条事件（模型判定，不硬性失败）")
        r = await c.post("/api/chat", json={"content": "又跑了 30 分钟，今天加起来 70 了"})
        check("POST /api/chat 200", r.status_code == 200)
        second = r.json()
        if second.get("merged") and second.get("event_id") == first_event:
            check("第二条并入了同一条事件", True, f"event_id={first_event}")
            card = second.get("card") or {}
            check("卡片标出了这是补充", bool((card.get("meta") or {}).get("merged")),
                  (card.get("title") or "") + " / " + "，".join(card.get("lines") or []))
        else:
            note("模型这次没合并",
                 "同一次调用里判断，偶发；机制本身由 [7d] 的确定性用例兜底")

        print("\n[4] 对话接口（规划）")
        r = await c.post("/api/chat", json={"content": "明天要交周报，别忘了"})
        check("POST /api/chat 200", r.status_code == 200)
        plan_body = r.json()

        print("\n[5] 待办")
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

        print("\n[6] 洞察线（Hermes 回调）")
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
        check("首次推送被接受", r.json()["accepted"] and not r.json()["deduped"])
        check("生成了洞察消息", bool(r.json()["message_id"]))

        r = await c.post("/api/insights", json=news)
        check("重复推送被幂等去重", r.json().get("deduped") is True)

        print("\n[7] 窗口流（单表：我说的 + 它说的）")
        r = await c.get("/api/messages?limit=200")
        msgs = r.json()
        check("GET /api/messages 200", r.status_code == 200)
        check("流按时间正序",
              all(msgs[i]["created_at"] <= msgs[i + 1]["created_at"] for i in range(len(msgs) - 1)))
        roles = {m["role"] for m in msgs}
        check("两侧都在窗口里", {"me", "secretary"} <= roles, str(roles))
        check("我说的那条原样保留（未被改写）",
              any(m["role"] == "me" and m["content"] == "今天跑了 40 分钟步" for m in msgs))
        kinds = {m["kind"] for m in msgs}
        check("含 reply 与 insight", {"reply", "insight"} <= kinds, str(kinds))

        print("\n[7b] 我说的每条都归到一条事件上（合并后仍可回溯到原始消息）")
        async with async_session() as db:
            me_rows = (await db.execute(select(Message).where(Message.role == ROLE_ME))).scalars().all()
            check("用户消息都带 ref_event_id", bool(me_rows) and all(m.ref_event_id for m in me_rows),
                  f"{len(me_rows)} 条")
            by_event: dict[str, int] = {}
            for m in me_rows:
                by_event[m.ref_event_id] = by_event.get(m.ref_event_id, 0) + 1
            shared = [k for k, v in by_event.items() if v > 1]
            if shared:
                check("多条消息可以指向同一条事件（合并发生了）", True, f"{len(shared)} 条事件被多条消息引用")
            else:
                note("没有多条消息指向同一事件", "模型这次全部新建；机制由 [7d] 兜底验证")

        print("\n[7c] 回溯：事件线（带标签、归属日期、合并次数）")
        r = await c.get("/api/messages?filter=record&order=desc&limit=50")
        events = r.json()
        check("GET 事件线 200", r.status_code == 200)
        check("事件线只返回事件（role=event）", bool(events) and {e["role"] for e in events} == {"event"})
        check("事件带归属日期", all(e["occurred_on"] for e in events))
        tagged = [e for e in events if e["tags"]]
        check("事件带标签", bool(tagged), f"{len(tagged)}/{len(events)} 条带标签")
        if tagged:
            check("标签是自由文本而不是固定枚举",
                  all(isinstance(t, str) and t for e in tagged for t in e["tags"]),
                  str(tagged[0]["tags"]))

        print("\n[7d] 合并的确定性部分（不看模型脸色，直接调 records.apply）")
        async with async_session() as db:
            user = (await db.execute(select(User).where(User.id == DEFAULT_USER_ID))).scalar_one()
            cands = await records.today_candidates(db, user.id)
            check("候选=今天的事件", bool(cands), f"{len(cands)} 条候选")
            base = cands[0]
            before_id, before_count = base.id, base.merged_count

            ev, merged = await records.apply(
                db, user, content="今天跑了 40 分钟，后来又跑了 30 分钟", etype="record",
                entities={"sport": "跑步", "duration": "70分钟"}, tags=["运动", "跑步"],
                merge_id=before_id, candidates=cands,
            )
            await db.commit()
            check("命中候选 → 并进同一条事件", merged and ev.id == before_id)
            check("合并次数 +1", ev.merged_count == before_count + 1, f"{before_count} → {ev.merged_count}")
            check("表述被整体替换", ev.content == "今天跑了 40 分钟，后来又跑了 30 分钟")
            check("标签被更新", list(ev.tags or []) == ["运动", "跑步"])

            ghost, ghost_merged = await records.apply(
                db, user, content="幻觉事件", etype="record", entities={}, tags=[],
                merge_id="根本不存在的事件-id", candidates=cands,
            )
            await db.commit()
            check("候选外的 id → 当作新建（幻觉不改写历史）", not ghost_merged and ghost.id != before_id)
            await db.delete(ghost)
            await db.commit()

        print("\n[7e] 同一秒落库的两条也次序确定（与库的时间精度无关）")
        async with async_session() as db:
            tie = now_local()
            db.add(Message(user_id=DEFAULT_USER_ID, role=ROLE_ME, kind=KIND_USER,
                           content="并列序测试·我说的", created_at=tie))
            db.add(Message(user_id=DEFAULT_USER_ID, role=ROLE_SECRETARY, kind="reply",
                           content="并列序测试·它说的", created_at=tie))
            await db.commit()
        stream_a = [m["id"] for m in (await c.get("/api/messages?limit=200")).json()]
        stream_b = [m["id"] for m in (await c.get("/api/messages?limit=200")).json()]
        check("两次查询次序一致", stream_a == stream_b)
        pair = [m["role"] for m in (await c.get("/api/messages?limit=200")).json()
                if m["content"].startswith("并列序测试")]
        check("同一时刻：我说的排在它说的之前", pair == ["me", "secretary"], str(pair))

        print("\n[8] 内置调度（手动触发）")
        before = len((await c.get("/api/messages?limit=200")).json())
        await scheduler.fire("morning")
        after = (await c.get("/api/messages?limit=200")).json()
        check("问候已写入同一窗口", len(after) == before + 1, f"{before} → {len(after)}")
        check("问候是它说的（role=secretary）", after[-1]["role"] == "secretary", after[-1]["role"])
        check("问候是最新一条且带议程卡",
              after[-1]["kind"] == "greeting" and (after[-1]["card"] or {}).get("kind") == "greeting",
              after[-1]["content"])

        print("\n[9] 记忆层 · 总结意识")
        r = await c.post("/api/memory/refresh")
        check("POST /api/memory/refresh 200", r.status_code == 200, r.text[:200])
        mem = r.json()
        if mem["profile"]:
            check("画像已生成", True,
                  f"v{mem['version']} · 依据 {mem['event_count']} 条事件 · {len(mem['profile'])} 字")
        else:
            note("画像为空", "模型未生效时的预期行为（摘要生成失败会跳过本次刷新）")
        check("GET /api/memory 200", (await c.get("/api/memory")).status_code == 200)

        print("\n[10] 后续对话是否引用记忆")
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
