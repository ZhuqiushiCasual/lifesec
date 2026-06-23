from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import Event
from app.models.finance import FinanceTxn
from app.schemas.event import EventCreate, EventListResponse, EventResponse
from app.services.ai.event_parser import detect_finance_intent, parse_event
from app.services.ai.finance_parser import parse_finance
from app.services.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/events", tags=["Events"])


@router.post("", response_model=EventResponse, status_code=201)
async def create_event(
    data: EventCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    parsed = await parse_event(data.content)

    event = Event(
        user_id=user.id,
        content=data.content,
        type=parsed.get("type", "event"),
        entities=parsed.get("entities"),
        sentiment=parsed.get("sentiment"),
        sentiment_score=parsed.get("sentiment_score"),
        tags=parsed.get("tags"),
    )
    is_finance = detect_finance_intent(parsed, data.content)
    if not is_finance:
        db.add(event)
    if is_finance:
        finance_data = await parse_finance(data.content)
        txn = FinanceTxn(
            user_id=user.id,
            type=finance_data.get("type", "expense"),
            amount=Decimal(finance_data.get("amount", 0)),
            currency=finance_data.get("currency", "CNY"),
            category=finance_data.get("category", "other"),
            counterparty=finance_data.get("counterparty"),
            account=finance_data.get("account"),
            note=data.content,
        )
        db.add(txn)

    await db.commit()
    await db.refresh(event)
    return EventResponse.model_validate(event)


@router.get("", response_model=EventListResponse)
async def list_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    total_q = select(func.count(Event.id)).where(Event.user_id == user.id)
    total = (await db.execute(total_q)).scalar()

    q = (
        select(Event)
        .where(Event.user_id == user.id)
        .order_by(Event.recorded_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(q)
    items = result.scalars().all()

    return EventListResponse(
        items=[EventResponse.model_validate(e) for e in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete("/{event_id}", status_code=204)
async def delete_event(
    event_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Event).where(Event.id == event_id, Event.user_id == user.id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    await db.delete(event)
    await db.commit()
