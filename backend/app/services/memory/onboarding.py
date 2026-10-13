"""初始化：10 题问卷 + 一份可审阅提案（设计文档 4.1）。

冷启动两步：
  1. 用户填 10 道题——**每题都必须能直接产出一句画像**，收集了不用的题不要出
  2. 先把"我看到的是这样"给他看，确认后才落盘（抄 Claude Code /init 的提案机制）

两个刻意的设计决定：

  · **答案不写成 events(source=user)**。问卷答案是画像的种子，不是"他说过的话"；
    混进时间线会污染"我今天做了什么"。所以单独用 source=questionnaire 存放，
    它不进索引卡、不参与命中，只作为画像生成的输入。

  · **草稿不用模型**：每题 → 一句画像的映射是确定的，所以预览免费、可重复、无延迟。
    真正的润色留给第一次画像迭代（可以随时再跑）。

关于 MBTI：不问四字母。它的重测信度很差（同一个人隔几周重测，结果常变），
学术共识是大五（OCEAN）。但 MBTI 有个真实的产品优势——用户熟悉、愿意填。
折中做法：用 MBTI 式的**情境二选一**（第 5、6 题），一样好填，但不承诺一个站不住的结论。
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SOURCE_QUESTIONNAIRE, TYPE_RECORD, Event
from app.models.memory import MemoryProfile, ProfileVersion
from app.models.user import User
from app.services.memory import profile as mem_profile
from app.utils import now_local, today_local

log = logging.getLogger("selfsec.onboarding")

SECTION_TAG = {
    "identity": "画像初始化",
    "style": "画像初始化",
    "avoid": "画像初始化",
    "current": "画像初始化",
    "insight": "画像初始化",
}

# 10 题：题目 / 形式 / 产出哪一节 / 为什么问
QUESTIONS: list[dict] = [
    {
        "id": "identity_what",
        "section": "identity",
        "kind": "choice_text",
        "question": "你现在主要在做什么？",
        "choices": ["在职", "学生", "自由职业 / 创业", "暂时没在做事"],
        "hint": "补一句：行业 / 公司性质 / 在做的事（不必写全称）",
    },
    {
        "id": "goal_year",
        "section": "current",
        "kind": "text",
        "question": "未来一年，你最想完成的一件事是什么？",
        "hint": "写你真正在推进的那件，不是年度计划模板",
    },
    {
        "id": "style_conclusion",
        "section": "style",
        "kind": "choice",
        "question": "我给你回话，你更希望哪种？",
        "choices": ["先给结论，再给理由", "先铺垫，再给结论"],
    },
    {
        "id": "style_decide",
        "section": "style",
        "kind": "choice",
        "question": "做决定时你更信哪个？",
        "choices": ["数据与清单", "直觉与感觉"],
    },
    {
        "id": "energy",
        "section": "insight",
        "kind": "choice",
        "question": "忙完一天，你更想怎么回血？",
        "choices": ["一个人待着", "找人聊聊"],
    },
    {
        "id": "stress",
        "section": "insight",
        "kind": "choice",
        "question": "事情堆起来的时候，你更容易？",
        "choices": ["先做最容易的", "先做最要紧的", "干脆先不做"],
    },
    {
        "id": "avoid",
        "section": "avoid",
        "kind": "text",
        "question": "什么样的话、或者什么做法，会让你立刻烦？",
        "hint": "这一题价值最高：直接决定它以后不说什么",
    },
    {
        "id": "hobby",
        "section": "insight",
        "kind": "text",
        "question": "最近让你上头的一件事、或者一个东西？",
        "hint": "写具体的那个：器材、游戏、一本书、一门手艺都行",
    },
    {
        "id": "rhythm",
        "section": "current",
        "kind": "choice",
        "question": "你的作息大致是？",
        "choices": ["早睡早起", "晚睡", "不规律"],
        "hint": "这条也会用来定问候与夜间重算的时间",
    },
    {
        "id": "address",
        "section": "identity",
        "kind": "text",
        "question": "希望我怎么称呼你？用一句话描述你希望我眼里的你。",
        "hint": "这句话会成为画像的开头",
    },
]

_ORDER = ("identity", "style", "avoid", "current", "insight")


def questions() -> list[dict]:
    return QUESTIONS


def _pick(answers: dict, key: str) -> str:
    return str(answers.get(key) or "").strip()


def draft_sections(answers: dict) -> dict[str, str]:
    """把答案确定性地翻译成 5 节草稿（不调模型）。"""
    who = _pick(answers, "identity_what")
    address = _pick(answers, "address")
    goal = _pick(answers, "goal_year")
    conclusion = _pick(answers, "style_conclusion")
    decide = _pick(answers, "style_decide")
    avoid = _pick(answers, "avoid")
    energy = _pick(answers, "energy")
    stress = _pick(answers, "stress")
    hobby = _pick(answers, "hobby")
    rhythm = _pick(answers, "rhythm")

    identity = "；".join(x for x in [
        f"他希望被这样看：{address}" if address else "",
        f"目前状态：{who}" if who else "",
    ] if x)
    style = "；".join(x for x in [conclusion, f"做决定偏{'数据' if '数据' in decide else '直觉'}" if decide else ""] if x)
    current = "；".join(x for x in [goal, f"作息：{rhythm}" if rhythm else ""] if x)
    insight = "；".join(
        x
        for x in [
            f"社交回血方式：{energy}" if energy else "",
            f"压力下的第一反应：{stress}" if stress else "",
            f"最近上头：{hobby}" if hobby else "",
        ]
        if x
    )

    return {"identity": identity, "style": style, "avoid": avoid, "current": current, "insight": insight}


async def answered(db: AsyncSession, user_id: str) -> bool:
    rows = (
        await db.execute(
            select(Event.id).where(Event.user_id == user_id, Event.source == SOURCE_QUESTIONNAIRE).limit(1)
        )
    ).first()
    return rows is not None


async def preview(db: AsyncSession, user: User, answers: dict) -> dict:
    """可审阅提案：先看"我看到的是这样"，确认后再落盘。"""
    sections = draft_sections(answers)
    return {"sections": sections, "text": mem_profile.render(sections)}


async def apply(db: AsyncSession, user: User, answers: dict) -> dict:
    """落库：问卷事件（source=questionnaire）+ 第一版画像（v1，不推 nudge）。"""
    now = now_local()
    sections = draft_sections(answers)

    for q in QUESTIONS:
        raw = _pick(answers, q["id"])
        if not raw:
            continue
        db.add(
            Event(
                user_id=user.id,
                source=SOURCE_QUESTIONNAIRE,
                type=TYPE_RECORD,
                content=f"{q['question']} → {raw}",
                tags=[SECTION_TAG.get(q["section"], "画像初始化")],
                entities={"question_id": q["id"], "section": q["section"], "answer": raw},
                occurred_on=today_local(),
                recorded_at=now,
                last_at=now,
                merged_count=1,
            )
        )

    filled = {k: v for k, v in sections.items() if v}
    cap = mem_profile.enforce_limit({k: sections.get(k, "") for k in _ORDER})

    row = await mem_profile.get(db, user.id)
    if row is None:
        row = MemoryProfile(user_id=user.id, version=1)
        db.add(row)
        version = 1
    else:
        row.version += 1
        version = row.version

    row.sections = cap
    row.content = mem_profile.render(cap)
    row.sources = {k: {"event_ids": [], "updated_at": f"{now:%Y-%m-%d %H:%M:%S}", "note": "问卷初始化"}
                   for k in filled}
    row.summary = "初始化问卷"
    row.event_count = await mem_profile.count_events(db, user.id)
    row.msg_count = await mem_profile.count_user_msgs(db, user.id)
    row.updated_at = now

    db.add(
        ProfileVersion(
            user_id=user.id, version=version, sections=cap, text=row.content,
            summary="初始化问卷", reason="questionnaire",
        )
    )
    await db.commit()
    await db.refresh(row)
    log.info("问卷初始化完成：v%s，填入 %s 节", version, len(filled))
    return {"ok": True, "version": version, "profile": row.content, "sections": cap}
