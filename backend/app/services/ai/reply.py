"""回应生成 —— 对话接口的 LLM 出口。

一次调用同时完成三件事：判定意图、抽取结构化结果、生成一句回应。
不拆成两次调用：意图和回应本来就该来自同一个理解，且更省一次往返。
"""

from __future__ import annotations

from typing import Any

from app.services.ai.client import AIUnavailable, chat_json

REPLY_SYSTEM = """你是这个用户的个人秘书，只服务他一个人。你的职责是让他「被回应、被记住」。

必须遵守：
1. 永远回应，只回一句话，40 字以内。不寒暄、不客套、不复述他说过的话。
2. 必须记得：下面「记忆」里如果有相关内容，回应要自然引用（例如"这周第三次了"）。
   记忆里没有的就不要编造。
3. 语气像熟人，不像客服。不过度热情，禁止"我理解你的感受""感谢分享"这类套话。
4. 他在表达情绪时，先接住，不评价、不建议、不说教。
5. 他提到想做但还没做的事时，可以追问一句。
6. 只说人话，不输出 Markdown。

只输出 JSON，不要任何多余文字：
{
  "type": "record | plan | finance | feeling | chat",
  "reply": "一句话回应",
  "title": "type 为 plan 时给出待办标题，否则 null",
  "entities": {"按需填写，如 sport/duration/amount/category 等；没有就填空对象"}
}"""

FALLBACK = {
    "type": "record",
    "reply": "记下了。",
    "title": None,
    "entities": {},
}


async def generate(memory_block: str, history: list[dict], user_text: str) -> dict[str, Any]:
    system = REPLY_SYSTEM + "\n\n## 记忆（关于这个用户，可能为空）\n" + (memory_block.strip() or "（暂无）")
    messages = [*history, {"role": "user", "content": user_text}]

    try:
        data = await chat_json(system, messages, temperature=0.6)
    except AIUnavailable:
        return dict(FALLBACK)

    reply = str(data.get("reply") or "").strip()
    if not reply:
        return dict(FALLBACK)
    return {
        "type": str(data.get("type") or "record"),
        "reply": reply,
        "title": data.get("title") or None,
        "entities": data.get("entities") if isinstance(data.get("entities"), dict) else {},
    }
