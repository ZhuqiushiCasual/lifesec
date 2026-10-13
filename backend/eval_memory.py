"""记忆评测 —— 离线回放，**不调模型**（设计文档 4.6）。

四项指标里三项可以在这里零成本跑出来：

  ① 档命中率 / 精确率   拿历史对话重放，看"该命中的档有没有命中"
  ② 记忆开销与分块占比  现场组装一次 Context，统计各 Block 的字符数与占比
  ③ staleness 率        画像各节多久没更新过了

刻意不调模型：回放要能天天跑、免费、而且结果可复现。
只看准确率不够——业界 benchmark 的评测框架也是"准确率 + token 消耗 + 延迟"一起看。

用法：
    cd backend && python eval_memory.py                  # 跑全部离线指标
    python eval_memory.py --rebuild-index                # 从 events 重建索引卡（派生产物）
    python eval_memory.py --merge-tags                   # 问模型要标签归并建议并写入别名表
    python eval_memory.py --limit 200                    # 回放最近 N 轮
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import async_session  # noqa: E402
from app.models.event import Event  # noqa: E402
from app.models.message import ROLE_ME, Message  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.deps import DEFAULT_USER_ID  # noqa: E402
from app.services.memory import context as ctx_builder  # noqa: E402
from app.services.memory import library  # noqa: E402
from app.services.memory import profile as mem_profile  # noqa: E402
from app.utils import now_local  # noqa: E402

# 中文口径：1 个中文字符 ≈ 0.6 token（官方文档给的估算值，英文是 1 字符 ≈ 0.3）
TOKENS_PER_CN_CHAR = 0.6


async def _user(db) -> User:
    return (await db.execute(select(User).where(User.id == DEFAULT_USER_ID))).scalar_one()


async def _rows(db, user_id: str, limit: int) -> list[dict]:
    """回放序列：每条用户消息 + 它归入的事件身上的标签（作为"标准答案"）。"""
    msgs = (
        await db.execute(
            select(Message.content, Message.created_at, Message.ref_event_id)
            .where(Message.user_id == user_id, Message.role == ROLE_ME)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
    ).all()
    msgs = list(reversed(msgs))

    ids = [m[2] for m in msgs if m[2]]
    tag_map: dict[str, list[str]] = {}
    if ids:
        ev_rows = (await db.execute(select(Event.id, Event.tags).where(Event.id.in_(ids)))).all()
        for eid, tags in ev_rows:
            tag_map[eid] = [str(t).strip().lstrip("#") for t in (tags or [])]

    return [
        {"content": content, "at": at, "expected": tag_map.get(eid or "", [])}
        for content, at, eid in msgs
    ]


async def eval_hits(db, user_id: str, rows: list[dict]) -> None:
    """档命中率 / 精确率。这是"不上向量库"这个决定能不能站住的关键指标。"""
    print("\n[1] 档命中率 / 精确率（离线回放，不调模型）")
    card = await library.card_rows(db, user_id, limit=500)
    all_tags = [r.tag for r in card]
    if not all_tags:
        print("  索引卡为空（还没有带标签的事件）——先跑 --rebuild-index")
        return

    inter_p = inter_l = tot_p = tot_l = 0
    tot_expected = 0
    literal_only_precision: list[float] = []
    evaluated = 0

    for i, row in enumerate(rows):
        expected = set(row["expected"])
        if not expected:
            continue
        content = row["content"] or ""
        hot: list[str] = []
        for prev in rows[max(0, i - 3): i]:
            hot.extend(prev["expected"])

        picked = await library.match(db, user_id, content, hot)
        literal = [t for t in all_tags if t and t.lower() in content.lower()]

        inter_p += len(set(picked) & expected)
        inter_l += len(set(literal) & expected)
        tot_p += len(picked)
        tot_l += len(literal)
        tot_expected += len(expected)
        if literal:
            literal_only_precision.append(len(set(literal) & expected) / len(literal))
        evaluated += 1

    if not evaluated:
        print("  没有可评测的样本（需要「消息 → 事件 → 标签」都齐全的对话）")
        return

    def pct(a: int, b: int) -> str:
        return f"{(100.0 * a / b):.1f}%" if b else "—"

    print(f"  样本 {evaluated} 条（只有带标签的用户消息参与）")
    print(f"  含兜底的实际加载：精确率 {pct(inter_p, tot_p)}  召回率 {pct(inter_p, tot_expected)}")
    print(f"  仅字面命中     ：精确率 {pct(inter_l, tot_l)}  召回率 {pct(inter_l, tot_expected)}")
    if literal_only_precision:
        avg = sum(literal_only_precision) / len(literal_only_precision)
        print(f"  字面命中的单次精确率均值：{avg:.2f}（{len(literal_only_precision)} 次有字面命中）")
    print("  判读：字面这一路的精确率应当接近 1.0 —— 这就是「索引优先」的立足点；")
    print("        召回率低于 50% 才考虑引入轻量向量检索（见设计文档 3.4 的触发条件）。")


async def report_blocks(db, user: User, rows: list[dict]) -> None:
    """记忆开销与分块占比：现场组装一次 Context 看各块占多少。"""
    print("\n[2] 记忆开销与分块占比（现场组装，不调模型）")
    probe = rows[-1]["content"] if rows else "今天怎么样"
    ctx = await ctx_builder.build(db, user, probe)

    total_chars = sum(len(v) for v in ctx.blocks.values())
    print(f"  探针输入：{probe[:30]}")
    print(f"  {'Block':<12}{'字符':>8}{'≈token':>10}   占比")
    for key, text in ctx.blocks.items():
        if not text:
            continue
        share = 100.0 * len(text) / total_chars if total_chars else 0
        print(f"  {key:<12}{len(text):>8}{int(len(text) * TOKENS_PER_CN_CHAR):>10}   {share:5.1f}%")
    est = int(total_chars * TOKENS_PER_CN_CHAR)
    print(f"  {'合计':<12}{total_chars:>8}{est:>10}")
    print(f"  命中档：{ctx.hit_tags or '（无）'}")
    print(f"  上限：画像 ≤{settings.portrait_char_limit} 字、目录 ≤{settings.index_max_lines} 行、"
          f"每次命中 ≤{settings.hit_max_tags} 档；记忆块占 input 的比例目标 <60%。")


async def report_staleness(db, user_id: str) -> None:
    """staleness 率：画像里哪些节太久没更新过（目标 <10%）。"""
    print("\n[3] 画像 staleness（哪些节太久没动过）")
    row = await mem_profile.get(db, user_id)
    if row is None:
        print("  还没有画像")
        return
    sources = dict(row.sources or {})
    now = now_local()
    stale = 0
    for key in mem_profile.SECTION_KEYS:
        body = (row.sections or {}).get(key) or ""
        if not body:
            print(f"  {mem_profile.SECTION_LABELS[key]:<8}（空）")
            continue
        meta = sources.get(key) or {}
        stamp = meta.get("updated_at")
        try:
            days = (now - datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")).days if stamp else None
        except ValueError:
            days = None
        flag = ""
        if days is None:
            flag = "（无时间戳）"
        elif days > 60:
            flag, stale = " ← 超过 60 天没更新", stale + 1
        print(f"  {mem_profile.SECTION_LABELS[key]:<8}{len(body):>5} 字 · {days if days is not None else '?'} 天前 {flag}")
    filled = sum(1 for k in mem_profile.SECTION_KEYS if (row.sections or {}).get(k))
    rate = 100.0 * stale / filled if filled else 0
    print(f"  v{row.version} · 变更摘要：{row.summary or '—'}")
    print(f"  staleness 率：{rate:.0f}%（{stale}/{filled}），目标 <10%")


async def rebuild_index_cmd(db, user_id: str) -> None:
    print("\n[*] 重建索引卡（索引卡是派生产物，可从 events 重建）")
    tags = await library.rebuild_index(db, user_id)
    rows = await library.card_rows(db, user_id)
    print(f"  标签 {tags} 个，索引卡 {len(rows)} 行")
    for r in rows[:15]:
        when = f"{r.last_at:%m-%d}" if r.last_at else "—"
        print(f"  #{r.tag}  {r.count} 条 · 最近 {when} → {r.digest or '（待生成摘要）'}")


async def merge_tags_cmd(db, user_id: str) -> None:
    print("\n[*] 标签归并（软归一 ②③ 层：只写别名，不合并事件）")
    applied = await library.merge_tags(db, user_id)
    if not applied:
        print("  没有建议（模型未生效，或确实没有同义标签）")
        return
    for item in applied:
        print(f"  {item['canonical']} ← {'、'.join(item['aliases'])}")


async def main() -> None:
    ap = argparse.ArgumentParser(description="selfsec 记忆评测（离线回放）")
    ap.add_argument("--limit", type=int, default=200, help="回放最近 N 轮用户消息")
    ap.add_argument("--rebuild-index", action="store_true", help="从 events 重建索引卡")
    ap.add_argument("--merge-tags", action="store_true", help="要标签归并建议并应用")
    args = ap.parse_args()

    print(f"数据库：{settings.database_url}")
    print(f"模型：  {settings.openai_model}    Key 已配置：{'是' if settings.openai_api_key else '否（离线模式）'}")

    async with async_session() as db:
        user = await _user(db)
        if user is None:
            print("没有锚点用户，先启动一次服务")
            return

        if args.rebuild_index:
            await rebuild_index_cmd(db, user.id)
        if args.merge_tags:
            await merge_tags_cmd(db, user.id)
        if args.rebuild_index or args.merge_tags:
            # 只做运维动作时不再跑评测
            if len(sys.argv) == 1:
                pass
            return

        rows = await _rows(db, user.id, args.limit)
        print(f"回放样本：{len(rows)} 条用户消息")
        await eval_hits(db, user.id, rows)
        await report_blocks(db, user, rows)
        await report_staleness(db, user.id)
        print("\n提示：模糊指标（画像遵守率）需要人工抽检，见设计文档 4.6 的「每周 30 分钟」。")


if __name__ == "__main__":
    asyncio.run(main())
