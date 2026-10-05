"""回应生成 —— 对话接口的 LLM 出口。

一次调用同时完成四件事：判定意图、判定「并入今天哪条事件」、生成标签、生成一句回应。
不拆成多次调用：这些本来就是同一个理解的不同侧面，
拆开只会更贵，而且会出现"回应说合并了、归档却新建了一条"这种自相矛盾。
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

## 归档规则（和回应同样重要，它决定系统最终记住什么）

每条输入都要归到一条**事件**上：

7. 先看「今天已有的事件」。如果这次输入是其中某一条的重复、更正或补充
   （同一天、同一件事），就合并进去：merge_event_id 填那条事件的 id。
   合并时 content / entities / tags 要写成**合并之后的完整版本**，不是只写新增的部分。
   例：已有「今天跑了 40 分钟」，这次说「又跑了 30 分钟」→
       content 写「今天跑了 40 分钟，后来又跑了 30 分钟」。
8. 没有可合并的（新的一件事、换了个话题、或者今天还没有事件）→ merge_event_id 填 null，
   content 写这次输入整理后的完整表述。
9. content 要写成脱离上下文也能看懂的一句话，可以沿用他的说法；
   type 用 record / plan / finance / feeling / chat 里最贴切的一个
   （纯心情用 feeling，纯闲聊用 chat）。
10. tags 给 1-4 个：名词短语、2-6 个字、直接写词不加 #。
    **每次都重新想，不要照抄下面这份参考，也允许造参考之外的词。**
    参考（只是命名风格，不是可选清单）：
      领域类  运动 跑步 饮食 睡眠 健康 工作 加班 学习 阅读 财务 社交 家庭 情绪 出行 兴趣 外部信息
      性质类  目标 习惯 重复 进展 计划 吐槽 灵感 心事

只输出 JSON，不要任何多余文字：
{
  "type": "record | plan | finance | feeling | chat",
  "reply": "一句话回应",
  "title": "type 为 plan 时给出待办标题，否则 null",
  "content": "这条事件（合并后）的完整表述",
  "entities": {"按需填写，如 sport/duration/amount/category 等；没有就填空对象"},
  "tags": ["标签1", "标签2"],
  "merge_event_id": "并入的今天已有事件 id；没有就 null"
}"""

FALLBACK = {
    "type": "record",
    "reply": "记下了。",
    "title": None,
    "content": None,
    "entities": {},
    "tags": [],
    "merge_event_id": None,
}


def _clean_merge_id(raw: Any) -> str | None:
    """模型常把 null 写成字符串，这里统一成真 None。"""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    return None if s.lower() in ("", "null", "none", "nan") else s


async def generate(memory_block: str, history: list[dict], user_text: str) -> dict[str, Any]:
    system = REPLY_SYSTEM + "\n\n## 记忆（关于这个用户，可能为空）\n" + (memory_block.strip() or "（暂无）")
    messages = [*history, {"role": "user", "content": user_text}]

    try:
        data = await chat_json(system, messages, temperature=0.6)
    except AIUnavailable:
        return dict(FALLBACK, content=user_text)

    reply = str(data.get("reply") or "").strip()
    if not reply:
        return dict(FALLBACK, content=user_text)

    return {
        "type": str(data.get("type") or "record"),
        "reply": reply,
        "title": data.get("title") or None,
        "content": str(data.get("content") or "").strip() or user_text.strip(),
        "entities": data.get("entities") if isinstance(data.get("entities"), dict) else {},
        "tags": data.get("tags") if isinstance(data.get("tags"), list) else [],
        "merge_event_id": _clean_merge_id(data.get("merge_event_id")),
    }
