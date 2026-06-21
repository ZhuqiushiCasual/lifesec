from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from typing import Optional


class FinanceTxnCreate(BaseModel):
    content: str
    recorded_at: Optional[datetime] = None


class FinanceTxnResponse(BaseModel):
    id: str
    user_id: str
    type: str
    amount: Decimal
    currency: str
    category: str
    counterparty: Optional[str]
    account: Optional[str]
    note: Optional[str]
    voice_source: bool
    recorded_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class FinanceSummary(BaseModel):
    total_assets: Decimal
    net_assets: Decimal
    monthly_inflow: Decimal
    monthly_outflow: Decimal
    monthly_net: Decimal


class AssetDistribution(BaseModel):
    category: str
    amount: Decimal
    percentage: float
