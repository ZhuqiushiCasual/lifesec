"""菜单项的输入 / 输出结构。

管理端 PATCH 用「只传改了的字段」的语义（`exclude_unset`），
所以这里全部字段可空；真正落库前用 `model_fields_set` 判断。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DateItemBase(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    branch: Optional[str] = Field(default=None, max_length=80)
    cuisine: Optional[str] = Field(default=None, max_length=80)
    price: Optional[int] = Field(default=None, ge=0, le=100000)
    score: Optional[float] = Field(default=None, ge=0, le=5)
    taste_light: Optional[int] = Field(default=None, ge=0, le=5)
    taste_spicy: Optional[int] = Field(default=None, ge=0, le=5)
    taste_oil: Optional[int] = Field(default=None, ge=0, le=5)
    taste_label: Optional[str] = Field(default=None, max_length=24)
    taste_kind: Optional[str] = Field(default=None, pattern="^(light|spicy|oil)$")
    reason: Optional[str] = None
    metro: Optional[str] = None
    reach: Optional[str] = None
    tip: Optional[str] = None
    dist_km: Optional[float] = Field(default=None, ge=0, le=100)
    art: Optional[str] = Field(default=None, max_length=24)
    accent_a: Optional[str] = Field(default=None, max_length=16)
    accent_b: Optional[str] = Field(default=None, max_length=16)
    photo: Optional[str] = Field(default=None, max_length=255)
    hidden: Optional[bool] = None


class DateItemCreate(DateItemBase):
    name: str = Field(max_length=120)


class DateItemUpdate(DateItemBase):
    """PATCH 用：全部可选，只落传了的字段（exclude_unset）。"""
    pass


class DateItemOut(DateItemBase):
    id: str
    sort: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ReorderIn(BaseModel):
    ids: list[str] = Field(min_length=1)


class ChooseIn(BaseModel):
    """她挑完之后发出去的那句话。text 允许被改写，restaurant_id 只作记录。"""

    text: str = Field(min_length=1, max_length=200)
    restaurant_id: Optional[str] = None


class ChooseOut(BaseModel):
    ok: bool
    message_id: str
    text: str
