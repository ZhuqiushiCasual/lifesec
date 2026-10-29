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

v3（画像 + 馆藏）追加覆盖：

  · 初始化问卷：10 题、预览不落库、答案单独存放（不污染"我说过什么"的时间线）
  · 馆藏索引卡是**派生产物**，能从 events 重建；命中规则（字面 / 热集 / 兜底）
  · 迭代的三个时钟 + job_runs 幂等锁（同一周期只跑一次）
  · 画像分节 + provenance + 版本历史 + 硬上限（1500 字）
  · 防漂移：没有新增就不重写画像

v4（约会探店）追加覆盖：

  · 聊天里说「去吃了」→ date_visits 关联 date_menu.id + 当天事件
  · 同店同日补充只更新一条；未知店保留店名快照；计划中的饭局不落记录

用法：cd backend && python smoke_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import quote

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
os.environ["WORKBENCH_PASSWORD"] = "smoke-wb"  # 工作台独立密码
os.environ["HERMES_WEBHOOK_URL"] = ""          # 不下发，任务停 queued 由测试手动 claim

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
    from app.database import Base, async_session, engine
    from app.services.date_menu import ensure_seed as ensure_date_menu
    from app.services.deps import ensure_default_user
    from app.services.ingest.sources import ensure_seed as ensure_ingest_sources

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_default_user()
    # ASGITransport 不跑 lifespan，源种子 / 约会菜单种子要手动补
    async with async_session() as db:
        await ensure_date_menu(db)
        await ensure_ingest_sources(db)


async def run() -> None:
    from app.database import async_session
    from app.main import app
    from app.models.message import KIND_USER, ROLE_ME, ROLE_SECRETARY, Message
    from app.models.user import User
    from app.services import records, scheduler
    from app.services.deps import DEFAULT_USER_ID
    from app.utils import now_local, today_local

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

        # ─────────────────────────── v3：画像 + 馆藏 ───────────────────────────
        from sqlalchemy import func  # noqa: PLC0415

        from app.models.event import SOURCE_QUESTIONNAIRE, Event as EventModel  # noqa: PLC0415
        from app.models.job import JobRun  # noqa: PLC0415
        from app.services.memory import lifecycle, library  # noqa: PLC0415
        from app.services.memory import profile as mp  # noqa: PLC0415

        print("\n[11] 初始化问卷（冷启动：10 题 → 预览 → 确认）")
        r = await c.get("/api/onboarding/questions")
        qs = r.json().get("questions", [])
        check("GET /api/onboarding/questions 200", r.status_code == 200)
        check("恰好 10 题（多了没人做）", len(qs) == 10, f"{len(qs)} 题")
        check("每题都标注产出画像的哪一节",
              all(q.get("section") in set(mp.SECTION_KEYS) for q in qs))
        check("每题都写了为什么问（hint 或选项）", all(q.get("hint") or q.get("choices") for q in qs))

        answers = {
            "identity_what": "在职，做 AI 应用",
            "goal_year": "年内把 selfsec 做完",
            "style_conclusion": "先给结论，再给理由",
            "style_decide": "数据与清单",
            "energy": "一个人待着",
            "stress": "先做最要紧的",
            "avoid": "别说「我理解你的感受」这种话",
            "hobby": "水下摄影",
            "rhythm": "晚睡",
            "address": "叫我老竹",
        }
        r = await c.post("/api/onboarding/preview", json={"answers": answers})
        check("POST /api/onboarding/preview 200", r.status_code == 200, r.text[:160])
        preview = r.json()
        check("预览是分节结构", set(preview.get("sections", {})) == set(mp.SECTION_KEYS))
        again = (await c.post("/api/onboarding/preview", json={"answers": answers})).json()
        check("预览不调模型，所以可重复（两次结果一致）", preview["text"] == again["text"])
        async with async_session() as db:
            n0 = (await db.execute(
                select(func.count()).select_from(EventModel).where(EventModel.source == SOURCE_QUESTIONNAIRE)
            )).scalar_one()
        check("预览阶段还没落库", n0 == 0, f"{n0} 条")

        r = await c.post("/api/onboarding/apply", json={"answers": answers})
        check("POST /api/onboarding/apply 200", r.status_code == 200, r.text[:160])
        applied = r.json()
        check("确认后有分节画像", bool(applied["sections"].get("avoid")), applied["sections"].get("avoid", ""))
        async with async_session() as db:
            n1 = (await db.execute(
                select(func.count()).select_from(EventModel).where(EventModel.source == SOURCE_QUESTIONNAIRE)
            )).scalar_one()
        check("问卷答案单独存放（source=questionnaire）", n1 == 10, f"{n1} 条")

        # 再 apply 一次（只答一题）：不该把之前答到的节清空 —— 问卷是补充/校正，不是覆盖
        r = await c.post("/api/onboarding/apply", json={"answers": {"hobby": "换了台相机"}})
        merged_sections = r.json()["sections"]
        check("重复提交只更新答到的节，不清空其它节",
              all(merged_sections.get(k) for k in ("identity", "style", "avoid", "current")),
              str({k: bool(v) for k, v in merged_sections.items()}))

        print("\n[12] 问卷不污染时间线（它不算「我说过的话」）")
        stream = (await c.get("/api/messages?limit=200")).json()
        check("问卷标记没混进窗口流",
              all("你现在主要在做什么" not in (m["content"] or "") for m in stream))

        print("\n[13] 馆藏：索引卡是派生产物 + 命中规则")
        async with async_session() as db:
            tags = await library.rebuild_index(db, DEFAULT_USER_ID)
            rows = await library.card_rows(db, DEFAULT_USER_ID)
            check("索引卡有行", bool(rows), f"{tags} 个标签 / {len(rows)} 行")
            check("每行都有条数与最近时间", all(r.count >= 1 and r.last_at for r in rows))
            check("问卷事件不进索引卡（它不是「你做过的事」）",
                  all(r.tag != "画像初始化" for r in rows), str([r.tag for r in rows][:6]))
            check("索引卡带一句话档首摘要或有待生成标记",
                  all(r.digest is not None or r.count >= 1 for r in rows))

            hot = await library.hot_tags(db, DEFAULT_USER_ID)
            picked = await library.match(db, DEFAULT_USER_ID, "今天又去跑步了，膝盖有点酸", hot)
            check("命中规则①：输入里字面出现标签名 → 命中该档", "跑步" in picked, str(picked))
            check("命中数量有上限", len(picked) <= settings.hit_max_tags, f"{len(picked)} 档")
            hits = await library.render_hits(db, DEFAULT_USER_ID, picked)
            check("命中后能展开成「摘要 + 最近原文」", "相关档" in hits and "跑步" in hits)

            await library.add_alias(db, DEFAULT_USER_ID, "慢跑", "跑步")
            await db.commit()
            picked2 = await library.match(db, DEFAULT_USER_ID, "今天慢跑了五公里", hot)
            check("软归一：别名也能命中同一档", "跑步" in picked2, str(picked2))

        print("\n[14] 迭代时钟 + 幂等锁（三个时钟会打架）")
        async with async_session() as db:
            first = await lifecycle.tag_iteration(db, DEFAULT_USER_ID, turns=10)
            second = await lifecycle.tag_iteration(db, DEFAULT_USER_ID, turns=10)
            check("档迭代第一次真正执行", not first.get("skipped"), str(first))
            check("同一周期第二次被幂等锁挡下", second.get("skipped") is True, str(second))
            runs = (await db.execute(select(func.count()).select_from(JobRun))).scalar_one()
            check("job_runs 留了记录（可审计）", runs >= 1, f"{runs} 条")
            tick = await lifecycle.tick(db, DEFAULT_USER_ID)
            check("tick 可安全调用（非边界轮次不会触发迭代）",
                  isinstance(tick, list) and len(tick) == 0, str(tick))

        print("\n[15] 画像：分节 + provenance + 版本历史 + 硬上限")
        r = await c.get("/api/memory")
        mem = r.json()
        check("画像返回分节结构", set(mem.get("sections", {})) == set(mp.SECTION_KEYS))
        check("每节带来源（provenance，能回答「你凭什么这么说」）",
              bool(mem.get("sources")), str(list(mem.get("sources", {}))[:4]))
        check("画像有硬上限（≤1500 字）", len(mem["profile"]) <= settings.portrait_char_limit,
              f"{len(mem['profile'])} 字")
        check("有变更摘要", bool(mem.get("summary")), (mem.get("summary") or "")[:40])

        capped = mp.enforce_limit({k: "字" * 2000 for k in mp.SECTION_KEYS})
        check("超长画像会被按节截断到上限内",
              len(mp.render(capped)) <= settings.portrait_char_limit, f"{len(mp.render(capped))} 字")

        r = await c.get("/api/memory/library")
        lib = r.json()
        check("GET /api/memory/library 200", r.status_code == 200)
        check("馆藏返回索引卡", bool(lib.get("card")), f"{len(lib.get('card', []))} 行")
        check("馆藏返回版本历史", bool(lib.get("versions")),
              f"共 {len(lib.get('versions', []))} 版")

        print("\n[16] 防漂移：没有新增就不重写画像")
        async with async_session() as db:
            before = await mp.get(db, DEFAULT_USER_ID)
            v0 = before.version if before else 0
            ok, why = await mp.should_iterate(db, DEFAULT_USER_ID)
            check("刚迭代过 → 不满足迭代条件", ok is False, f"{ok} / {why}")
            after = await mp.refresh(db, DEFAULT_USER_ID)
            check("非强制刷新在没有新增时不写库",
                  after is None or after.version == v0,
                  f"v{v0} → v{after.version if after else '（未写）'}")

        print("\n[17] 窗口流的 limit 语义：取的是「最近 N 条」，不是「最早的 N 条」")
        # 线上事故（2026-10-15）：攒够 limit 条之后，新记的输入与它的回应都写进了库，
        # 但窗口永远只返回最早的 60 条 → 用户看到的是「我说了，它不再回应」。
        # 这里直接把库造成「已经超过 limit 条」，再断言最新那几条必须出现在窗口里。
        from datetime import timedelta  # noqa: PLC0415

        from app.models.event import SOURCE_USER, Event  # noqa: PLC0415

        base = now_local()
        async with async_session() as db:
            for i in range(70):
                db.add(Message(user_id=DEFAULT_USER_ID, role=ROLE_ME, kind=KIND_USER,
                               content=f"水位测试·第{i}条", created_at=base - timedelta(seconds=200 - i)))
            # 同一时刻的两条，且比上面所有都新：用来验证翻转不会打乱并列项的先后
            tie = base + timedelta(seconds=1)
            db.add(Message(user_id=DEFAULT_USER_ID, role=ROLE_ME, kind=KIND_USER,
                           content="水位测试·并列·我说的", created_at=tie))
            db.add(Message(user_id=DEFAULT_USER_ID, role=ROLE_SECRETARY, kind="reply",
                           content="水位测试·并列·它说的", created_at=tie))
            await db.commit()

        async with async_session() as db:
            newest_ev = (await db.execute(
                select(Event).where(Event.user_id == DEFAULT_USER_ID, Event.source == SOURCE_USER)
                .order_by(Event.recorded_at.desc(), Event.id.desc()).limit(1)
            )).scalar_one()

        window = (await c.get("/api/messages?limit=60")).json()
        check("窗口返回 limit 条", len(window) == 60, f"{len(window)} 条")
        check("窗口是最新的 60 条（最后一条就是刚记的）",
              window[-1]["content"] == "水位测试·并列·它说的", window[-1]["content"])
        check("窗口仍按时间正序",
              all(window[i]["created_at"] <= window[i + 1]["created_at"]
                  for i in range(len(window) - 1)))
        check("最早的那几条被挤出窗口（LIMIT 在新的一头）",
              all(not m["content"].startswith("水位测试·第0条") for m in window))
        tail = [m["role"] for m in window if m["content"].startswith("水位测试·并列")]
        check("最近 60 条里的并列项：我说的排在它说的之前", tail == ["me", "secretary"], str(tail))

        desc = (await c.get("/api/messages?limit=10&order=desc")).json()
        check("回溯（倒序）也是最近 10 条，最新在最上",
              len(desc) == 10 and desc[0]["content"] == "水位测试·并列·它说的", desc[0]["content"])
        cursor = quote(desc[-1]["created_at"], safe="")
        older = (await c.get(f"/api/messages?limit=10&order=desc&before={cursor}")).json()
        check("翻页游标之前才有内容（游标那条不重复出现）",
              bool(older) and all(m["created_at"] < desc[-1]["created_at"] for m in older))

        events = (await c.get("/api/messages?filter=record&limit=3")).json()
        check("事件线也是最近 3 条（最新事件在里面）",
              bool(events) and events[-1]["id"] == newest_ev.id,
              f"{len(events)} 条 / 最新 {events[-1]['content'][:20] if events else ''}")


        # ───────────────────── v2.1：消息推送 / 采集链路 ─────────────────────
        print("\n[18] 采集任务：工作台下发 → Hermes 领取 → 运行记录 → 收尾")
        wb = {"X-Workbench-Password": "smoke-wb"}
        r = await c.get("/api/workbench/check")
        check("工作台无密码被拒", r.status_code == 401, r.text[:120])
        r = await c.get("/api/workbench/check", headers=wb)
        check("工作台密码正确放行", r.status_code == 200, r.text[:120])

        r = await c.get("/api/workbench/sources", headers=wb)
        sources = r.json()
        check("内置五个源已就位",
              {"jiqizhixin", "qbitai", "infoq", "aiera", "github"} <= {s["key"] for s in sources},
              str([s["key"] for s in sources]))
        qbit = next((s for s in sources if s["key"] == "qbitai"), None)
        check("量子位源存在且启用", bool(qbit) and qbit["enabled"])
        if qbit:
            r = await c.patch(f"/api/workbench/sources/{qbit['id']}", json={"enabled": False}, headers=wb)
            check("工作台可停用源", r.status_code == 200 and r.json()["enabled"] is False)
            r = await c.patch(f"/api/workbench/sources/{qbit['id']}", json={"enabled": True}, headers=wb)
            check("工作台可重新启用源", r.status_code == 200 and r.json()["enabled"] is True)

        r = await c.post(
            "/api/workbench/tasks",
            json={"source_keys": ["qbitai"], "trigger": "manual"},
            headers=wb,
        )
        check("工作台创建任务 201", r.status_code == 201, r.text[:160])
        task = r.json()
        task_id = task["id"]
        check("任务初始为 queued（未配 webhook 时不假装下发）", task["status"] == "queued", task["status"])

        r = await c.post(f"/api/ingest/tasks/{task_id}/claim?worker=smoke")
        check("Hermes 可领取任务", r.status_code == 200, r.text[:160])
        claimed = r.json()
        check("领取后任务 running", claimed["task"]["status"] == "running", claimed["task"]["status"])
        check("领取响应带回源配置", any(s["key"] == "qbitai" for s in claimed["sources"]))
        check("领取响应带回回调地址", bool(claimed.get("api_base")))

        r = await c.post(
            f"/api/ingest/tasks/{task_id}/runs",
            json={
                "source_key": "qbitai",
                "source_name": "量子位",
                "status": "succeeded",
                "fetch_level": "L1",
                "items_found": 2,
                "detail": {"elapsed_ms": 1200},
            },
        )
        check("单源运行记录可上报", r.status_code == 200, r.text[:160])
        check("运行记录带层级与条数",
              r.json()["fetch_level"] == "L1" and r.json()["items_found"] == 2)

        print("\n[19] 消息写回：新增 / 幂等 / 更新 / 已读状态保留")
        item_a = {
            "source_key": "qbitai",
            "source_name": "量子位",
            "title": "Anthropic 递交 335 页招股书",
            "summary": "Anthropic 公开招股书，披露财务与风险信息。",
            "detail": "第一段：收入与亏损。\n\n第二段：上市时间表。",
            "impact": "AI 公司上市窗口打开。",
            "category": "tech",
            "topics": ["Anthropic", "IPO"],
            "importance": 5,
            "source_url": "https://example.com/news/a?utm_source=rss&spm=abc",
            "published_at": "2026-10-27 00:06:31",
            "fetch_level": "L1",
        }
        item_b = {
            "source_key": "qbitai",
            "source_name": "量子位",
            "title": "另一个消息（用 url 字段）",
            "summary": "runner 中间格式用 url，写回时也应认。",
            "url": "https://example.com/news/b",
            "category": "tech",
        }
        batch = {"task_id": task_id, "items": [item_a, item_b]}
        r = await c.post("/api/ingest/messages", json=batch)
        check("批量写回 200", r.status_code == 200, r.text[:200])
        out = r.json()
        check("两条都是新建", out["created"] == 2 and out["accepted"] == 2, str(out))
        a_id, b_id = out["event_ids"][0], out["event_ids"][1]

        r = await c.get(f"/api/ingest/messages/{a_id}")
        msg = r.json()
        check("source_url 已规范化（去掉 utm/spm）",
              msg["source_url"] == "https://example.com/news/a", msg["source_url"])
        check("总结 / 详情 / 影响都落了库",
              bool(msg["summary"]) and bool(msg["detail"]) and bool(msg["impact"]))
        check("重要性保留", msg["importance"] == 5)

        r = await c.post("/api/ingest/messages", json=batch)
        out2 = r.json()
        check("同一批重跑 → 幂等跳过，不重复建卡",
              out2["created"] == 0 and out2["skipped"] == 2, str(out2))
        check("幂等命中仍回传已有 event_id", set(out2["event_ids"]) == {a_id, b_id})

        r = await c.patch(f"/api/ingest/messages/{a_id}", json={"status": "hidden"})
        check("消息可隐藏", r.status_code == 200 and r.json()["status"] == "hidden")

        changed = dict(item_a, summary="更新后的总结")
        r = await c.post("/api/ingest/messages", json={"task_id": task_id, "items": [changed]})
        check("内容变化 → 计为 updated", r.json()["updated"] == 1, str(r.json()))
        r = await c.get(f"/api/ingest/messages/{a_id}")
        check("重跑不会把已隐藏打回 new", r.json()["status"] == "hidden", r.json()["status"])
        check("更新后的总结生效", r.json()["summary"] == "更新后的总结")

        print("\n[20] 前台洞察卡：总结 / 详情 / 原文链接")
        r = await c.get("/api/messages?filter=insight&limit=100")
        cards = r.json()
        card = next((m for m in cards if (m.get("card") or {}).get("meta", {}).get("event_id") == a_id), None)
        check("洞察卡出现在窗口流（filter=insight）", card is not None)
        if card:
            meta = card["card"]["meta"]
            check("卡片带总结", meta.get("summary") == "更新后的总结", str(meta.get("summary"))[:40])
            check("卡片带详情（弹层用）", bool(meta.get("detail")))
            check("卡片带原文链接", meta.get("source_url") == "https://example.com/news/a")
            check("卡片带来源徽标", meta.get("source_name") == "量子位")

        index_html = (HERE / "static" / "index.html").read_text(encoding="utf-8")
        app_js = (HERE / "static" / "app.js").read_text(encoding="utf-8")
        check("前台有洞察详情弹层",
              all(k in index_html for k in ("insight-modal", "insight-summary", "insight-detail", "insight-link")))
        check("前台脚本接了详情打开逻辑", "openInsight" in app_js and "data-insight" in app_js)

        print("\n[21] 消息合并 / 删除")
        item_c = {
            "source_key": "qbitai",
            "source_name": "量子位",
            "title": "同一事件 · 转载",
            "summary": "转载版本的总结。",
            "detail": "转载版本的详情。",
            "topics": ["Anthropic"],
            "source_url": "https://example.com/news/c",
        }
        r = await c.post("/api/ingest/messages", json={"items": [item_c]})
        c_id = r.json()["event_ids"][0]
        r = await c.post(
            "/api/ingest/messages/merge",
            json={"primary_id": a_id, "duplicate_ids": [c_id], "title": "合并后的标题"},
        )
        check("合并 200", r.status_code == 200, r.text[:200])
        merged = r.json()
        check("合并后的标题生效", merged["title"] == "合并后的标题", merged["title"])
        check("重复项详情并入主条", "转载版本的详情" in (merged.get("detail") or ""))
        r = await c.get(f"/api/ingest/messages/{c_id}")
        check("重复项已删除", r.status_code == 404, str(r.status_code))

        r = await c.post(
            "/api/ingest/messages/merge",
            json={"primary_id": a_id, "duplicate_ids": ["不存在的-id"]},
        )
        check("合并含不存在的 id → 整次 404（不半途生效）", r.status_code == 404, str(r.status_code))

        r = await c.delete(f"/api/ingest/messages/{b_id}")
        check("消息可删除", r.status_code == 200 and r.json().get("ok"))
        check("删除后再查 404", (await c.get(f"/api/ingest/messages/{b_id}")).status_code == 404)

        print("\n[22] 任务收尾与工作台总览")
        r = await c.post(
            f"/api/ingest/tasks/{task_id}/finish",
            json={"status": "succeeded", "stats": {"written": 2}},
        )
        check("任务可收尾", r.status_code == 200 and r.json()["status"] == "succeeded", r.text[:160])

        r = await c.get(f"/api/ingest/tasks/{task_id}")
        detail = r.json()
        check("任务详情带运行记录", len(detail["runs"]) == 1)
        run = detail["runs"][0]
        check("运行记录被补齐新增/更新条数",
              run["items_new"] >= 2 and run["items_updated"] >= 1,
              f"new={run['items_new']} updated={run['items_updated']}")

        r = await c.get("/api/workbench/overview", headers=wb)
        ov = r.json()
        check("工作台总览 200", r.status_code == 200)
        check("总览能看到任务状态", ov["tasks"].get("succeeded", 0) >= 1, str(ov["tasks"]))
        check("总览能看到消息量", ov["messages"]["total"] >= 1, str(ov["messages"]))
        check("总览返回调度与下发配置", "schedule" in ov["config"] and "dispatch" in ov["config"])

        print("\n[23] 约会探店：聊天里说「去吃了」→ 关联到菜单里的店")
        from datetime import timedelta  # noqa: PLC0415

        from app.models.date_menu import DateMenuItem  # noqa: PLC0415
        from app.models.date_visit import DateVisit  # noqa: PLC0415
        from app.services.ai import reply as ai_reply  # noqa: PLC0415

        today = today_local()
        tomorrow = today + timedelta(days=1)
        async with async_session() as db:
            restaurant = (
                await db.execute(select(DateMenuItem).order_by(DateMenuItem.sort, DateMenuItem.id))
            ).scalars().first()
        check("约会菜单有种子数据", restaurant is not None)

        short = restaurant.name.split("·")[0].strip()
        captured: dict = {}
        original_generate = ai_reply.generate

        async def fake_visit_generate(memory_block, history, user_text, existing_tags=None):
            captured["memory_block"] = memory_block
            return {
                "type": "record",
                "reply": "梅溪徐记的牛肉记下了。",
                "title": None,
                "content": f"今天和她在{short}吃饭，牛肉很嫩。",
                "entities": {"restaurant": restaurant.name},
                "tags": ["约会", "探店"],
                "merge_event_id": None,
                "date_visit": {
                    "is_visit": True,
                    "restaurant_id": restaurant.id,
                    "restaurant_name": restaurant.name,
                    "visited_on": today.isoformat(),
                    "rating": 4.5,
                    "dishes": ["鲜切牛肉", "沙茶酱"],
                    "companion": "她",
                    "occasion": "约会",
                    "review": "牛肉很嫩，清汤锅底不油。",
                },
            }

        ai_reply.generate = fake_visit_generate
        try:
            r = await c.post("/api/chat", json={"content": f"今天和她在{short}吃饭，牛肉很嫩"})
        finally:
            ai_reply.generate = original_generate
        check("探店对话 200", r.status_code == 200, r.text[:200])
        first = r.json()
        check("返回 date_visit_id", bool(first.get("date_visit_id")))
        check("返回关联的餐厅 id", first.get("restaurant_id") == restaurant.id)
        check("Context 注入了约会餐厅清单", restaurant.name in (captured.get("memory_block") or ""))

        async with async_session() as db:
            visit = (
                await db.execute(select(DateVisit).where(DateVisit.id == first.get("date_visit_id")))
            ).scalar_one_or_none()
            check("探店记录落库", visit is not None)
            if visit is not None:
                check("探店记录指向菜单项", visit.restaurant_id == restaurant.id)
                check("店名 / 分店快照落库",
                      visit.restaurant_name == restaurant.name and visit.branch == restaurant.branch)
                check("评分 / 菜名 / 同行人 / 场合落库",
                      visit.rating == 4.5 and visit.dishes == ["鲜切牛肉", "沙茶酱"]
                      and visit.companion == "她" and visit.occasion == "约会")
                check("探店记录挂到事件上", visit.event_id == first.get("event_id"))
                check("就餐日期来自模型", visit.visited_on == today)

        # 同一家店同一天再补充：id 故意给错，靠店名本地兜底；记录只更新不新增
        async def fake_update_generate(memory_block, history, user_text, existing_tags=None):
            return {
                "type": "record",
                "reply": "吊龙也记下了。",
                "title": None,
                "content": f"今天和她在{short}吃饭，牛肉很嫩；吊龙和沙茶酱都不错。",
                "entities": {"restaurant": restaurant.name},
                "tags": ["约会", "探店"],
                "merge_event_id": first.get("event_id"),
                "date_visit": {
                    "is_visit": True,
                    "restaurant_id": "不存在的菜单-id",
                    "restaurant_name": short,
                    "visited_on": today.isoformat(),
                    "rating": 5,
                    "dishes": ["吊龙"],
                    "companion": "她",
                    "occasion": "约会",
                    "review": "牛肉很嫩；吊龙和沙茶酱都不错。",
                },
            }

        ai_reply.generate = fake_update_generate
        try:
            r = await c.post("/api/chat", json={"content": f"还是{short}，吊龙也不错"})
        finally:
            ai_reply.generate = original_generate
        second = r.json()
        check("补充时返回同一条探店记录",
              second.get("date_visit_id") == first.get("date_visit_id"))
        async with async_session() as db:
            visits = (
                await db.execute(select(DateVisit).where(DateVisit.restaurant_id == restaurant.id))
            ).scalars().all()
            check("同店同日只保留一条探店记录", len(visits) == 1, f"{len(visits)} 条")
            if visits:
                v = visits[0]
                check("评价被合并后的完整版本替换", "吊龙" in v.review and "沙茶酱" in v.review)
                check("菜名去重合并", set(v.dishes or []) == {"鲜切牛肉", "沙茶酱", "吊龙"})
                check("评分被更新", v.rating == 5)

        # 菜单里没有的店：保留店名快照，restaurant_id 为空
        async def fake_unknown_generate(memory_block, history, user_text, existing_tags=None):
            return {
                "type": "record",
                "reply": "海底捞记下了。",
                "title": None,
                "content": "晚上和朋友去海底捞，服务不错。",
                "entities": {},
                "tags": ["聚餐"],
                "merge_event_id": None,
                "date_visit": {
                    "is_visit": True,
                    "restaurant_id": "菜单里没有的-id",
                    "restaurant_name": "海底捞",
                    "visited_on": today.isoformat(),
                    "rating": 4,
                    "dishes": [],
                    "companion": "朋友",
                    "occasion": "聚餐",
                    "review": "服务不错。",
                },
            }

        ai_reply.generate = fake_unknown_generate
        try:
            r = await c.post("/api/chat", json={"content": "晚上和朋友去海底捞，服务不错"})
        finally:
            ai_reply.generate = original_generate
        unknown = r.json()
        check("菜单里没有的店也保留记录", bool(unknown.get("date_visit_id")))
        check("对不上菜单时 restaurant_id 为空", unknown.get("restaurant_id") is None)
        async with async_session() as db:
            v = (
                await db.execute(select(DateVisit).where(DateVisit.id == unknown.get("date_visit_id")))
            ).scalar_one_or_none()
            check("未知店保留店名快照",
                  v is not None and v.restaurant_name == "海底捞" and v.restaurant_id is None)

        # 未来日期 / is_visit=false：不落探店记录（普通事件仍然照记）
        async def fake_future_generate(memory_block, history, user_text, existing_tags=None):
            return {
                "type": "plan",
                "reply": "周六去吃记下了。",
                "title": "周六去吃饭",
                "content": "周六想去吃一家店。",
                "entities": {},
                "tags": ["计划"],
                "merge_event_id": None,
                "date_visit": {
                    "is_visit": True,
                    "restaurant_id": None,
                    "restaurant_name": "周六的店",
                    "visited_on": tomorrow.isoformat(),
                    "rating": None,
                    "dishes": [],
                    "companion": "她",
                    "occasion": "约会",
                    "review": None,
                },
            }

        ai_reply.generate = fake_future_generate
        try:
            r = await c.post("/api/chat", json={"content": "周六想去吃一家店"})
        finally:
            ai_reply.generate = original_generate
        future = r.json()
        check("计划中的饭局不落探店记录", future.get("date_visit_id") is None)

        async def fake_not_visit_generate(memory_block, history, user_text, existing_tags=None):
            return {
                "type": "record",
                "reply": "记下了。",
                "title": None,
                "content": user_text,
                "entities": {},
                "tags": [],
                "merge_event_id": None,
                "date_visit": {
                    "is_visit": False,
                    "restaurant_id": restaurant.id,
                    "restaurant_name": restaurant.name,
                    "visited_on": today.isoformat(),
                    "rating": None,
                    "dishes": [],
                    "companion": None,
                    "occasion": None,
                    "review": None,
                },
            }

        ai_reply.generate = fake_not_visit_generate
        try:
            r = await c.post("/api/chat", json={"content": f"下次想吃{short}"})
        finally:
            ai_reply.generate = original_generate
        check("is_visit=false 不落探店记录", r.json().get("date_visit_id") is None)

        if settings.date_admin_password:
            r = await c.get(
                f"/api/date/admin/visits?restaurant_id={restaurant.id}",
                headers={"X-Date-Password": settings.date_admin_password},
            )
            check("后台按店查询探店记录 200", r.status_code == 200, r.text[:200])
            rows = r.json()
            check("后台返回这家店的探店记录",
                  len(rows) == 1 and rows[0]["restaurant_id"] == restaurant.id, str(rows[:1]))
            if rows:
                check("后台记录带合并后的评价", "吊龙" in rows[0]["review"])
        else:
            note("未配置 DATE_ADMIN_PASSWORD", "跳过后台探店查询")


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
