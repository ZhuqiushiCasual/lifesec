from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from typing import Optional


class FinanceTxn(Base):
    __tablename__ = "finance_txns"
    __table_args__ = {"comment": "财务记录表——存储每一笔收支"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), comment="交易唯一标识 UUID")
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, comment="关联用户 ID")
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="收支类型（income / expense）"
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, comment="金额")
    currency: Mapped[str] = mapped_column(String(10), default="CNY", comment="币种（默认 CNY）")
    category: Mapped[str] = mapped_column(String(50), nullable=False, comment="分类（如 food / transport / salary）")
    counterparty: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, comment="交易对手")
    account: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="账户（如 支付宝 / 微信）")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="备注")
    voice_source: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否来自语音输入")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="交易发生时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="记录创建时间")

    user = relationship("User", back_populates="finance_txns")
