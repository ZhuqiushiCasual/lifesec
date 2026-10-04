"""摘要生成 —— 「总结意识」（4.1 长期画像）专用的 LLM 出口。"""

from __future__ import annotations

from app.services.ai.client import AIUnavailable, chat_json

PROFILE_SYSTEM = """你在为一个人写一段「关于他」的画像，供他的个人秘书在对话前阅读。

要求：
1. 只写这一段，250 字以内，直接陈述，不加标题、不加列表、不加 Markdown。
2. 写三件事：他是谁 / 他反复在做和反复没做成的事 / 最近的状态和变化。
3. 只依据给定的事件记录，不要推测、不要美化、不要编造。
4. 用第二人称"你"。像一个熟悉他的人在替别人介绍他。

只输出 JSON：{"profile": "画像正文"}"""


async def summarize(event_lines: list[str]) -> str:
    """把全部事件压成一段画像；失败返回空串（调用方跳过本次刷新）。"""
    if not event_lines:
        return ""

    body = "\n".join(event_lines)
    try:
        data = await chat_json(
            PROFILE_SYSTEM,
            [{"role": "user", "content": f"以下是他的全部记录：\n{body}"}],
            temperature=0.3,
        )
    except AIUnavailable:
        return ""

    return str(data.get("profile") or "").strip()
