import json

from app.config import settings
from app.services.ai.client import get_openai_client

SYSTEM_PROMPT = """你是一个生活记录解析助手。用户会输入日常记录，你需要解析出结构化信息。

事件类型固定为以下 7 种之一：
- health   健康（体征测量、症状、就医）
- sport    运动（跑步、瑜伽、游泳等）
- sleep    睡眠（时长、质量、午睡等）
- dietary  饮食（三餐、饮水、零食）
- mood     心情（情绪、精力）
- finance  财务（股票、基金、期货、消费、收入等）
- event    事件（工作、社交、出行等，无法归入上述 6 类时使用）

每种类型有专属的 entities 结构。所有字段必须返回，抽取不到的用默认值（空字符串""、0、false、空数组[]），严禁返回 null。

=== health ===
{
  "metric_name": "",        // 体征指标: blood_pressure/weight/blood_sugar/heart_rate/temperature，无则为""
  "metric_value": 0,        // 指标数值
  "metric_unit": "",        // 单位: kg/mmHg/mmol/L/bpm/℃
  "symptom": "",            // 症状描述
  "body_part": "",          // 身体部位
  "severity": 0,            // 严重程度 1-5，无则 0
  "hospital": "",           // 就医医院
  "medication": ""          // 用药
}

=== sport ===
{
  "activity": "",           // 运动类型: 跑步/瑜伽/游泳/健身/骑行/球类
  "duration": 0,            // 时长（分钟）
  "distance": 0,            // 距离（公里）
  "calories": 0,            // 消耗热量（kcal）
  "intensity": "low"        // 强度: low/medium/high
}

=== sleep ===
{
  "duration": 0,            // 睡眠时长（小时）
  "quality": 0,             // 质量评分 1-5
  "bedtime": "",            // 入睡时间 HH:MM
  "wake_time": "",          // 起床时间 HH:MM
  "has_dream": false,       // 是否做梦
  "nap": false              // 是否午睡
}

=== dietary ===
{
  "meal": "",               // 餐次: breakfast/lunch/dinner/snack
  "foods": [],              // 食物列表
  "calories": 0,            // 摄入热量（kcal）
  "water_ml": 0,            // 饮水量（ml）
  "is_healthy": false       // 是否健康饮食
}

=== mood ===
{
  "emotion": "",            // 情绪: happy/anxious/calm/sad/angry/excited/tired
  "score": 0,               // 情绪分 1-5（5 最佳）
  "trigger": "",            // 触发原因
  "energy": 0               // 精力值 1-5
}

=== finance ===
{
  "amount": 0               // 金额，整数即可
}

=== event ===
{
  "category": "",           // 子类: work/social/travel/learning/other
  "title": "",              // 事件简述
  "location": "",           // 地点
  "participants": []        // 参与人
}

返回 JSON 格式：
{
  "type": "health" | "sport" | "sleep" | "dietary" | "mood" | "finance" | "event",
  "entities": { ...对应类型的完整结构，所有字段必须有值... },
  "sentiment": "positive" | "neutral" | "negative",
  "sentiment_score": 0.0-1.0,
  "tags": ["..."]
}
只返回 JSON，不要有其他文字。"""

_TYPE_DEFAULTS = {
    "health": {
        "metric_name": "", "metric_value": 0, "metric_unit": "",
        "symptom": "", "body_part": "", "severity": 0,
        "hospital": "", "medication": "",
    },
    "sport": {
        "activity": "", "duration": 0, "distance": 0,
        "calories": 0, "intensity": "low",
    },
    "sleep": {
        "duration": 0, "quality": 0, "bedtime": "",
        "wake_time": "", "has_dream": False, "nap": False,
    },
    "dietary": {
        "meal": "", "foods": [], "calories": 0,
        "water_ml": 0, "is_healthy": False,
    },
    "mood": {
        "emotion": "", "score": 0, "trigger": "", "energy": 0,
    },
    "finance": {
        "amount": 0,
    },
    "event": {
        "category": "", "title": "", "location": "", "participants": [],
    },
}


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
    parsed = json.loads(resp.choices[0].message.content)

    event_type = parsed.get("type", "event")
    if event_type not in _TYPE_DEFAULTS:
        event_type = "event"

    defaults = _TYPE_DEFAULTS[event_type]
    entities = parsed.get("entities") or {}
    merged = {**defaults, **entities}
    for key, default_val in defaults.items():
        val = merged.get(key)
        if val is None:
            merged[key] = default_val
    parsed["entities"] = merged
    parsed["type"] = event_type

    return parsed


_FINANCE_KEYWORDS = frozenset(
    {"花", "买", "消费", "支出", "收入", "工资", "转账", "付款", "元", "块", "¥", "￥", "红包", "退款", "报销"}
)


def detect_finance_intent(parsed: dict, content: str = "") -> bool:
    if parsed.get("type") == "finance":
        return True
    return any(kw in content for kw in _FINANCE_KEYWORDS)
