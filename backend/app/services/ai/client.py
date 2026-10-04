"""DeepSeek 客户端 —— 系统唯一的模型出口。

两处调用（对话 / 摘要）都从这里走，方便统一控制模型、温度与失败兜底。
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from openai import AsyncOpenAI

from app.config import settings

log = logging.getLogger("selfsec.ai")


@lru_cache(maxsize=1)
def get_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)


class AIUnavailable(RuntimeError):
    """模型不可用（未配置 key / 调用失败）——调用方应降级而不是报错给用户。"""


async def chat_json(system: str, messages: list[dict], *, temperature: float = 0.3) -> dict[str, Any]:
    """调用模型并解析 JSON。失败抛 AIUnavailable，由调用方兜底。"""
    if not settings.openai_api_key:
        raise AIUnavailable("OPENAI_API_KEY 未配置")

    try:
        resp = await get_client().chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "system", "content": system}, *messages],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001 —— 任何失败都降级，不让用户看到报错
        log.warning("模型调用失败: %s", e)
        raise AIUnavailable(str(e)) from e
