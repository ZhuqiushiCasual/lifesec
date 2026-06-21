import json
from datetime import datetime

from app.config import settings
from app.services.ai.client import get_openai_client

FINANCE_SYSTEM_PROMPT = """你是一个财务记录解析助手。用户会输入财务相关的记录，你需要解析出结构化信息。
请返回 JSON，格式如下：
{
  "type": "expense" | "income" | "asset" | "liability",
  "amount": number,
  "currency": "CNY" | "USD" | "HKD",
  "category": "shopping" | "invest_dividend" | "invest_gain" | "invest_loss" | "real_estate" | "cash" | "salary" | "other",
  "counterparty": "交易对手/商户/股票名称" | null,
  "account": "支付宝" | "银行卡" | "证券账户" | "房贷" | "现金" | null
}
只返回 JSON，不要有其他文字。"""


async def parse_finance(content: str) -> dict:
    client = get_openai_client()
    resp = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": FINANCE_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    print(resp.choices[0].message.content)

    return json.loads(resp.choices[0].message.content)
