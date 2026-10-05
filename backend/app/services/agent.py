"""对话接口的核心编排。

    意图路由 → 组装 Context（含今天的事件候选）→ 生成回应 + 归档决定
             → 落窗口（我说的原话）→ 合并/新建事件 → 落待办 → 落回应

设计取舍：**全程只有一次 LLM 调用**（services/ai/reply.py）。
意图判定、字段抽取、标签生成、以及「并入今天哪条事件」都在这一次里完成——
它们本来就是同一个理解的不同侧面，拆开只会更贵、更容易自相矛盾。
route() 只做本地能确定的事（判断这条输入是不是在表达情绪），不做第二次调用。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import TYPE_FEELING, TYPE_FINANCE, TYPE_PLAN, TYPE_RECORD, Event
from app.models.message import KIND_REPLY, KIND_USER, ROLE_ME, ROLE_SECRETARY, Message
from app.models.plan import Plan
from app.models.user import User
from app.services import records
from app.services.ai import reply as ai_reply
from app.services.memory import context as ctx_builder
from app.services.memory import profile as mem_profile

log = logging.getLogger("selfsec.agent")

VALID_TYPES = {TYPE_RECORD, TYPE_PLAN, TYPE_FINANCE, TYPE_FEELING, "chat"}

# 情绪词：命中即认为这次输入主要是在表达情绪，提示模型优先接住
FEELING_WORDS = (
    "累", "难过", "焦虑", "烦", "压力", "不开心", "失落", "崩溃", "委屈", "孤独",
    "失眠", "想哭", "撑不住", "没意思", "迷茫", "害怕",
)

CARD_TITLE = {
    TYPE_RECORD: "已记录",
    TYPE_PLAN: "待办",
    TYPE_FINANCE: "已记账",
}


def route(content: str) -> tuple[str, str]:
    """本地预路由。返回 (intent, hint)。intent 只用于提示，不是最终类型。"""
    if any(w in content for w in FEELING_WORDS):
        return "feeling", "这条输入像是在表达情绪：先接住，不评价、不建议、不说教。"
    return "record", ""


def _build_card(etype: str, event: Event, plan: Plan | None, merged: bool) -> dict | None:
    """卡片是窗口里唯一的结构化输出——它把「并到哪儿了、贴了什么标签」露出来。"""
    tags = event.tags or []

    if plan is not None:
        return {
            "kind": "plan",
            "title": plan.title,
            "lines": ["待办"],
            "meta": {"plan_id": plan.id, "event_id": event.id, "tags": tags},
        }

    if etype in CARD_TITLE:
        entities = event.entities or {}
        lines = [f"{k}：{v}" for k, v in list(entities.items())[:5]]
        if merged:
            lines.insert(0, f"并入 {event.recorded_at:%H:%M} 那条记录")
        return {
            "kind": "record",
            "title": "已并入今天的记录" if merged else CARD_TITLE[etype],
            "lines": lines,
            "meta": {
                "event_id": event.id,
                "tags": tags,
                "merged": merged,
                "merged_count": event.merged_count,
            },
        }

    return None  # feeling / chat 不产生卡片


async def handle(db: AsyncSession, user: User, content: str) -> dict:
    """处理一次用户输入，返回 {reply, card, message_id, event_id, merged}。"""
    _, hint = route(content)

    # 1. 组装 Context（此时不含本条输入——统计的是"之前"，候选也不含它还没并入的东西）
    ctx = await ctx_builder.build(db, user, content, hint=hint)

    # 2. 生成回应 + 归档决定（唯一一次 LLM 调用）
    data = await ai_reply.generate(ctx.memory_block, ctx.history, content)

    # 3. 落事件：合并进今天已有的那一条，或新建一条
    etype = data["type"] if data["type"] in VALID_TYPES else TYPE_RECORD
    event, merged = await records.apply(
        db,
        user,
        content=data["content"] or content,
        etype=etype,
        entities=data.get("entities") or {},
        tags=records.clean_tags(data.get("tags")),
        merge_id=data.get("merge_event_id"),
        candidates=ctx.candidates,
    )

    # 4. 我说的这条：原样进窗口（时间点 = created_at），指向它归入的事件
    db.add(Message(user_id=user.id, role=ROLE_ME, kind=KIND_USER, content=content, ref_event_id=event.id))

    # 4b. 命中待办则生成 plan
    plan = None
    if etype == TYPE_PLAN and data.get("title"):
        plan = Plan(user_id=user.id, title=str(data["title"])[:255], ref_event_id=event.id)
        db.add(plan)
        await db.flush()

    # 5. 它的回应：挂在同一条事件上，卡片带标签与合并信息
    card = _build_card(etype, event, plan, merged)
    msg = Message(
        user_id=user.id,
        role=ROLE_SECRETARY,
        kind=KIND_REPLY,
        content=data["reply"],
        card=card,
        ref_event_id=event.id,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    # 6. 阈值触发「总结意识」（未达阈值时内部直接返回）
    try:
        await mem_profile.refresh(db, user.id)
    except Exception as e:  # noqa: BLE001 —— 画像刷新失败不影响本次回应
        log.warning("画像阈值刷新失败: %s", e)

    return {"reply": msg.content, "card": card, "message_id": msg.id, "event_id": event.id, "merged": merged}
