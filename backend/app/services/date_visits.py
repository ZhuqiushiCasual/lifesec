"""探店记录落库 —— 把对话里「已经发生的吃饭 / 会面」变成 date_visits。

判定在模型那一次生成里完成（`date_visit.is_visit`），这里只做三件事：

    ① 校验 restaurant_id：必须命中菜单项；命中不了就用店名本地匹配
    ② 规范化字段：日期 / 评分 / 菜名 / 同行人 / 场合
    ③ 落库去重：同一个人 + 同一家店 + 同一个就餐日期，只保留一条

为什么不把探店信息塞进 events.entities：
    「哪家店、什么时候、吃了什么、和谁」是需要按店聚合查询的结构化事实，
    单独一张表才能干净地挂到 date_menu 上；events 仍是叙事记忆的真相源。

去重的口径是「人 + 店 + 日期」而不是 event_id：
    事件层的同一天合并由模型判定，偶尔会漏合并；探店记录再兜一层，
    避免同一天对同一家店的两次补充堆成两条。代价是同一天在同一家店吃两顿
    （午饭 + 晚饭）会并成一条 —— 对个人记录来说可以接受。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.date_menu import DateMenuItem
from app.models.date_visit import DateVisit
from app.models.event import Event
from app.models.user import User
from app.utils import now_local, today_local

MAX_REVIEW = 2000
MAX_DISHES = 12
MAX_DISH_LEN = 30
MAX_TEXT = 120

# 店名里的装饰分隔符：「梅溪徐记 · 鲜牛肉火锅」→ 简称「梅溪徐记」
_NAME_SPLIT = re.compile(r"[·・•|\s]+")
# 匹配前统一去掉空格和标点，避免「梅溪徐记（德信中心店）」对不上
_NORM_STRIP = re.compile(r"[\s·・•|\-—_（）()【】\[\]「」,，。.!！?？:：/]+")


def _norm(value: Any) -> str:
    return _NORM_STRIP.sub("", str(value or "")).lower()


def _short_name(item: DateMenuItem) -> str:
    parts = [p for p in _NAME_SPLIT.split((item.name or "").strip()) if p]
    return parts[0] if parts else (item.name or "").strip()


def _match_by_id(items: list[DateMenuItem], raw_id: Any) -> DateMenuItem | None:
    if not isinstance(raw_id, str):
        return None
    rid = raw_id.strip()
    return next((item for item in items if item.id == rid), None)


def _match_by_name(items: list[DateMenuItem], raw_name: Any) -> DateMenuItem | None:
    """按模型给的店名匹配；只对「简称」做包含匹配，避免菜系词误伤。

    例：模型给「鲜牛肉火锅」不能匹配到「梅溪徐记 · 鲜牛肉火锅」——
    那只是一个菜系描述，不是店名。
    """
    name = _norm(raw_name)
    if len(name) < 2:
        return None

    best: DateMenuItem | None = None
    best_score = 0
    for item in items:
        short = _norm(_short_name(item))
        full = _norm(item.name)
        if not short and not full:
            continue
        if name == full or name == short:
            score = 10_000 + len(short)
        elif len(short) >= 2 and (short in name or name in short):
            score = len(short)
        else:
            continue
        if score > best_score:
            best, best_score = item, score
    return best


def _match_by_content(items: list[DateMenuItem], content: str) -> DateMenuItem | None:
    """模型没给店名时的本地兜底：正文里出现了菜单里的店名就直接认。"""
    text = _norm(content)
    if not text:
        return None

    best: DateMenuItem | None = None
    best_score = 0
    for item in items:
        for key in {_norm(item.name), _norm(_short_name(item))}:
            if len(key) >= 2 and key in text and len(key) > best_score:
                best, best_score = item, len(key)
    return best


def _resolve_restaurant(
    items: list[DateMenuItem],
    extraction: dict,
    content: str,
) -> DateMenuItem | None:
    """id 必须命中菜单；命中不了再看店名，最后看正文。"""
    item = _match_by_id(items, extraction.get("restaurant_id"))
    if item is not None:
        return item
    item = _match_by_name(items, extraction.get("restaurant_name"))
    if item is not None:
        return item
    return _match_by_content(items, content)


def _as_text(value: Any, limit: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y", "是")
    return False


def _as_rating(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value)
    try:
        rating = float(text)
    except ValueError:
        # 模型偶尔写成「4.5 分」「4.5/5」，取第一个数字
        found = re.search(r"\d+(?:\.\d+)?", text)
        if not found:
            return None
        rating = float(found.group())
    if 1 <= rating <= 5:
        return round(rating, 1)
    return None


def _as_dishes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for raw in value:
        dish = _as_text(raw, MAX_DISH_LEN)
        if dish and dish not in out:
            out.append(dish)
        if len(out) >= MAX_DISHES:
            break
    return out


def _as_date(value: Any, fallback: date) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value.strip()[:10])
        except ValueError:
            parsed = None
        if parsed is not None and parsed.year >= 2000:
            return parsed
    return fallback


def _union_dishes(existing: Any, incoming: list[str]) -> list[str]:
    out: list[str] = []
    for raw in list(existing or []) + incoming:
        dish = _as_text(raw, MAX_DISH_LEN)
        if dish and dish not in out:
            out.append(dish)
        if len(out) >= MAX_DISHES:
            break
    return out


async def _all_items(db: AsyncSession) -> list[DateMenuItem]:
    stmt = select(DateMenuItem).order_by(DateMenuItem.sort, DateMenuItem.id)
    return list((await db.execute(stmt)).scalars().all())


async def _find_existing(
    db: AsyncSession,
    *,
    user_id: str,
    item: DateMenuItem | None,
    name: str,
    visited_on: date,
) -> DateVisit | None:
    stmt = select(DateVisit).where(
        DateVisit.user_id == user_id,
        DateVisit.visited_on == visited_on,
    )
    if item is not None:
        # 菜单 id 对得上，或早先只记了同一个店名（当时没关联上）都算同一条
        stmt = stmt.where(
            or_(DateVisit.restaurant_id == item.id, DateVisit.restaurant_name == item.name)
        )
    elif name:
        stmt = stmt.where(DateVisit.restaurant_id.is_(None), DateVisit.restaurant_name == name)
    else:
        return None

    stmt = stmt.order_by(DateVisit.created_at.asc(), DateVisit.id.asc()).limit(1)
    return (await db.execute(stmt)).scalars().first()


def _merge_into(
    row: DateVisit,
    *,
    item: DateMenuItem | None,
    name: str,
    rating: float | None,
    dishes: list[str],
    companion: str,
    occasion: str,
    review: str,
    event_id: str | None,
) -> None:
    """补充说明只增不减：空字段不覆盖已有值，菜名去重合并。"""
    if item is not None:
        row.restaurant_id = item.id
        row.restaurant_name = item.name
        row.branch = item.branch or ""
        row.cuisine = item.cuisine or ""
    elif name and (not row.restaurant_name or len(name) > len(row.restaurant_name)):
        row.restaurant_name = name

    if rating is not None:
        row.rating = rating
    if dishes:
        row.dishes = _union_dishes(row.dishes, dishes)
    if companion:
        row.companion = companion
    if occasion:
        row.occasion = occasion
    if review:
        row.review = review
    if event_id and not row.event_id:
        row.event_id = event_id
    row.updated_at = now_local()


async def apply(
    db: AsyncSession,
    user: User,
    event: Event | None,
    extraction: Any,
    *,
    content: str,
    restaurants: list[DateMenuItem] | None = None,
) -> DateVisit | None:
    """按模型给出的 date_visit 落一条探店记录；不是探店就返回 None。

    模型返回的 `is_visit` 才是语义判定，这里不替模型猜「吃饭」：
    模型说不是（计划、单纯吃了顿饭没提店名）就不写；
    但只要写了具体店名，即使对不上菜单也保留一条 restaurant_id=null 的记录，
    以后可以在后台把店补进菜单，历史不会丢。
    """
    if not isinstance(extraction, dict) or not _as_bool(extraction.get("is_visit")):
        return None

    items = restaurants if restaurants is not None else await _all_items(db)
    item = _resolve_restaurant(items, extraction, content)
    name = item.name if item is not None else _as_text(extraction.get("restaurant_name"), MAX_TEXT)
    if not name:
        # 没提到具体哪家店 → 只是一条普通吃饭事件，events 已经记住了，不建探店记录
        return None

    fallback_date = (event.occurred_on if event and event.occurred_on else today_local())
    visited_on = _as_date(extraction.get("visited_on"), fallback_date)
    if visited_on > today_local():
        # 计划中的饭局不是探店；避免把「周六去吃」记成已经吃过
        return None

    rating = _as_rating(extraction.get("rating"))
    dishes = _as_dishes(extraction.get("dishes"))
    companion = _as_text(extraction.get("companion"), 40)
    occasion = _as_text(extraction.get("occasion"), 40)
    review = _as_text(extraction.get("review"), MAX_REVIEW)
    event_id = event.id if event is not None else None

    existing = await _find_existing(
        db, user_id=user.id, item=item, name=name, visited_on=visited_on
    )
    if existing is not None:
        _merge_into(
            existing,
            item=item,
            name=name,
            rating=rating,
            dishes=dishes,
            companion=companion,
            occasion=occasion,
            review=review,
            event_id=event_id,
        )
        return existing

    row = DateVisit(
        user_id=user.id,
        event_id=event_id,
        restaurant_id=item.id if item is not None else None,
        restaurant_name=item.name if item is not None else name,
        branch=(item.branch or "") if item is not None else "",
        cuisine=(item.cuisine or "") if item is not None else "",
        visited_on=visited_on,
        rating=rating,
        dishes=dishes or None,
        companion=companion or None,
        occasion=occasion or None,
        review=review,
        source="chat",
    )
    db.add(row)
    await db.flush()
    return row
