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

    # ── 画像（Portrait）────────────────────────────────────
    # 硬上限：整段画像的字符数。画像越长越不被遵守，而且这份 token 每轮都要付。
    portrait_char_limit: int = int(os.environ.get("PORTRAIT_CHAR_LIMIT", "1500"))
    # 时钟一：每 N 条用户消息迭代一次画像
    portrait_user_turns: int = int(os.environ.get("PORTRAIT_USER_TURNS", "20"))
    # 时钟二：距上次迭代超过 N 小时 **且** 新增事件 ≥ M 条，才重算（防漂移：没有新增就不重写）
    portrait_hours: int = int(os.environ.get("PORTRAIT_HOURS", "24"))
    portrait_min_new_events: int = int(os.environ.get("PORTRAIT_MIN_NEW_EVENTS", "3"))

    # ── 馆藏（Library / 索引卡）────────────────────────────
    # 索引卡上限行数（常驻注入的那份目录，对应 Claude Code 的 200 行索引）
    index_max_lines: int = int(os.environ.get("INDEX_MAX_LINES", "60"))
    # 每个标签的档首摘要上限（字符）
    digest_char_limit: int = int(os.environ.get("DIGEST_CHAR_LIMIT", "60"))
    # 时钟三：每 N 条用户消息重算「有新增事件的那些标签」的档首摘要
    tag_iter_turns: int = int(os.environ.get("TAG_ITER_TURNS", "10"))

    # ── 拼接（Context 组装）────────────────────────────────
    # Block C：近 N 轮「用户提问」（只取我说的，带时间锚与主题）
    user_turn_window: int = int(os.environ.get("USER_TURN_WINDOW", "40"))
    # 命中规则：每次最多加载几档、每档最多几条原文
    hit_max_tags: int = int(os.environ.get("HIT_MAX_TAGS", "3"))
    hit_max_events: int = int(os.environ.get("HIT_MAX_EVENTS", "3"))
    # 软归一：注入 prompt 的「已有标签清单」条数（让模型优先复用已有标签）
    existing_tags_in_prompt: int = int(os.environ.get("EXISTING_TAGS_IN_PROMPT", "60"))


settings = Settings()
