"""`/api/date/*` —— 约会挑餐厅。

两组路由，鉴权方式故意不同：

- **public**（不带 API_TOKEN）：这张页面的读者是女朋友，她没有 selfsec 的
  接口 token。所以读菜单、提交选择两个端点走独立的 public_router，
  挂在 `main.py` 里不带 `verify_token` 的那一支。
- **admin**（密码）：增删改排序、探店记录查询要密码，走请求头 `X-Date-Password`，
  对应 `DATE_ADMIN_PASSWORD`。**不是** API_TOKEN —— 那是给 Hermes 用的，
  不该拿去分享给另一半。

提交选择只落一条 `messages(role=me)`，不调模型：她点一下要立刻成功，
而生成回应是另一条路径（他自己在窗口里会看到这句话）。
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.date_menu import DateMenuItem
from app.models.date_visit import DateVisit
from app.models.message import KIND_USER, ROLE_ME, Message
from app.schemas.date_menu import (
    ChooseIn,
    ChooseOut,
    DateItemCreate,
    DateItemOut,
    DateItemUpdate,
    DateVisitOut,
    ReorderIn,
)
from app.services.deps import DEFAULT_USER_ID

public_router = APIRouter(prefix="/api/date", tags=["date"])
admin_router = APIRouter(prefix="/api/date", tags=["date-admin"])


async def verify_date_admin(x_date_password: str = Header(default="", alias="X-Date-Password")) -> None:
    """后台密码。空密码一律拒绝（宁可后台进不去，也不要裸奔）。"""
    expect = settings.date_admin_password or ""
    if not expect:
        raise HTTPException(status_code=503, detail="未配置 DATE_ADMIN_PASSWORD，后台已禁用")
    if not secrets.compare_digest(x_date_password, expect):
        raise HTTPException(status_code=401, detail="密码不对")


async def _ordered(db: AsyncSession, include_hidden: bool) -> list[DateMenuItem]:
    stmt = select(DateMenuItem).order_by(DateMenuItem.sort, DateMenuItem.id)
    if not include_hidden:
        stmt = stmt.where(DateMenuItem.hidden.is_(False))
    return list((await db.execute(stmt)).scalars().all())


# ────────────────────────── public ──────────────────────────


@public_router.get("/menu", response_model=list[DateItemOut])
async def get_menu(db: AsyncSession = Depends(get_db)):
    """前台菜单。隐藏项不出现。"""
    return await _ordered(db, include_hidden=False)


@public_router.get("/ping")
async def ping():
    """给前端探活用：确认后端起来了 + 后台是否可用。"""
    return {"ok": True, "admin_enabled": bool(settings.date_admin_password)}


@public_router.post("/choose", response_model=ChooseOut)
async def choose(payload: ChooseIn, db: AsyncSession = Depends(get_db)):
    """她挑完发出来的那句话 —— 落一条「我说的」消息，出现在 selfsec 窗口里。

    刻意不触发 AI 回应：
    1) 她按下发送就该立刻成功，不该等一次模型调用；
    2) 这条消息的读者是他，回不回、怎么回是他的事。
    """
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息不能是空的")

    # 卡片必须满足 schemas.api.Card（kind 必填），否则 GET /api/messages 会在
    # 校验这一步 500 —— 一条脏卡片能让整个窗口流打不开。所以这里只放合法字段。
    # 注意：窗口渲染只给 secretary 的消息画卡片，role=me 带 card 不会显示，
    # 纯粹是给以后做统计/回溯留的结构化线索。
    card: dict = {
        "kind": "record",
        "title": "选好了",
        "lines": [],
        "meta": {"source": "date-picker"},
    }
    if payload.restaurant_id:
        item = (
            await db.execute(select(DateMenuItem).where(DateMenuItem.id == payload.restaurant_id))
        ).scalar_one_or_none()
        if item:
            card["lines"] = [f"{item.name} · {item.branch}"]
            card["meta"].update(
                {"restaurant_id": item.id, "restaurant": item.name, "branch": item.branch,
                 "dist_km": item.dist_km, "price": item.price}
            )

    msg = Message(user_id=DEFAULT_USER_ID, role=ROLE_ME, kind=KIND_USER, content=text, card=card)
    db.add(msg)
    await db.commit()
    return ChooseOut(ok=True, message_id=msg.id, text=text)


# ────────────────────────── admin ───────────────────────────


@admin_router.post("/admin/check", dependencies=[Depends(verify_date_admin)])
async def admin_check():
    return {"ok": True}


@admin_router.get("/admin/items", response_model=list[DateItemOut], dependencies=[Depends(verify_date_admin)])
async def admin_list(db: AsyncSession = Depends(get_db)):
    """后台列表：含隐藏项，顺序同前台。"""
    return await _ordered(db, include_hidden=True)


@admin_router.get("/admin/visits", response_model=list[DateVisitOut], dependencies=[Depends(verify_date_admin)])
async def list_visits(
    limit: int = Query(50, ge=1, le=200),
    restaurant_id: str | None = Query(None, description="只看某家店的探店记录"),
    db: AsyncSession = Depends(get_db),
):
    """探店记录（从对话里长出来的「去过哪、吃得怎么样」）。

    前台怎么展示还没定，先留一个后台查询口，方便核对关联是否正确。
    """
    stmt = select(DateVisit).order_by(
        DateVisit.visited_on.desc(), DateVisit.created_at.desc(), DateVisit.id.desc()
    )
    if restaurant_id:
        stmt = stmt.where(DateVisit.restaurant_id == restaurant_id)
    rows = list((await db.execute(stmt.limit(limit))).scalars().all())
    return [
        DateVisitOut(
            id=v.id,
            event_id=v.event_id,
            restaurant_id=v.restaurant_id,
            restaurant_name=v.restaurant_name,
            branch=v.branch or "",
            cuisine=v.cuisine or "",
            visited_on=v.visited_on,
            rating=v.rating,
            dishes=list(v.dishes or []),
            companion=v.companion,
            occasion=v.occasion,
            review=v.review or "",
            created_at=v.created_at,
            updated_at=v.updated_at,
        )
        for v in rows
    ]


@admin_router.post("/items", response_model=DateItemOut, status_code=201, dependencies=[Depends(verify_date_admin)])
async def create_item(payload: DateItemCreate, db: AsyncSession = Depends(get_db)):
    items = await _ordered(db, include_hidden=True)
    next_sort = (max((i.sort for i in items), default=0) + 10) if items else 10
    row = DateMenuItem(**payload.model_dump(), sort=next_sort)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@admin_router.patch("/items/{item_id}", response_model=DateItemOut, dependencies=[Depends(verify_date_admin)])
async def update_item(item_id: str, payload: DateItemUpdate, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(DateMenuItem).where(DateMenuItem.id == item_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="没有这一条")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return row


@admin_router.delete("/items/{item_id}", dependencies=[Depends(verify_date_admin)])
async def delete_item(item_id: str, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(DateMenuItem).where(DateMenuItem.id == item_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="没有这一条")
    # 探店记录是历史，不跟着菜单项删：把外键摘掉，店名快照还在。
    # SQLite 默认不启用外键约束，所以这里显式做，别只依赖 ondelete。
    await db.execute(update(DateVisit).where(DateVisit.restaurant_id == item_id).values(restaurant_id=None))
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@admin_router.post("/reorder", dependencies=[Depends(verify_date_admin)])
async def reorder(payload: ReorderIn, db: AsyncSession = Depends(get_db)):
    """按传入的 id 顺序重排。没传到的项保持相对位置、排在后面。"""
    rows = {r.id: r for r in await _ordered(db, include_hidden=True)}
    unknown = [i for i in payload.ids if i not in rows]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知的 id：{unknown[:3]}")
    order = payload.ids + [i for i in rows if i not in payload.ids]
    for idx, item_id in enumerate(order):
        rows[item_id].sort = (idx + 1) * 10
    await db.commit()
    return {"ok": True, "count": len(order)}
