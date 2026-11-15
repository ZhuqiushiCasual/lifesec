"""地点查询：一张 places 表 + 一个 nearby(anchor, want)。

设计要点（见 docs/设计-地点拓扑-v3.html）：

- **没有方向**。餐厅 → 闲逛、闲逛 → 餐厅是同一个函数，只是 want 不同。
- **没有边表**。步行分钟 = 直线 × 1.3 ÷ 80 米/分；同 parent 按 2 分钟。
  算出来的东西不落库，就不会有「重算覆盖人工边」这种问题。
- **不调模型**。排序必须可复现、可断言；模型只用来补 attrs（哪里要不要爬坡、几点关门）。
- **缺坐标要降级**。没坐标的地点仍可以出现，但排最后、标「未取到坐标」、不写分钟。
"""

from __future__ import annotations

import math
import re
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.date_menu import DateMenuItem
from app.models.date_visit import DateVisit
from app.models.outing_spot import OutingSpot
from app.models.place import Place

# 出门玩表的 kind → places.category
OUTING_CATEGORY = {
    "景点": "play",
    "展馆": "exhibit",
    "公园": "park",
    "街区": "street",
    "活动": "play",
}
CATEGORY_LABEL = {
    "eat": "吃",
    "play": "玩",
    "park": "公园",
    "street": "街区",
    "exhibit": "展馆",
    "shop": "商场",
}

# ── 意图：一个查询的三种参数，不是三条链路 ──────────────────────
WANTS: dict[str, dict] = {
    "stroll": {
        "label": "饭后走走",
        "ok": lambda p: p.category != "eat",
        "fit_tags": {"街区", "公园", "平路", "夜逛", "散步", "湖", "街区散步"},
    },
    "eat": {
        "label": "就近吃",
        "ok": lambda p: p.category == "eat",
        "fit_tags": set(),
    },
    "indoor": {
        "label": "雨天",
        "ok": lambda p: bool((p.attrs or {}).get("indoor")),
        "fit_tags": {"展览", "室内", "商场", "书店"},
    },
}
DEFAULT_WANT = "stroll"


# ── 规范化 ────────────────────────────────────────────────
def _norm(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip()).lower()


def canonical_key(name: str, branch: str = "") -> str:
    """名称|分店。分店不参与去重合并（不同分店是两个地点，各自算距离）。"""
    return f"{_norm(name)}|{_norm(branch)}"


# ── 距离 ──────────────────────────────────────────────────
def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    h = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(h))


WALK_M_PER_MIN = 80.0   # 正常步行
DETOUR = 1.3            # 直线上没有路，绕一点


def walk_minutes(anchor: Place, other: Place) -> Optional[int]:
    """步行分钟；没有坐标返回 None（调用方据此降级，不编距离）。"""
    if anchor.id == other.id:
        return 0
    if anchor.parent_place_id and anchor.parent_place_id == other.parent_place_id:
        return 2  # 同一栋楼：按坐标会得出「相距 0 米」
    if not anchor.has_geo or not other.has_geo:
        return None
    km = haversine_km(anchor.lat, anchor.lng, other.lat, other.lng)  # type: ignore[arg-type]
    return max(2, round(km * DETOUR * 1000 / WALK_M_PER_MIN))


# ── 同步：领域表 → places（幂等，可反复跑）────────────────────
async def sync_from_domain(db: AsyncSession) -> dict:
    """把 date_menu / outing_spots 灌成地点，并把 place_id 写回领域表。

    只覆盖「从领域表带来的字段」，不动已经补好的坐标和 attrs 里的其它键
    （否则每次启动都会把 geo_backfill 的结果冲掉）。
    """
    existing = {
        row.canonical_key: row
        for row in (await db.execute(select(Place))).scalars().all()
    }
    created = updated = linked = 0

    # 餐厅
    for item in (await db.execute(select(DateMenuItem))).scalars().all():
        key = canonical_key(item.name, item.branch)
        place = existing.get(key)
        if place is None:
            place = Place(
                canonical_key=key, name=item.name, branch=item.branch or "",
                category="eat", sub_kind=item.cuisine or "", source="domain", attrs={},
            )
            db.add(place)
            await db.flush()
            existing[key] = place
            created += 1
        else:
            updated += 1
        attrs = dict(place.attrs or {})
        attrs.setdefault("cuisine", item.cuisine or "")
        attrs.setdefault("price", item.price or 0)
        attrs.setdefault("score", item.score or 0)
        attrs.setdefault("taste", [item.taste_light, item.taste_spicy, item.taste_oil])
        attrs.setdefault("note", item.reason or "")
        attrs.setdefault("indoor", True)  # 餐厅都算室内去处
        attrs.setdefault("tags", [t for t in [item.cuisine] if t])
        if item.metro:
            place.metro_station = place.metro_station or item.metro[:80]
        place.attrs = attrs
        place.source = place.source or "domain"
        if place.source_ref != item.id:
            place.source_ref = item.id
        if item.place_id != place.id:
            item.place_id = place.id
            linked += 1

    # 出门玩
    for spot in (await db.execute(select(OutingSpot))).scalars().all():
        key = canonical_key(spot.name, "")
        place = existing.get(key)
        if place is None:
            place = Place(
                canonical_key=key, name=spot.name, branch="",
                category=OUTING_CATEGORY.get(spot.kind, "play"), sub_kind=spot.kind or "",
                area=spot.area or "", source="domain", attrs={},
            )
            db.add(place)
            await db.flush()
            existing[key] = place
            created += 1
        else:
            updated += 1
        attrs = dict(place.attrs or {})
        attrs.setdefault("tags", list(spot.tags or []))
        attrs.setdefault("note", spot.note or "")
        attrs.setdefault("indoor", spot.kind == "展馆")
        place.attrs = attrs
        place.area = place.area or (spot.area or "")
        if place.source_ref != spot.id:
            place.source_ref = spot.id
        if spot.place_id != place.id:
            spot.place_id = place.id
            linked += 1

    await db.commit()
    return {"created": created, "updated": updated, "linked": linked}


# ── 打分 ──────────────────────────────────────────────────
def _tags(p: Place) -> set[str]:
    return set((p.attrs or {}).get("tags") or [])


def _fit(p: Place, want: str) -> float:
    """意图匹配度：标签命中 1.0，类别不对但通过 ok() 的给 0.5。"""
    cfg = WANTS.get(want) or WANTS[DEFAULT_WANT]
    fit_tags = cfg.get("fit_tags") or set()
    if fit_tags and (_tags(p) & fit_tags):
        return 1.0
    if want == "eat":
        return 1.0
    if want == "indoor":
        return 1.0 if (p.attrs or {}).get("indoor") else 0.4
    return 0.5


def _near(walk: Optional[int]) -> float:
    if walk is None:
        return 0.15
    if walk <= 5:
        return 1.0
    if walk <= 10:
        return 0.8
    return 0.5


def score(anchor: Place, p: Place, walk: Optional[int], want: str, visits: int = 0) -> float:
    return round(
        0.40 * _near(walk)
        + 0.30 * _fit(p, want)
        + 0.20 * (1.0 if visits else 0.0)
        + 0.10 * (0.5 if p.area and p.area == anchor.area else 0.0),
        4,
    )


def reason(anchor: Place, p: Place, walk: Optional[int], distance_km: Optional[float] = None) -> str:
    """理由句是拼出来的，不是编出来的：缺一段就少写一段。"""
    if walk is not None:
        head = f"从{anchor.name}走约 {walk} 分钟到{p.name}"
    elif distance_km is not None:
        head = f"从{anchor.name}过去约 {distance_km:g} km"
    else:
        head = f"{p.name}同在{anchor.area or p.area}"
    bits = [head]
    tags = [t for t in (p.attrs or {}).get("tags") or [] if t][:1]
    if tags:
        bits.append(tags[0])
    note = (p.attrs or {}).get("note") or ""
    if note:
        bits.append(note.split("。")[0])
    return "，".join(bits)


# ── 查询 ──────────────────────────────────────────────────
async def _visits_by_place(db: AsyncSession) -> dict[str, int]:
    """去过次数：date_visits 按 restaurant_id 计数，再映射到 place。"""
    rows = (
        await db.execute(
            select(DateVisit.restaurant_id, func.count(DateVisit.id)).group_by(DateVisit.restaurant_id)
        )
    ).all()
    counts = {rid: n for rid, n in rows if rid}
    if not counts:
        return {}
    places = (
        await db.execute(select(Place).where(Place.source_ref.in_(list(counts.keys()))))
    ).scalars().all()
    return {p.id: counts[p.source_ref] for p in places if p.source_ref in counts}


async def nearby(
    db: AsyncSession,
    anchor: Place,
    want: str = DEFAULT_WANT,
    *,
    max_walk: int = 20,
    max_km: float = 6.0,
    limit: int = 5,
    exclude: Iterable[str] = (),
) -> list[dict]:
    """以 anchor 为中心，返回三档候选：走得动 / 更远一点 / 没坐标。

    「更远一点」这一档是刻意加的：39 个点的图很稀，很多餐厅周边 15 分钟里什么都没有。
    与其返回空、或者硬塞一个「同在西湖区」的假邻居，不如老实给「约 2.3 km · 打车 8 分钟」，
    人自己判断去不去。
    """
    if anchor is None:
        return []
    cfg = WANTS.get(want) or WANTS[DEFAULT_WANT]
    skip = set(exclude)
    visits = await _visits_by_place(db)
    rows = (
        await db.execute(select(Place).where(Place.status == "active"))
    ).scalars().all()

    walkable: list[dict] = []
    far: list[dict] = []
    unknown: list[dict] = []

    for p in rows:
        if p.id == anchor.id or p.id in skip:
            continue
        if not cfg["ok"](p):
            continue
        walk = walk_minutes(anchor, p)
        item = {
            "place": p,
            "walk": walk,
            "score": score(anchor, p, walk, want, visits.get(p.id, 0)),
            "visits": visits.get(p.id, 0),
            "distance_km": round(
                haversine_km(anchor.lat, anchor.lng, p.lat, p.lng), 2
            ) if (anchor.has_geo and p.has_geo) else None,
        }
        if walk is None:
            item["tier"] = "unknown"
            unknown.append(item)
        elif walk <= max_walk:
            item["tier"] = "walk"
            walkable.append(item)
        elif item["distance_km"] is not None and item["distance_km"] <= max_km:
            item["tier"] = "far"          # 走不到但打车顺路，最多带 2 个
            far.append(item)
        # 更远的直接不出现：列出来只是噪音

    walkable.sort(key=lambda r: (-r["score"], r["walk"], r["place"].id))
    far.sort(key=lambda r: (r["distance_km"] or 99, r["place"].id))
    unknown.sort(key=lambda r: r["place"].id)

    out = walkable[:limit]
    if len(out) < limit:
        out += far[: min(2, max(0, limit - len(out)))]
    if len(out) < limit:              # 还没有就补没坐标的（最多 2 个，别占满）
        out += unknown[: min(2, max(0, limit - len(out)))]
    return out


async def place_by_ref(db: AsyncSession, kind: str, ref_id: str) -> Optional[Place]:
    """用领域表的 id 找到地点：kind = food / outing。"""
    if kind == "food":
        item = await db.get(DateMenuItem, ref_id)
        if item is None:
            return None
        return await _by_key(db, canonical_key(item.name, item.branch))
    if kind == "outing":
        spot = await db.get(OutingSpot, ref_id)
        if spot is None:
            return None
        return await _by_key(db, canonical_key(spot.name, ""))
    return await db.get(Place, ref_id)


async def _by_key(db: AsyncSession, key: str) -> Optional[Place]:
    return (await db.execute(select(Place).where(Place.canonical_key == key))).scalars().first()


def to_row(anchor: Place, r: dict) -> dict:
    p: Place = r["place"]
    walk = r["walk"]
    tier = r.get("tier", "walk")
    km = r.get("distance_km")
    attrs = p.attrs or {}
    sub_bits = []
    if tier == "unknown":
        if p.area and anchor.area and p.area != anchor.area:
            sub_bits.append(f"在{p.area} · 未取到坐标")
        else:
            sub_bits.append("未取到坐标")
    else:
        tags = [t for t in attrs.get("tags") or [] if t]
        if p.category == "eat":
            cuisine = attrs.get("cuisine") or ""
            if cuisine:
                sub_bits.append(cuisine)
            if attrs.get("price"):
                sub_bits.append(f"人均 {attrs['price']}")
            if r.get("visits"):
                sub_bits.append(f"去过 {r['visits']} 次")
        else:
            if tags:
                sub_bits.append(tags[0])
            if attrs.get("note"):
                sub_bits.append(str(attrs["note"]).split("。")[0][:16])
    return {
        "place_id": p.id,
        "kind": p.kind,                 # food / outing —— 前端拿它直接复用安排流程
        "id": p.source_ref or p.id,     # 领域表 id，安排时用
        "name": p.name,
        "branch": p.branch,
        "category": p.category,
        "category_label": CATEGORY_LABEL.get(p.category, "地点"),
        "area": p.area,
        "tier": tier,                   # walk / far / unknown
        "walk_min": walk,
        "distance_km": km,
        "drive_min": round(km * 3) if (tier == "far" and km) else None,
        "geo_ok": walk is not None,
        "visits": r.get("visits", 0),
        "score": r["score"],
        "sub": " · ".join([b for b in sub_bits if b]),
        "reason": reason(anchor, p, walk if tier != "far" else None, km),
    }


def to_anchor(p: Place) -> dict:
    attrs = p.attrs or {}
    bits = [p.area, attrs.get("cuisine") or "", CATEGORY_LABEL.get(p.category, "")]
    if attrs.get("price"):
        bits.append(f"人均 {attrs['price']}")
    return {
        "place_id": p.id,
        "kind": p.kind,
        "id": p.source_ref or p.id,
        "name": p.name,
        "branch": p.branch,
        "category": p.category,
        "meta": " · ".join([b for b in bits if b]),
        "note": attrs.get("note") or "",
        "geo_ok": p.has_geo,
    }


async def all_places(db: AsyncSession, *, q: str | None = None) -> list[Place]:
    stmt = select(Place).where(Place.status == "active")
    if q:
        stmt = stmt.where(Place.name.like(f"%{q.strip()}%"))
    return (await db.execute(stmt.order_by(Place.category, Place.name))).scalars().all()
