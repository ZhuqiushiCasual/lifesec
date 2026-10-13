"""馆藏相关的两个 LLM 出口：档首摘要、标签归并建议。

两者都**不是**对话路径上的调用：
  档首摘要  在迭代时钟（每 10 轮 / 夜间）里跑，一次只算"有新增的那些标签"
  归并建议  手动触发（每周或标签数超标时），一次算完全部标签

失败都返回空，由调用方跳过本次，绝不让用户看到报错。
"""

from __future__ import annotations

from app.config import settings
from app.services.ai.client import AIUnavailable, chat_json

DIGEST_SYSTEM = """你在为一个"标签档"写一句话摘要，供个人秘书的目录使用。

他每次对话只会先看到这份目录（一行一个标签），命中之后才会展开这一档的详细内容。
所以摘要要回答的是：**这一档里都是些什么事**。

要求：
1. 40 字以内，一句话，直接陈述，不加标题、不加列表。
2. 写清楚：这一档主要在说什么 + 最值得记的 1-2 个具体点（人名 / 数字 / 名词 / 器材名这类）。
3. 不要评价、不要给建议、不要写"你需要注意"这类话。
4. 只依据给定的记录，不要编造。
5. 用第二人称"你"（例如："你在练半马，膝盖有旧伤"）。

只输出 JSON：{"digest": "一句话摘要"}"""

MERGE_SYSTEM = """你要把一组标签里的**同义项**归并到一起。

输入是标签与各自的条数。你的任务：找出确实指的是同一类东西的标签，给出归并建议。

要求：
1. 只归并**语义相同**的（例：水下摄影 / 潜水摄影；跑步 / 跑）。语义相关的（运动 / 跑步）不要合并。
2. canonical 选那个条数最多、或者最通用的写法。
3. 拿不准就不要提，宁可漏也不要错——错误归并会把两档内容混在一起。
4. 没有可归并的就返回空数组。

只输出 JSON：{"merges": [{"canonical": "运动", "aliases": ["跑步", "健身"]}]}"""


def _clean(text: str, limit: int) -> str:
    s = " ".join(str(text or "").split()).strip().strip("。")
    if len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


async def summarize_tag(tag: str, lines: list[str]) -> str:
    """给一个标签档写档首摘要；失败返回空串。"""
    if not lines:
        return ""
    body = "\n".join(lines)
    try:
        data = await chat_json(
            DIGEST_SYSTEM,
            [{"role": "user", "content": f"标签：#{tag}\n该档下的记录：\n{body}"}],
            temperature=0.3,
        )
    except AIUnavailable:
        return ""
    return _clean(data.get("digest") or "", settings.digest_char_limit)


async def merge_suggestions(tag_counts: list[tuple[str, int]]) -> list[dict]:
    """给一组 (标签, 条数)，返回归并建议；失败返回空列表。"""
    if len(tag_counts) < 2:
        return []
    body = "\n".join(f"- {t}（{c} 条）" for t, c in tag_counts)
    try:
        data = await chat_json(
            MERGE_SYSTEM,
            [{"role": "user", "content": f"全部标签：\n{body}"}],
            temperature=0.2,
        )
    except AIUnavailable:
        return []

    out: list[dict] = []
    for item in data.get("merges") or []:
        if not isinstance(item, dict):
            continue
        canon = str(item.get("canonical") or "").strip().lstrip("#")
        aliases = [str(a).strip().lstrip("#") for a in (item.get("aliases") or []) if str(a).strip()]
        aliases = [a for a in aliases if a and a != canon]
        if canon and aliases:
            out.append({"canonical": canon, "aliases": aliases})
    return out
