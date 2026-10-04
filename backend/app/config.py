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
    # 默认落到本地 SQLite，开箱即跑；生产用环境变量覆盖为 MySQL（mysql+asyncmy://...）
    database_url: str = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./selfsec.db")

    openai_base_url: str = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com")
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_model: str = os.environ.get("OPENAI_MODEL", "deepseek-v4-pro")

    # 非空时启用接口鉴权：请求需带 X-API-Token 头
    api_token: str = os.environ.get("API_TOKEN", "")
    debug: bool = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")

    # ── 内置调度（services/scheduler.py）─────────────────────
    scheduler_enabled: bool = os.environ.get("SCHEDULER_ENABLED", "1").lower() in ("1", "true", "yes")
    tz_offset_hours: int = int(os.environ.get("TZ_OFFSET_HOURS", "8"))
    morning_hour: int = int(os.environ.get("MORNING_HOUR", "8"))    # 问候
    evening_hour: int = int(os.environ.get("EVENING_HOUR", "21"))   # 问候 + 总结意识

    # ── 记忆层参数 ──────────────────────────────────────────
    # 「总结意识」阈值：新增事件数达到该值即重算画像（也支持定时/手动触发）
    profile_trigger_events: int = int(os.environ.get("PROFILE_TRIGGER_EVENTS", "20"))
    # 4.4 会话短期：注入 prompt 的最近轮数
    session_window: int = int(os.environ.get("SESSION_WINDOW", "6"))


settings = Settings()
