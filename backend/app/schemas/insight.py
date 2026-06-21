from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class InsightResponse(BaseModel):
    id: str
    user_id: str
    title: str
    summary: str
    impact: Optional[str]
    category: str
    topics: Optional[list[str]]
    importance: Optional[int]
    source_url: Optional[str]
    source_name: Optional[str]
    published_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class InsightListResponse(BaseModel):
    items: list[InsightResponse]
    total: int
