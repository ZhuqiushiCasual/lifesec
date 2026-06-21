from functools import lru_cache

from openai import AsyncOpenAI

from app.config import settings


@lru_cache(maxsize=1)
def get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
