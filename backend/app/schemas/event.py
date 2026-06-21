from datetime import datetime

from pydantic import BaseModel
from typing import Optional


class EventCreate(BaseModel):
    content: str
    recorded_at: Optional[datetime] = None


class EventResponse(BaseModel):
    id: str
    user_id: str
    type: str
    content: str
    entities: Optional[dict]
    sentiment: Optional[str]
    sentiment_score: Optional[float]
    tags: Optional[list[str]]
    voice_source: bool
    recorded_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class EventListResponse(BaseModel):
    items: list[EventResponse]
    total: int
    page: int
    page_size: int
