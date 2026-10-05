"""③ Context 组装 —— 把记忆层拼成模型能读的 Context。

对应架构图 ③ 的四块：

    System Prompt      长且稳定：身份 / 核心目的 / 边界
    Memory Block       动态注入：4.1 画像 + 4.2 统计 + 4.3 洞察 + **今天已有的事件（合并候选）**
    当前 User Message  本次输入
    （history）        4.4 会话短期，作为中间轮次

「今天已有的事件」是这次改造新加的一块：模型据此判断这条输入该合并进哪条事件。
一次组装 = 四查 SQL（统计）+ 两查 SQL（画像、洞察）+ 一查 SQL（会话）+ 一查 SQL（候选），
依旧没有额外的 LLM 调用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.user import User
from app.services import records
from app.services.memory import insights, profile, session, stats

# 长且稳定：放在这里，而不是每次对话现编
SYSTEM_PROMPT = """你是"selfsec"，这个人的个人秘书。只服务他一个人。

你的核心目的：让他被回应、被记住，并且不错过重要的外部消息。

边界：
- 你只谈他的生活、他的计划、外部对他的影响。不聊别的，不做通用问答机器人。
- 你不安慰式地陪伴，不说教，不替他做决定。
- 你说的每句话都要短。你的价值在"记得"，不在"能说"。
"""


@dataclass
class Context:
    memory_block: str
    history: list[dict] = field(default_factory=list)
    candidates: list[Event] = field(default_factory=list)   # 今天已有的事件（合并候选）
    user: str = ""
    profile: str = ""
    stats: dict = field(default_factory=dict)


async def build(db: AsyncSession, user: User, content: str, *, hint: str = "") -> Context:
    profile_text = await profile.text(db, user.id)
    stat_data = await stats.collect(db, user.id)
    insight_items = await insights.recent(db, user.id)
    history = await session.as_history(db, user.id)
    candidates = await records.today_candidates(db, user.id)   # 此时不含本条输入

    blocks: list[str] = []

    if profile_text:
        blocks.append(f"【长期画像】\n{profile_text}")
    blocks.append(f"【本周状态】\n{stats.render(stat_data)}")

    insight_text = insights.render(insight_items)
    if insight_text:
        blocks.append(insight_text)

    blocks.append(records.render_candidates(candidates))

    if hint:
        blocks.append(f"【本次路由提示】\n{hint}")

    return Context(
        memory_block="\n\n".join(blocks),
        history=history,
        candidates=candidates,
        user=content,
        profile=profile_text,
        stats=stat_data,
    )
