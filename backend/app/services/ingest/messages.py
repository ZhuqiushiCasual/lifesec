"""洞察消息的写入 / 修改 / 删除 / 合并。

消息的真相源仍然是 `events(source=hermes)`；窗口里的那条 `messages(kind=insight)`
是它的渲染副本。两者必须一起改，否则会出现「数据库里改了、窗口里还是旧标题」。

幂等键是 `canonical_url(source_url)`：
同一篇文章被 RSS、搜索结果、转载源各推一次时，后到的会更新同一条事件，
而不是在窗口里堆三张卡。
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SOURCE_HERMES, TYPE_INSIGHT, Event
from app.models.ingest import IngestRun
from app.models.message import KIND_INSIGHT, ROLE_SECRETARY, Message
from app.schemas.ingest import MessageBatchOut, MessageMergeIn, MessageOut, MessagePatch
from app.services.ingest.fetch import canonical_url, parse_datetime
from app.utils import now_local

MAX_DETAIL = 4000
MAX_RAW = 12000


def _v(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _url(item: Any) -> Optional[str]:
    return _v(item, "source_url") or _v(item, "url")


def _key(item: Any) -> str:
    url = canonical_url(_url(item))
    title = str(_v(item, "title") or "").strip()
    return (url or title)[:255]


def _tags(item: Any) -> list[str]:
    raw = [_v(item, "category")] + list(_v(item, "topics") or [])
    out: list[str] = []
    for t in raw:
        s = str(t or "").strip()
        if s and s not in out:
            out.append(s)
    return out[:6]


def _payload_hash(item: Any) -> str:
    parts = [
        str(_v(item, "title") or ""),
        str(_v(item, "summary") or ""),
        str(_v(item, "detail") or ""),
        str(_v(item, "impact") or ""),
        str(_v(item, "importance") or ""),
        str(_v(item, "category") or ""),
        ",".join(str(x) for x in (_v(item, "topics") or [])),
    ]
    return "sha256:" + hashlib.sha256("\n".join(parts).encode("utf-8", errors="ignore")).hexdigest()[:24]


def _iso(value: Any) -> Optional[str]:
    dt = parse_datetime(value)
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def _summary(item: Any, detail: str) -> str:
    summary = str(_v(item, "summary") or "").strip()
    if summary:
        return summary[:600]
    return detail[:240]


def _entities(item: Any, *, task_id: Optional[str] = None) -> dict[str, Any]:
    detail = str(_v(item, "detail") or _v(item, "content") or "").strip()[:MAX_RAW]
    return {
        "source_key": _v(item, "source_key"),
        "source_name": _v(item, "source_name"),
        "source_url": canonical_url(_url(item)) or _url(item),
        "published_at": _iso(_v(item, "published_at")),
        "category": _v(item, "category"),
        "topics": list(_v(item, "topics") or []),
        "impact": _v(item, "impact"),
        "importance": int(_v(item, "importance") or 3),
        "summary": _summary(item, detail),
        "detail": detail[:MAX_DETAIL],
        "raw_content": detail,
        "fetch_level": _v(item, "fetch_level"),
        "raw_hash": _v(item, "raw_hash"),
        "batch_id": _v(item, "batch_id"),
        "task_id": task_id or _v(item, "task_id"),
        "status": _v(item, "status") or "new",
        "payload_hash": _payload_hash(item),
    }


def _card(event: Event) -> dict[str, Any]:
    ent = event.entities or {}
    summary = ent.get("summary") or event.content or ""
    impact = ent.get("impact") or ""
    lines = [summary]
    if impact:
        lines.append(f"影响：{impact}")
    return {
        "kind": "insight",
        "title": event.title or summary[:40],
        "lines": [line for line in lines if line],
        "meta": {
            "source_url": ent.get("source_url"),
            "source_name": ent.get("source_name"),
            "source_key": ent.get("source_key"),
            "category": ent.get("category"),
            "importance": ent.get("importance", 3),
            "impact": ent.get("impact") or "",
            "tags": event.tags or [],
            "event_id": event.id,
            "summary": summary,
            "detail": ent.get("detail") or "",
            "published_at": ent.get("published_at"),
            "status": ent.get("status", "new"),
            "fetch_level": ent.get("fetch_level"),
            "task_id": ent.get("task_id"),
            "merged_from": ent.get("merged_from") or [],
        },
    }


async def _message_for(db: AsyncSession, event_id: str) -> Optional[Message]:
    return (
        await db.execute(
            select(Message)
            .where(Message.ref_event_id == event_id, Message.kind == KIND_INSIGHT)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _sync_message(db: AsyncSession, event: Event) -> Optional[Message]:
    msg = await _message_for(db, event.id)
    if msg is None:
        return None
    msg.content = event.title or (event.entities or {}).get("summary") or event.content
    msg.card = _card(event)
    return msg


def _apply(event: Event, item: Any, *, task_id: Optional[str] = None) -> None:
    now = now_local()
    old = dict(event.entities or {})
    new = _entities(item, task_id=task_id)
    # 更新时保留第一次记到它的信息；合并来源只在 merge 接口里追加
    new["merged_from"] = old.get("merged_from") or []
    if not _v(item, "status"):
        # 更新一篇已读 / 已隐藏的消息，不应该把状态打回 new
        new["status"] = old.get("status") or "new"
    event.content = new["summary"] or new["detail"] or event.content
    event.title = str(_v(item, "title") or event.title or "")[:255]
    event.tags = _tags(item) or event.tags
    event.entities = {**old, **new}
    event.last_at = now


async def upsert_items(
    db: AsyncSession,
    user_id: str,
    items: list[Any],
    *,
    task_id: Optional[str] = None,
) -> MessageBatchOut:
    out = MessageBatchOut()
    now = now_local()
    per_source: dict[str, list[int]] = {}   # source_key -> [new, updated]

    def _bump(source_key: Optional[str], index: int) -> None:
        if not source_key:
            return
        counts = per_source.setdefault(source_key, [0, 0])
        counts[index] += 1

    for raw in items:
        title = str(_v(raw, "title") or "").strip()
        key = _key(raw)
        if not title or not key:
            out.errors.append("缺少 title 或 source_url/title")
            continue

        existing = (
            await db.execute(
                select(Event).where(
                    Event.user_id == user_id,
                    Event.source == SOURCE_HERMES,
                    Event.dedup_key == key,
                )
            )
        ).scalar_one_or_none()

        payload = _payload_hash(raw)
        if existing is not None:
            if (existing.entities or {}).get("payload_hash") == payload:
                out.skipped += 1
                out.event_ids.append(existing.id)   # 幂等命中时也回传已有事件，方便调用方关联
                continue
            _apply(existing, raw, task_id=task_id)
            await _sync_message(db, existing)
            out.updated += 1
            out.event_ids.append(existing.id)
            _bump(existing.entities.get("source_key"), 1)
            continue

        detail = str(_v(raw, "detail") or _v(raw, "content") or "").strip()[:MAX_RAW]
        ent = _entities(raw, task_id=task_id)
        event = Event(
            user_id=user_id,
            source=SOURCE_HERMES,
            type=TYPE_INSIGHT,
            content=ent["summary"] or detail,
            title=title[:255],
            dedup_key=key,
            tags=_tags(raw) or None,
            occurred_on=now.date(),
            recorded_at=now,
            last_at=now,
            merged_count=1,
            entities=ent,
        )
        db.add(event)
        await db.flush()

        msg = Message(
            user_id=user_id,
            role=ROLE_SECRETARY,
            kind=KIND_INSIGHT,
            content=event.title,
            card=_card(event),
            ref_event_id=event.id,
        )
        db.add(msg)
        await db.flush()
        out.created += 1
        out.event_ids.append(event.id)
        _bump(ent.get("source_key"), 0)

    # 让工作台的「新增 / 更新」与实际写库数一致：
    # runner 上报时只知道抓到几条，消息落库后才知道其中几条是新的。
    if task_id:
        for source_key, (new, updated) in per_source.items():
            run = (
                await db.execute(
                    select(IngestRun)
                    .where(IngestRun.task_id == task_id, IngestRun.source_key == source_key)
                    .order_by(IngestRun.started_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if run is not None:
                run.items_new += new
                run.items_updated += updated

    out.accepted = out.created + out.updated
    await db.commit()
    return out


def event_out(event: Event, message_id: Optional[str] = None) -> MessageOut:
    ent = event.entities or {}
    return MessageOut(
        event_id=event.id,
        message_id=message_id,
        title=event.title or "",
        summary=ent.get("summary") or event.content or "",
        detail=ent.get("detail"),
        source_url=ent.get("source_url"),
        source_name=ent.get("source_name"),
        source_key=ent.get("source_key"),
        category=ent.get("category"),
        topics=list(ent.get("topics") or []),
        impact=ent.get("impact"),
        importance=int(ent.get("importance") or 3),
        published_at=parse_datetime(ent.get("published_at")),
        status=ent.get("status") or "new",
        tags=list(event.tags or []),
        created_at=event.recorded_at or event.created_at,
        updated_at=event.last_at,
    )


async def _get_event(db: AsyncSession, user_id: str, event_id: str) -> Event:
    event = (
        await db.execute(
            select(Event).where(
                Event.id == event_id,
                Event.user_id == user_id,
                Event.source == SOURCE_HERMES,
            )
        )
    ).scalar_one_or_none()
    if event is None:
        raise LookupError("没有这条消息")
    return event


async def get_event_out(db: AsyncSession, user_id: str, event_id: str) -> MessageOut:
    event = await _get_event(db, user_id, event_id)
    msg = await _message_for(db, event.id)
    return event_out(event, msg.id if msg else None)


async def update_event(db: AsyncSession, user_id: str, event_id: str, patch: MessagePatch) -> MessageOut:
    event = await _get_event(db, user_id, event_id)
    ent = dict(event.entities or {})
    data = patch.model_dump(exclude_unset=True)

    if "title" in data and data["title"] is not None:
        event.title = str(data["title"])[:255]
    if "summary" in data and data["summary"] is not None:
        ent["summary"] = str(data["summary"])[:600]
        event.content = ent["summary"]
    if "detail" in data and data["detail"] is not None:
        ent["detail"] = str(data["detail"])[:MAX_DETAIL]
        ent["raw_content"] = str(data["detail"])[:MAX_RAW]
    for field in ("impact", "category", "source_url", "source_name", "status"):
        if field in data:
            ent[field] = (
                canonical_url(data[field]) or data[field]
                if field == "source_url"
                else data[field]
            )
    if data.get("source_url"):
        event.dedup_key = canonical_url(data["source_url"])[:255]
    if "topics" in data and data["topics"] is not None:
        ent["topics"] = list(data["topics"])
    if "importance" in data and data["importance"] is not None:
        ent["importance"] = int(data["importance"])

    if "category" in data or "topics" in data:
        event.tags = _tags(
            {
                "category": ent.get("category"),
                "topics": ent.get("topics") or [],
            }
        )
    ent["payload_hash"] = _payload_hash(
        {
            "title": event.title,
            "summary": ent.get("summary"),
            "detail": ent.get("detail"),
            "impact": ent.get("impact"),
            "importance": ent.get("importance"),
            "category": ent.get("category"),
            "topics": ent.get("topics") or [],
        }
    )
    event.entities = ent
    event.last_at = now_local()
    msg = await _sync_message(db, event)
    await db.commit()
    return event_out(event, msg.id if msg else None)


async def delete_event(db: AsyncSession, user_id: str, event_id: str) -> None:
    event = await _get_event(db, user_id, event_id)
    msgs = (
        await db.execute(select(Message).where(Message.ref_event_id == event.id))
    ).scalars().all()
    for m in msgs:
        await db.delete(m)
    await db.delete(event)
    await db.commit()


async def merge_events(db: AsyncSession, user_id: str, payload: MessageMergeIn) -> MessageOut:
    primary = await _get_event(db, user_id, payload.primary_id)
    dup_ids = [i for i in payload.duplicate_ids if i and i != primary.id]
    if not dup_ids:
        raise LookupError("没有可合并的重复消息")
    # 任一 id 不存在就整次拒绝：合并是破坏性操作，不能「合了一半」
    dups = [await _get_event(db, user_id, event_id) for event_id in dup_ids]

    ent = dict(primary.entities or {})
    merged_from = list(ent.get("merged_from") or []) + [d.id for d in dups]
    tags: list[str] = list(primary.tags or [])
    topics: list[str] = list(ent.get("topics") or [])
    details: list[str] = [ent.get("detail") or ""]

    for dup in dups:
        dent = dup.entities or {}
        for t in dup.tags or []:
            if t not in tags:
                tags.append(t)
        for t in dent.get("topics") or []:
            if t not in topics:
                topics.append(t)
        if dent.get("detail"):
            details.append(dent["detail"])
        merged_from += list(dent.get("merged_from") or [])
        msgs = (
            await db.execute(select(Message).where(Message.ref_event_id == dup.id))
        ).scalars().all()
        for m in msgs:
            await db.delete(m)
        await db.delete(dup)

    ent["topics"] = topics[:8]
    ent["merged_from"] = list(dict.fromkeys(merged_from))
    ent["detail"] = "\n\n---\n\n".join(d for d in details if d)[:MAX_DETAIL]
    primary.entities = ent
    primary.tags = tags[:8]
    if payload.title:
        primary.title = payload.title[:255]
    primary.last_at = now_local()
    msg = await _sync_message(db, primary)
    await db.commit()
    return event_out(primary, msg.id if msg else None)


async def list_events(
    db: AsyncSession,
    user_id: str,
    *,
    limit: int = 100,
    source_key: Optional[str] = None,
    include_hidden: bool = False,
) -> list[MessageOut]:
    rows = (
        await db.execute(
            select(Event)
            .where(Event.user_id == user_id, Event.source == SOURCE_HERMES)
            .order_by(Event.recorded_at.desc(), Event.id.desc())
            .limit(max(limit * 3, 100))
        )
    ).scalars().all()

    # 一次查完这些事件对应的窗口消息，避免逐条查库（列表接口会一次返回上百条）
    msg_rows = (
        await db.execute(
            select(Message.id, Message.ref_event_id).where(
                Message.ref_event_id.in_([e.id for e in rows])
            )
        )
    ).all()
    msg_ids = {ref_id: msg_id for msg_id, ref_id in msg_rows}

    out: list[MessageOut] = []
    for event in rows:
        ent = event.entities or {}
        if source_key and ent.get("source_key") != source_key:
            continue
        if not include_hidden and ent.get("status") == "hidden":
            continue
        out.append(event_out(event, msg_ids.get(event.id)))
        if len(out) >= limit:
            break
    return out
