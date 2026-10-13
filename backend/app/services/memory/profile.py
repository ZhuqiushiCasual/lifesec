"""4.1 长期画像 ·「总结意识」。

画像回答的是"你是谁"，馆藏（library.py）回答的是"你做过什么"。
它是慢变量：不在每次对话里塞原始记录，而是定期把事件压成一段「关于你的话」，
之后每次组装 Context 都注入这一段（Block A，常驻）。

**分 5 节**（见 3.1）：identity / style / avoid / current / insight。
各节半衰期不同——身份以年计、正在做的事以周计——分开存才能只重算变了的那节。

触发（三个时钟里的第二个）：
  轮次   新增用户消息 ≥ PORTRAIT_USER_TURNS（默认 20）
  定时   距上次 > PORTRAIT_HOURS 且 新增事件 ≥ PORTRAIT_MIN_NEW_EVENTS（AND，不是无条件）
  手动   POST /api/memory/refresh / 夜间调度 / 问卷初始化

**防漂移**（这是初版设计里最大的技术缺陷，四条一起上）：
  ① 没有新增就不重算（定时那个分支是 AND 条件）
  ② 把上一版画像作为输入，要求"没有新依据不要改写"
  ③ 输出变更摘要 + 存版本历史，可回溯
  ④ 变更摘要作为 nudge 推给用户（用已有的 messages.kind=nudge）

硬上限：整段画像 ≤ PORTRAIT_CHAR_LIMIT（默认 1500 字符），超了按节截断。
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.event import SOURCE_QUESTIONNAIRE, SOURCE_USER, Event
from app.models.memory import MemoryProfile, ProfileVersion
from app.models.message import KIND_NUDGE, ROLE_ME, ROLE_SECRETARY, Message
from app.services.ai.profile import build_portrait
from app.services.memory import library
from app.utils import now_local

log = logging.getLogger("selfsec.memory")

SECTION_KEYS = ("identity", "style", "avoid", "current", "insight")
SECTION_LABELS = {
    "identity": "身份",
    "style": "沟通与风格",
    "avoid": "回避项",
    "current": "当前进行中",
    "insight": "结论级洞察",
}

MAX_EVENTS = 300        # 喂给画像生成的事件原文上限（单用户很难触及）
PROVENANCE_IDS = 60     # 每节最多记多少个来源事件 id


# ── 读取 ────────────────────────────────────────────────────

async def get(db: AsyncSession, user_id: str) -> MemoryProfile | None:
    return (
        await db.execute(select(MemoryProfile).where(MemoryProfile.user_id == user_id))
    ).scalar_one_or_none()


def sections_of(row: MemoryProfile | None) -> dict[str, str]:
    """取分节内容。老库（只有一段 content）兜底放进 insight，不丢东西。"""
    if row is None:
        return {}
    data = dict(row.sections or {})
    if not data and row.content:
        data = {"insight": row.content.strip()}
    return {k: str(data.get(k) or "").strip() for k in SECTION_KEYS}


def render(sections: dict[str, str]) -> str:
    """分节 → 注入 Context 的文本。空节不占位（省 token）。"""
    lines: list[str] = []
    for key in SECTION_KEYS:
        body = (sections or {}).get(key) or ""
        if body:
            lines.append(f"{SECTION_LABELS[key]}：{body}")
    return "\n".join(lines)


async def text(db: AsyncSession, user_id: str) -> str:
    row = await get(db, user_id)
    if row is None:
        return ""
    rendered = render(sections_of(row))
    return rendered or (row.content or "")


async def versions(db: AsyncSession, user_id: str, limit: int = 10) -> list[ProfileVersion]:
    return list(
        (
            await db.execute(
                select(ProfileVersion)
                .where(ProfileVersion.user_id == user_id)
                .order_by(ProfileVersion.created_at.desc(), ProfileVersion.id.desc())
                .limit(limit)
            )
        ).scalars().all()
    )


# ── 计数与触发判断 ──────────────────────────────────────────

async def count_events(db: AsyncSession, user_id: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(Event)
            .where(Event.user_id == user_id, Event.source.in_((SOURCE_USER, SOURCE_QUESTIONNAIRE)))
        )
    ).scalar_one()


async def count_user_msgs(db: AsyncSession, user_id: str) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Message).where(Message.user_id == user_id, Message.role == ROLE_ME)
        )
    ).scalar_one()


async def should_iterate(db: AsyncSession, user_id: str) -> tuple[bool, str]:
    """该不该重算画像。返回 (是否, 原因)。**没有新增就不重算**——防漂移的第一条。"""
    row = await get(db, user_id)
    total_events = await count_events(db, user_id)
    if total_events == 0:
        return False, ""

    total_msgs = await count_user_msgs(db, user_id)
    new_events = max(0, total_events - (row.event_count or 0)) if row else total_events
    new_turns = max(0, total_msgs - (row.msg_count or 0)) if row else total_msgs

    if row is None:
        return True, "首次生成"

    if new_turns >= settings.portrait_user_turns:
        return True, f"新增 {new_turns} 轮对话"

    hours = (now_local() - (row.updated_at or row.created_at)).total_seconds() / 3600
    if hours >= settings.portrait_hours and new_events >= settings.portrait_min_new_events:
        return True, f"距上次 {hours:.0f} 小时 + {new_events} 条新事件"

    if new_events >= settings.profile_trigger_events:
        return True, f"新增事件 {new_events} 条达到阈值"

    return False, ""


# ── 写入 ────────────────────────────────────────────────────

def enforce_limit(sections: dict[str, str], limit: int | None = None) -> dict[str, str]:
    """硬上限。从"最可以牺牲"的节开始截断：insight → avoid → style → current → identity。"""
    cap = limit or settings.portrait_char_limit
    out = {k: (sections.get(k) or "").strip() for k in SECTION_KEYS}
    if len(render(out)) <= cap:
        return out

    for key in ("insight", "avoid", "style", "current", "identity"):
        overflow = len(render(out)) - cap
        if overflow <= 0:
            break
        cur = out.get(key) or ""
        if not cur:
            continue
        keep = len(cur) - overflow - 1
        out[key] = (cur[:keep].rstrip() + "…") if keep > 0 else ""
    return out


def _line(e: Event) -> str:
    at = f"{e.recorded_at:%Y-%m-%d}" if e.recorded_at else "?"
    tags = " ".join(f"#{t}" for t in (e.tags or []))
    mark = "[初始化问卷] " if e.source == SOURCE_QUESTIONNAIRE else ""
    return f"[{at}] ({e.type}) {mark}{tags} {e.content}".replace("  ", " ")


async def _load_events(db: AsyncSession, user_id: str) -> list[Event]:
    """画像的原料：全部问卷答案 + 最近的用户事件（**读原文**，不是读摘要）。"""
    questionnaire = (
        await db.execute(
            select(Event)
            .where(Event.user_id == user_id, Event.source == SOURCE_QUESTIONNAIRE)
            .order_by(Event.recorded_at.asc())
        )
    ).scalars().all()

    recent = (
        await db.execute(
            select(Event)
            .where(Event.user_id == user_id, Event.source == SOURCE_USER)
            .order_by(Event.recorded_at.desc())
            .limit(MAX_EVENTS)
        )
    ).scalars().all()

    return list(questionnaire) + list(reversed(recent))


async def _notify(db: AsyncSession, user_id: str, summary: str) -> None:
    """用已有的 kind=nudge 把变更摘要推给用户——"它对我的理解变了"要看得见。"""
    if not summary or summary.strip() in ("", "无变更"):
        return
    db.add(
        Message(
            user_id=user_id,
            role=ROLE_SECRETARY,
            kind=KIND_NUDGE,
            content=f"画像更新：{summary.strip()[:120]}",
            card={"kind": "memory", "title": "画像已更新", "lines": [summary.strip()[:200]], "meta": {}},
        )
    )


async def refresh(
    db: AsyncSession,
    user_id: str,
    *,
    force: bool = False,
    reason: str = "manual",
    notify: bool = True,
) -> MemoryProfile | None:
    """重算画像。不满足触发条件且非强制时返回 None（表示这次不刷新）。"""
    if not force:
        ok, why = await should_iterate(db, user_id)
        if not ok:
            return None
        reason = why

    row = await get(db, user_id)
    events = await _load_events(db, user_id)
    if not events:
        return None

    prev = sections_of(row) if row else None
    digests = await library.digest_lines(db, user_id)      # 导航层：有什么
    data = await build_portrait(                             # 结论层：读原文
        prev=prev or None,
        digests=digests,
        event_lines=[_line(e) for e in events],
    )
    if not data:
        return None

    summary = str(data.pop("summary", "") or "无变更")
    new_sections = enforce_limit({k: str(data.get(k) or "") for k in SECTION_KEYS})
    total = await count_events(db, user_id)
    turns = await count_user_msgs(db, user_id)
    prev_sections = prev or {}

    # 没有任何实质变化就不写：避免版本号膨胀，也避免"没新信息却在重写"
    if row is not None and render(new_sections) == render(prev_sections) and summary == "无变更":
        log.info("画像无实质变化，跳过本次写入")
        return row

    # provenance：只更新真的变了的节（记住"这批事件是这一节的依据"）
    now = now_local()
    sources = dict((row.sources if row else {}) or {})
    input_ids = [e.id for e in events][-PROVENANCE_IDS:]
    for key in SECTION_KEYS:
        if new_sections.get(key) != prev_sections.get(key):
            sources[key] = {"event_ids": input_ids, "updated_at": f"{now:%Y-%m-%d %H:%M:%S}"}

    if row is None:
        row = MemoryProfile(user_id=user_id, version=1)
        db.add(row)
    else:
        row.version += 1

    row.sections = new_sections
    row.content = render(new_sections)
    row.sources = sources
    row.summary = summary
    row.event_count = total
    row.msg_count = turns
    row.updated_at = now

    db.add(
        ProfileVersion(
            user_id=user_id,
            version=row.version,
            sections=new_sections,
            text=row.content,
            summary=summary,
            reason=reason[:64],
        )
    )

    if notify:
        await _notify(db, user_id, summary)

    await db.commit()
    await db.refresh(row)
    log.info("画像已迭代到 v%s（%s · 依据 %s 条事件 · %s 字）", row.version, reason, total, len(row.content or ""))
    return row

