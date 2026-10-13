"""③ Context 组装 —— 把记忆层拼成模型能读的 Context。

对应设计文档 4.2 的五个 Block，**顺序就是缓存策略**：

    Block A  画像（Portrait）      全量 · 分 5 节 · ≤1500 字符   稳定（天级）
    Block B  馆藏目录（索引卡）     一行一个标签，只有指针不展开    稳定（天级）
    —— 统计 / 洞察 ——              半稳定（天 / 周级）
    Block C  近 N 轮用户提问        只取我说的 + 时间锚 + 主题      只追加（轮级）
    Block D  命中档                 命中标签的摘要 + 最近几条原文    **每轮都变**
    Block E  今天的事件候选         供本轮合并判定用               当天内变

为什么要这么排：前缀缓存按"从头开始的最长相同前缀"命中。
**越稳定的块放越前面、每轮都会变的检索块（D）放最末** ——
一个易变块放前面，会让它后面的全部内容（对话历史是大头）一起失效。

组装全部在本地完成：不引入检索模型、不引入向量库，只是 SQL 聚合与字符串匹配。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.user import User
from app.services import records
from app.services.memory import insights, library, profile, session, stats

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
    # 分块留档：既方便排查"模型到底看到了什么"，也是评测（eval_memory.py）的输入
    blocks: dict[str, str] = field(default_factory=dict)
    hit_tags: list[str] = field(default_factory=list)

    @property
    def block_sizes(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.blocks.items() if v}


async def build(db: AsyncSession, user: User, content: str, *, hint: str = "") -> Context:
    """一次组装 = 若干次本地查询。没有任何额外的模型调用。"""
    profile_text = await profile.text(db, user.id)                  # Block A
    card = await library.card_rows(db, user.id)                     # Block B
    stat_data = await stats.collect(db, user.id)
    insight_items = await insights.recent(db, user.id)
    turns = await session.user_turns(db, user.id)                   # Block C

    hot = await library.hot_tags(db, user.id)                       # 命中规则 ②
    hit_tags = await library.match(db, user.id, content, hot)        # 命中规则 ①②③
    hits = await library.render_hits(db, user.id, hit_tags)         # Block D

    candidates = await records.today_candidates(db, user.id)         # Block E（此时不含本条输入）

    blocks: dict[str, str] = {}

    if profile_text:
        blocks["A_画像"] = f"【画像】（关于你，稳定，不要复述）\n{profile_text}"

    card_text = library.render_card(card)
    if card_text:
        blocks["B_馆藏目录"] = card_text

    # 统计与洞察：半稳定，放在目录之后、会话之前
    stat_text = stats.render(stat_data)
    if stat_text:
        blocks["B2_统计"] = f"【本周状态】\n{stat_text}"
    insight_text = insights.render(insight_items)
    if insight_text:
        blocks["B3_洞察"] = insight_text

    turns_text = session.render_user_turns(turns)
    if turns_text:
        blocks["C_近N轮"] = turns_text        # 只追加，缓存友好

    if hits:
        blocks["D_命中档"] = hits             # 每轮都变 → 放最末

    blocks["E_今天候选"] = records.render_candidates(candidates)

    if hint:
        blocks["Z_路由提示"] = f"【本次路由提示】\n{hint}"

    return Context(
        memory_block="\n\n".join(blocks.values()),
        history=await session.as_history(db, user.id),
        candidates=candidates,
        user=content,
        profile=profile_text,
        stats=stat_data,
        blocks=blocks,
        hit_tags=hit_tags,
    )
