from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import cast, Date, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.finance import FinanceTxn
from app.models.user import User
from app.schemas.finance import (
    AssetDistribution,
    FinanceSummary,
    FinanceTxnCreate,
    FinanceTxnResponse,
)
from app.services.ai.finance_parser import parse_finance
from app.services.deps import get_current_user

router = APIRouter(prefix="/api/finance", tags=["Finance"])


@router.post("/txns", response_model=FinanceTxnResponse, status_code=201)
async def create_txn(
    data: FinanceTxnCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    parsed = await parse_finance(data.content)
    txn = FinanceTxn(
        user_id=user.id,
        type=parsed.get("type", "expense"),
        amount=Decimal(str(parsed.get("amount", 0))),
        currency=parsed.get("currency", "CNY"),
        category=parsed.get("category", "other"),
        counterparty=parsed.get("counterparty"),
        account=parsed.get("account"),
        note=data.content,
        recorded_at=data.recorded_at or datetime.utcnow(),
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return FinanceTxnResponse.model_validate(txn)


@router.get("/txns")
async def list_txns(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(FinanceTxn)
        .where(FinanceTxn.user_id == user.id)
        .order_by(FinanceTxn.recorded_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(q)
    items = result.scalars().all()
    return {
        "items": [FinanceTxnResponse.model_validate(t) for t in items],
        "total": len(items),
    }


@router.delete("/txns/{txn_id}", status_code=204)
async def delete_txn(
    txn_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FinanceTxn).where(FinanceTxn.id == txn_id, FinanceTxn.user_id == user.id)
    )
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    await db.delete(txn)
    await db.commit()


@router.get("/summary")
async def get_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    income_q = select(func.coalesce(func.sum(FinanceTxn.amount), 0)).where(
        FinanceTxn.user_id == user.id,
        FinanceTxn.type.in_(["income"]),
        FinanceTxn.recorded_at >= month_start,
    )
    expense_q = select(func.coalesce(func.sum(FinanceTxn.amount), 0)).where(
        FinanceTxn.user_id == user.id,
        FinanceTxn.type.in_(["expense"]),
        FinanceTxn.recorded_at >= month_start,
    )
    monthly_inflow = (await db.execute(income_q)).scalar()
    monthly_outflow = (await db.execute(expense_q)).scalar()

    return FinanceSummary(
        total_assets=Decimal("0"),
        net_assets=Decimal("0"),
        monthly_inflow=monthly_inflow,
        monthly_outflow=monthly_outflow,
        monthly_net=monthly_inflow - monthly_outflow,
    )


@router.get("/assets")
async def get_assets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return [
        AssetDistribution(category="stock", amount=Decimal("0"), percentage=0),
        AssetDistribution(category="fund", amount=Decimal("0"), percentage=0),
        AssetDistribution(category="real_estate", amount=Decimal("0"), percentage=0),
        AssetDistribution(category="cash", amount=Decimal("0"), percentage=0),
    ]
