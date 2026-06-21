from datetime import date

from pydantic import BaseModel
from typing import Optional


class TodayBoardResponse(BaseModel):
    greeting: str
    date: str
    today_event_count: int
    sport_done: bool
    mood: Optional[str]
    water_warning: bool
    recent_events: list
    latest_insights: list
    has_latest_digest: bool
    digest_date: Optional[date]
