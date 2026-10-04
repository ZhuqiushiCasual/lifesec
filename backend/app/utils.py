"""本地时间工具。

项目只有单用户、单时区，统一用「UTC + 固定偏移」的 naive 本地时间，
避免 naive/aware 混用带来的比较错误。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.config import settings


def now_local() -> datetime:
    return datetime.utcnow() + timedelta(hours=settings.tz_offset_hours)


def today_local() -> date:
    return now_local().date()
