import os
from pathlib import Path

# 读取 backend/.env（零依赖极简实现；真实环境变量优先）
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _, _value = _line.partition("=")
        os.environ.setdefault(_key.strip(), _value.strip())


class Settings:
    database_url: str = os.environ.get("DATABASE_URL", "")
    openai_base_url: str = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com")
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_model: str = os.environ.get("OPENAI_MODEL", "deepseek-v4-pro")

    # 非空时启用接口鉴权：请求需带 X-API-Token 头
    api_token: str = os.environ.get("API_TOKEN", "")
    debug: bool = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")


settings = Settings()
