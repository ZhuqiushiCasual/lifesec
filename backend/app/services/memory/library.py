"""馆藏 —— 索引卡、分档、命中、标签软归一。

对应设计文档 3.2 / 4.2 / 4.5。三层结构：

    索引卡（常驻）    一行一个标签：标签 · 条数 · 最近时间 · 一句话档首摘要
    分档（按需）      命中该标签时，给它档首摘要 + 最近若干条事件原文
    原文（真相源）    events 表，永不改写

**语义判断被前移到了写入时刻**：给事件打标签就是一次语义归一，
所以检索时退化成精确匹配——这是本项目不需要向量库的根本原因（见 3.4）。

命中规则（本地算，不引检索模型）：
    ① 当前输入字面出现已知标签名或别名
    ② 会话热集：最近几轮在聊的标签（不需要等本轮标签算出来）
    ③ 兜底：按最近时间取几档
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime
from typing import Iterable, Optional, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.event import SOURCE_HERMES, SOURCE_USER, Event
from app.models.library import TagAlias, TagIndex
from app.models.message import ROLE_ME, Message
from app.services.ai import library as ai_library
from app.utils import now_local

log = logging.getLogger("selfsec.library")

# 索引卡只认"用户自己的事"，外部推来的洞察不占目录（它们是 4.3，另走一条线）
INDEX_SOURCES = (SOURCE_USER,)


# ── 标签读取 ────────────────────────────────────────────────

async def existing_tags(db: AsyncSession, user_id: str, limit: int | None = None) -> list[str]:
    """已有标签清单（按条数排序）——软归一：注入 prompt 让模型优先复用。"""
    n = limit or settings.existing_tags_in_prompt
    rows = (
        await db.execute(
            select(TagIndex.tag)
            .where(TagIndex.user_id == user_id)
            .order_by(TagIndex.count.desc(), TagIndex.last_at.desc())
            .limit(n)
        )
    ).scalars().all()
    return list(rows)


async def aliases(db: AsyncSession, user_id: str) -> dict[str, str]:
    rows = (await db.execute(select(TagAlias).where(TagAlias.user_id == user_id))).scalars().all()
    return {r.alias: r.canonical for r in rows}


async def add_alias(db: AsyncSession, user_id: str, alias: str, canonical: str) -> None:
    """记一笔别名映射（不合并事件本身，只让检索时按同一个键聚合）。"""
    alias, canonical = alias.strip().lstrip("#"), canonical.strip().lstrip("#")
    if not alias or not canonical or alias == canonical:
        return
    exists = (
        await db.execute(select(TagAlias).where(TagAlias.user_id == user_id, TagAlias.alias == alias))
    ).scalar_one_or_none()
    if exists:
        exists.canonical = canonical
    else:
        db.add(TagAlias(user_id=user_id, alias=alias, canonical=canonical))


# ── 索引卡（派生产物，可从 events 重建）─────────────────────

async def rebuild_index(db: AsyncSession, user_id: str) -> int:
    """扫描全部事件，重建/更新索引卡的行（条数、最近时间、依据的事件 id）。

    摘要（digest）不在这里重算——它要走 LLM，由 digest_pending 单独处理：
    只有"条数变了"的标签才需要重算摘要（有新增才重写，没新增不动）。
    """
    rows = (
        await db.execute(
            select(Event.id, Event.tags, Event.recorded_at, Event.last_at)
            .where(Event.user_id == user_id, Event.source.in_(INDEX_SOURCES))
            .order_by(Event.recorded_at.asc())
        )
    ).all()

    counts: Counter = Counter()
    last_at: dict[str, datetime] = {}
    members: dict[str, list[str]] = {}

    for eid, tags, recorded_at, last in rows:
        at = last or recorded_at
        for raw in tags or []:
            tag = str(raw).strip().lstrip("#")
            if not tag:
                continue
            counts[tag] += 1
            if tag not in last_at or (at and at > last_at[tag]):
                last_at[tag] = at
            members.setdefault(tag, []).append(eid)

    existing = {
        r.tag: r
        for r in (await db.execute(select(TagIndex).where(TagIndex.user_id == user_id))).scalars().all()
    }

    for tag, n in counts.items():
        row = existing.get(tag)
        if row is None:
            row = TagIndex(user_id=user_id, tag=tag, count=n, last_at=last_at.get(tag))
            row.built_from = json.dumps(members.get(tag, [])[-20:], ensure_ascii=False)
            db.add(row)
        else:
            row.count = n
            row.last_at = last_at.get(tag, row.last_at)
            row.built_from = json.dumps(members.get(tag, [])[-20:], ensure_ascii=False)

    # 标签彻底消失（事件被删）→ 索引卡里的行也删掉
    stale = [t for t in existing if t not in counts]
    for t in stale:
        await db.delete(existing[t])

    await db.commit()
    return len(counts)


async def digest_pending(db: AsyncSession, user_id: str, *, only: Sequence[str] | None = None) -> list[str]:
    """重算「有新增」的标签档首摘要（走 LLM）。返回实际重算的标签。

    这就是"每 10 轮"那个时钟真正做的事——而且**只算有新增的档**，
    不是每次都把所有标签重算一遍（否则成本随标签数线性增长）。
    """
    stmt = select(TagIndex).where(TagIndex.user_id == user_id)
    if only:
        stmt = stmt.where(TagIndex.tag.in_(list(only)))
    rows = (await db.execute(stmt)).scalars().all()

    updated: list[str] = []
    for row in rows:
        if row.count <= (row.digest_count or 0) and row.digest:
            continue  # 没有新增，不动
        events = await _events_of_tag(db, user_id, row.tag, limit=20)
        lines = [f"[{_d(e)}] {e.content}" for e in events]
        digest = await ai_library.summarize_tag(row.tag, lines)
        if not digest:
            continue  # 模型不可用：保留旧摘要，下次再算
        row.digest = digest
        row.digest_count = row.count
        row.built_at = now_local()
        updated.append(row.tag)

    if updated:
        await db.commit()
    return updated


async def card_rows(db: AsyncSession, user_id: str, limit: int | None = None) -> list[TagIndex]:
    """索引卡的行：按条数排，条数相同按最近时间。"""
    n = limit or settings.index_max_lines
    return list(
        (
            await db.execute(
                select(TagIndex)
                .where(TagIndex.user_id == user_id)
                .order_by(TagIndex.count.desc(), TagIndex.last_at.desc())
                .limit(n)
            )
        ).scalars().all()
    )


def render_card(rows: Sequence[TagIndex]) -> str:
    """索引卡 → 注入 Context 的文本（Block B）。一行一个标签，只有指针不展开内容。"""
    if not rows:
        return ""
    lines = []
    for r in rows:
        when = f"{r.last_at:%m-%d}" if r.last_at else "—"
        digest = r.digest or "（还没生成摘要）"
        lines.append(f"#{r.tag}  {r.count} 条 · 最近 {when} → {digest}")
    return "【馆藏目录】先看目录：命中相关标签后再展开细节。\n" + "\n".join(lines)


async def digest_lines(db: AsyncSession, user_id: str, limit: int | None = None) -> list[str]:
    """只要目录行（不带标题）——给画像生成当"导航层"用。

    设计要点：画像的输入里给目录是为了告诉模型"有什么"，
    但结论必须来自事件原文——避免"摘要的摘要"那层误差累积（星型，不是链式）。
    """
    rows = await card_rows(db, user_id, limit)
    out = []
    for r in rows:
        when = f"{r.last_at:%m-%d}" if r.last_at else "—"
        out.append(f"#{r.tag}  {r.count} 条 · 最近 {when} → {r.digest or '（无摘要）'}")
    return out


# ── 命中（本地算，不引检索模型）────────────────────────────

async def hot_tags(db: AsyncSession, user_id: str, turns: int = 3) -> list[str]:
    """会话热集：最近几轮用户在聊什么话题的标签。用于解开"本轮标签还没有"的问题。"""
    recent = (
        await db.execute(
            select(Message.ref_event_id)
            .where(Message.user_id == user_id, Message.role == ROLE_ME, Message.ref_event_id.is_not(None))
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(turns)
        )
    ).scalars().all()
    if not recent:
        return []
    rows = (
        await db.execute(select(Event.tags).where(Event.id.in_(list(recent))))
    ).all()
    out: list[str] = []
    for (tags,) in rows:
        for t in tags or []:
            s = str(t).strip().lstrip("#")
            if s and s not in out:
                out.append(s)
    return out


async def match(
    db: AsyncSession,
    user_id: str,
    content: str,
    hot: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[str]:
    """命中规则 ①②③。返回要展开的标签（按优先级，最多 limit 个）。"""
    n = limit or settings.hit_max_tags
    rows = await card_rows(db, user_id, limit=settings.index_max_lines * 4)
    if not rows:
        return []

    alias_map = await aliases(db, user_id)
    # 别名 → 规范名 的方向：内容里出现别名时，命中的是它归并到的那个标签
    canon_of = {r.tag: r.tag for r in rows}
    for a, c in alias_map.items():
        if c in canon_of:
            canon_of[a] = c

    picked: list[str] = []

    def add(tag: str) -> None:
        if tag in picked or len(picked) >= n:
            return
        picked.append(tag)

    text = (content or "").lower()

    # ① 字面命中：输入里直接出现标签名或别名
    for raw in list(canon_of.keys()):
        if raw and raw.lower() in text:
            add(canon_of[raw])

    # ② 会话热集
    for t in hot or []:
        add(canon_of.get(t, t))

    # ③ 兜底：最近的几档
    if len(picked) < n:
        for r in sorted(rows, key=lambda x: x.last_at or datetime.min, reverse=True):
            add(r.tag)

    return [t for t in picked if any(r.tag == t for r in rows)]


async def render_hits(db: AsyncSession, user_id: str, tags: Sequence[str]) -> str:
    """命中档 → 注入 Context 的文本（Block D）：档首摘要 + 最近几条原文。"""
    if not tags:
        return ""
    limit = settings.hit_max_events
    chunks: list[str] = []
    for tag in tags:
        row = (
            await db.execute(select(TagIndex).where(TagIndex.user_id == user_id, TagIndex.tag == tag))
        ).scalar_one_or_none()
        head = f"  {row.digest}" if row and row.digest else ""
        when = f"{row.last_at:%m-%d}" if row and row.last_at else "—"
        events = await _events_of_tag(db, user_id, tag, limit=limit)
        lines = [f"    - [{_d(e)}] {e.content}" for e in events]
        chunks.append(f"#{tag}（{row.count if row else len(events)} 条 · 最近 {when}）{head}\n" + "\n".join(lines))
    return "【相关档（命中后展开的细节）】\n" + "\n".join(chunks)


# ── 内部工具 ────────────────────────────────────────────────

def _d(e: Event) -> str:
    at = e.last_at or e.recorded_at
    return f"{at:%Y-%m-%d}" if at else "?"


async def _events_of_tag(db: AsyncSession, user_id: str, tag: str, limit: int = 3) -> list[Event]:
    """某标签下的最近若干条事件（tags 是 JSON 数组，各库聚合函数不一样，取回来在 Python 侧筛）。"""
    rows = (
        await db.execute(
            select(Event)
            .where(Event.user_id == user_id, Event.source.in_(INDEX_SOURCES))
            .order_by(func.coalesce(Event.last_at, Event.recorded_at).desc(), Event.id.desc())
            .limit(max(limit * 12, 60))
        )
    ).scalars().all()
    hit = [e for e in rows if tag in [str(t).strip().lstrip("#") for t in (e.tags or [])]]
    return hit[:limit]


async def merge_tags(db: AsyncSession, user_id: str) -> list[dict]:
    """标签归并（② ③ 层）：让模型给建议，然后写入别名表。

    只写别名，**不合并事件本身** —— 检索时按 canonical 聚合，归档结构不动。
    """
    rows = await card_rows(db, user_id, limit=200)
    suggestions = await ai_library.merge_suggestions([(r.tag, r.count) for r in rows])
    applied: list[dict] = []
    for s in suggestions:
        for alias in s["aliases"]:
            await add_alias(db, user_id, alias, s["canonical"])
        applied.append(s)
    if applied:
        await db.commit()
        log.info("标签归并：%s", applied)
    return applied


def tag_counter(events: Iterable[Event]) -> Counter:
    c: Counter = Counter()
    for e in events:
        for t in e.tags or []:
            c[str(t).strip().lstrip("#")] += 1
    return c
