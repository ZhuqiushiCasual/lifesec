"""画像生成 —— 「总结意识」（4.1 长期画像）专用的 LLM 出口。

v3 起画像不是"一段话"，而是**分 5 节**。理由见 docs/记忆-同行调研.html 3.1：
各节的半衰期不同（身份几乎不变、正在做的事每周在变），
分开存才能只重算变了的那一节，而不是每天重新描写一遍你的人生。

**星型而不是链式**：画像的输入 = 上一版画像 + 馆藏目录（当导航用）+ 事件原文。
标签档的摘要只用来告诉模型"有什么"，结论本身仍然从原文里读——
避免"摘要的摘要"那种误差累积。

**防漂移**：把上一版画像一起给它，并要求"没有新依据的部分不要改写"。
"""

from __future__ import annotations

import logging

from app.config import settings
from app.services.ai.client import AIUnavailable, chat_json

log = logging.getLogger("selfsec.ai")

PORTRAIT_SYSTEM = """你在为一个人维护一份「画像」，供他的个人秘书在每次对话前阅读。

画像分 5 节，总字数必须 ≤ {limit} 字（硬约束，超了会被系统截断）：

[identity] 身份：年龄 / 职业 / 城市 / 在做的事。半衰期以年计。
[style]    沟通与风格：他要的是结论先行还是铺垫、语气偏好、格式偏好。半年。
[avoid]    回避项：什么话、什么做法会让他烦。半年。
[current]  当前进行中：项目、计划、期限、正在攻的目标。以周计，变化最快。
[insight]  结论级洞察：反复出现的模式、动机、他自己未必说出口的判断。以月计。

规则：
1. 只依据给定材料，不推测、不美化、不编造。材料里没有的宁可不写。
2. 用第二人称"你"。
3. **防漂移**：identity / style / avoid 三节尽量保持原样——没有新依据就不要改写措辞。
   只有新事实与之冲突时才动它，并在 summary 里说明。
4. [current] 每次都要重写。
5. 某一节确实没有内容时，写空字符串。
6. 不要写"（来源：…）"这类标注，来源由系统单独记录。
7. 整体像"一个熟悉他的人替他写的简介"，不是心理测评报告，不要写套话。

另外给一句 summary：这次相对上一版改了什么。
格式示例：`+新增：在做的项目 X；~修正：沟通偏好`。没有任何实质改动就写 `无变更`。

只输出 JSON（不要任何多余文字）：
{{"identity": "", "style": "", "avoid": "", "current": "", "insight": "", "summary": ""}}"""


def _clean(text: object, limit: int) -> str:
    s = " ".join(str(text or "").split()).strip()
    if len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


async def build_portrait(
    *,
    prev: dict[str, str] | None,
    digests: list[str],
    event_lines: list[str],
) -> dict[str, str]:
    """生成分节画像。失败返回空 dict（调用方跳过本次迭代）。

    prev          上一版分节画像（防漂移的锚点）
    digests       馆藏目录（导航层：告诉模型"有什么"，不下结论）
    event_lines   事件原文（结论的来源）
    """
    if not event_lines:
        return {}

    parts: list[str] = []
    if prev and any(prev.values()):
        parts.append("【上一版画像（没有新依据的部分请保持原样）】")
        for key, label in (
            ("identity", "identity 身份"),
            ("style", "style 沟通与风格"),
            ("avoid", "avoid 回避项"),
            ("current", "current 当前进行中"),
            ("insight", "insight 结论级洞察"),
        ):
            parts.append(f"{label}：{prev.get(key) or '（空）'}")

    if digests:
        parts.append("\n【馆藏目录（只作导航，不要在画像里复述目录）】")
        parts.extend(digests)

    parts.append(f"\n【全部记录（{len(event_lines)} 条）】")
    parts.extend(event_lines)

    try:
        data = await chat_json(
            PORTRAIT_SYSTEM.format(limit=settings.portrait_char_limit),
            [{"role": "user", "content": "\n".join(parts)}],
            temperature=0.3,
        )
    except AIUnavailable:
        return {}

    per_section = max(120, settings.portrait_char_limit // 3)
    out = {
        "identity": _clean(data.get("identity"), per_section),
        "style": _clean(data.get("style"), per_section),
        "avoid": _clean(data.get("avoid"), per_section),
        "current": _clean(data.get("current"), per_section),
        "insight": _clean(data.get("insight"), per_section),
    }
    out["summary"] = _clean(data.get("summary"), 200) or "无变更"

    if not any(out[k] for k in ("identity", "style", "avoid", "current", "insight")):
        log.warning("画像生成返回空内容，跳过本次迭代")
        return {}
    return out

