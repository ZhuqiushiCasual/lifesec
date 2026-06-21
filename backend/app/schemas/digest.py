from datetime import date, datetime

from pydantic import BaseModel
from typing import Optional


class DigestResponse(BaseModel):
    id: str
    user_id: str
    date: date
    score: Optional[int]
    highlights: Optional[dict]
    problems: Optional[dict]
    suggestions: Optional[dict]
    trends: Optional[dict]
    created_at: datetime

    class Config:
        from_attributes = True
