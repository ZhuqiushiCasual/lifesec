"""对话接口的核心编排。

    意图路由 → 组装 Context → 生成回应 → 落事件 → 落消息

设计取舍：**全程只有一次 LLM 调用**（在 ai/reply.py 里，顺带完成意图判定与字段抽取）。
路由（route）只做本地能确定的事——判断这条输入是不是在表达情绪，给模型一句提示。
这样既满足"单一入口"，又不会为了路由再花一次调用。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import (
    SOURCE_USER,
    TYPE_FEELING,
    TYPE_FINANCE,
    TYPE_PLAN,
    TYPE_RECORD,
    Event,
)
from app.models.message import KIND_REPLY, Message
from app.models.plan import Plan
from app.models.user import User
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


def _build_card(etype: str, data: dict, event: Event, plan: Plan | None) -> dict | None:
    if plan is not None:
        return {"kind": "plan", "title": plan.title, "lines": ["待办"], "meta": {"plan_id": plan.id}}

    if etype in CARD_TITLE:
        entities = data.get("entities") or {}
        lines = [f"{k}：{v}" for k, v in list(entities.items())[:5]]
        return {"kind": "record", "title": CARD_TITLE[etype], "lines": lines, "meta": {"event_id": event.id}}

    return None  # feeling / chat 不产生卡片


async def handle(db: AsyncSession, user: User, content: str) -> dict:
    """处理一次用户输入，返回 {reply, card, message_id}。"""
    _, hint = route(content)

    # 1. 组装 Context（此时不含本条输入——统计的是"之前"）
    ctx = await ctx_builder.build(db, user, content, hint=hint)

    # 2. 生成回应（唯一一次 LLM 调用）
    data = await ai_reply.generate(ctx.memory_block, ctx.history, content)

    # 3. 落事件
    etype = data["type"] if data["type"] in VALID_TYPES else TYPE_RECORD
    event = Event(
        user_id=user.id,
        source=SOURCE_USER,
        type=etype,
        content=content,
        entities=data.get("entities") or None,
    )
    db.add(event)
    await db.flush()

    # 3b. 命中待办则生成 plan
    plan = None
    if etype == TYPE_PLAN and data.get("title"):
        plan = Plan(user_id=user.id, title=str(data["title"])[:255], ref_event_id=event.id)
        db.add(plan)
        await db.flush()

    # 4. 落消息
    card = _build_card(etype, data, event, plan)
    msg = Message(
        user_id=user.id,
        kind=KIND_REPLY,
        content=data["reply"],
        card=card,
        ref_event_id=event.id,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    # 5. 阈值触发「总结意识」（未达阈值时内部直接返回）
    try:
        await mem_profile.refresh(db, user.id)
    except Exception as e:  # noqa: BLE001 —— 画像刷新失败不影响本次回应
        log.warning("画像阈值刷新失败: %s", e)

    return {"reply": msg.content, "card": card, "message_id": msg.id}
