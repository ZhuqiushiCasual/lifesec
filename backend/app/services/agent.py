"""对话接口的核心编排。

    意图路由 → 组装 Context（五个 Block）→ 生成回应 + 归档决定
             → 落窗口（我说的原话）→ 合并/新建事件 → 落待办 → 落回应
             → 记忆迭代时钟（档迭代 / 画像迭代，幂等）

回应与归档由同一次生成完成：意图判定、字段抽取、标签生成、
以及「并入今天哪条事件」本来就是同一个理解的不同侧面，拆开会让模型重复理解同一句话，
也会出现"回应说合并了、归档却新建了一条"这种自相矛盾。
route() 只做本地能确定的事（判断这条输入是不是在表达情绪），不额外调用模型。

记忆侧的迭代（档摘要 / 画像）不在这条路径里，它由 lifecycle 的三个时钟驱动。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import TYPE_FEELING, TYPE_FINANCE, TYPE_PLAN, TYPE_RECORD, Event
from app.models.message import KIND_REPLY, KIND_USER, ROLE_ME, ROLE_SECRETARY, Message
from app.models.plan import Plan
from app.models.user import User
from app.services import date_visits, fitness, records
from app.services.ai import reply as ai_reply
from app.services.memory import context as ctx_builder
from app.services.memory import library as mem_library
from app.services.memory import lifecycle

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


def _build_card(
    etype: str,
    event: Event,
    plan: Plan | None,
    merged: bool,
    workout=None,
    workout_lines: list[str] | None = None,
) -> dict | None:
    """卡片是窗口里唯一的结构化输出——它把「并到哪儿了、贴了什么标签」露出来。"""
    tags = event.tags or []

    if workout is not None:
        return {
            "kind": "workout",
            "title": workout.title or "训练",
            "lines": list(workout_lines or []),
            "meta": {
                "event_id": event.id,
                "workout_id": workout.id,
                "tags": tags,
                "place": workout.place,
                "duration_min": workout.duration_min,
                "merged": merged,
            },
        }

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

    # 2. 生成回应 + 归档决定
    #    已有标签清单一并给它 —— 标签的"软归一"：优先复用已有写法，
    #    否则同义不同名会把同一档裂成两半（设计文档 4.5）
    existing = await mem_library.existing_tags(db, user.id)
    data = await ai_reply.generate(ctx.memory_block, ctx.history, content, existing_tags=existing)

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
    await db.flush()

    # 4a. 如果这句话是在讲一顿已经发生的饭 / 会面，落一条挂到餐厅上的探店记录。
    #     判定来自同一次生成（date_visit.is_visit），这里只校验 id、清洗字段、去重。
    visit = await date_visits.apply(
        db,
        user,
        event,
        data.get("date_visit"),
        content=content,
        restaurants=ctx.restaurants,
    )

    # 4a2. 如果这句话是在讲一次已经发生的训练，落 workouts / workout_sets。
    #      判定同样来自这次生成（workout.is_workout），这里只校验、匹配动作、展开组数。
    workout, workout_lines = await fitness.apply(
        db, user, event, data.get("workout"), content=content
    )

    # 4b. 命中待办则生成 plan
    plan = None
    if etype == TYPE_PLAN and data.get("title"):
        plan = Plan(
            user_id=user.id,
            title=str(data["title"])[:255],
            ref_event_id=event.id,
            kind="todo",
            source="chat",
        )
        db.add(plan)
        await db.flush()

    # 5. 它的回应：挂在同一条事件上，卡片带标签与合并信息
    card = _build_card(etype, event, plan, merged, workout, workout_lines)
    if card is not None and visit is not None:
        # 只放进 meta，不改变卡面文案：前台怎么呈现探店记录还没定
        card["meta"]["date_visit"] = {
            "id": visit.id,
            "restaurant_id": visit.restaurant_id,
            "restaurant_name": visit.restaurant_name,
            "visited_on": visit.visited_on.isoformat(),
            "rating": visit.rating,
        }
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

    # 6. 记忆迭代时钟（每 10 轮档迭代 / 每 20 轮画像迭代；每日兜底在调度器里）
    #    幂等由 job_runs 保证；没到条件时内部直接返回
    try:
        await lifecycle.tick(db, user.id)
    except Exception as e:  # noqa: BLE001 —— 迭代失败不影响本次回应
        log.warning("记忆迭代失败: %s", e)

    return {
        "reply": msg.content,
        "card": card,
        "message_id": msg.id,
        "event_id": event.id,
        "merged": merged,
        "date_visit_id": visit.id if visit is not None else None,
        "restaurant_id": visit.restaurant_id if visit is not None else None,
        "workout_id": workout.id if workout is not None else None,
    }
