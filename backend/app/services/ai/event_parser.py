import json

from app.config import settings
from app.services.ai.client import get_openai_client

SYSTEM_PROMPT = """你是一个生活记录解析助手。用户会输入日常记录，你需要解析出结构化信息。
请返回 JSON，格式如下：
{
  "type": "dietary" | "sport" | "health" | "mood" | "invest" | "event",
  "entities": {
    "food": ["..."] | null,
    "activity": "..." | null,
    "symptom": "..." | null,
    "mood": "..." | null,
    "amount": number | null,
    "currency": "CNY" | "USD" | null,
    "counterparty": "..." | null,
    "category": "..." | null
  },
  "sentiment": "positive" | "neutral" | "negative",
  "sentiment_score": 0.0-1.0,
  "tags": ["..."]
}
只返回 JSON，不要有其他文字。"""


async def parse_event(content: str) -> dict:
    client = get_openai_client()
    resp = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    print(resp.choices[0].message.content)
    return json.loads(resp.choices[0].message.content)


def detect_finance_intent(parsed: dict) -> bool:
    return parsed.get("type") == "invest" or (
        parsed.get("entities", {}).get("amount") is not None
        and parsed.get("entities", {}).get("category") is not None
    )
