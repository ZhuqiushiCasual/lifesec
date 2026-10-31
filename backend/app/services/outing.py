"""出门玩候选：种子 + 查询。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outing_spot import OutingSpot

# 杭州的一组常用候选；只作「想去哪」的起点，不替用户决定
OUTING_SEED: list[tuple[str, str, str, str, list[str]]] = [
    ("西湖", "景点", "西湖区", "沿湖走一段，傍晚光线最好", ["湖", "散步", "免费"]),
    ("宝石山", "景点", "西湖区", "爬升不大，看保俶塔和城市天际线", ["爬山", "日落"]),
    ("灵隐寺", "景点", "西湖区", "早点去，避开中午的人流", ["寺庙", "安静"]),
    ("浙江省博物馆", "展馆", "上城区", "之江馆区，常设展够看半天", ["展览", "室内"]),
    ("浙江美术馆", "展馆", "西湖区", "看展 + 南山路散步可以连起来", ["展览", "室内"]),
    ("天目里", "街区", "西湖区", "书店、咖啡和建筑本身都值得逛", ["街区", "咖啡"]),
    ("南宋御街", "街区", "上城区", "晚上灯亮起来之后更好走", ["街区", "夜逛"]),
    ("吴山广场", "街区", "上城区", "上山看城隍阁，顺路吃小吃", ["爬山", "小吃"]),
    ("良渚古城遗址公园", "公园", "余杭区", "园区大，留半天，带防晒", ["公园", "遗址"]),
    ("西溪湿地", "公园", "西湖区", "坐船比走路省力，秋天最好", ["公园", "坐船"]),
    ("湘湖", "公园", "萧山区", "人比西湖少，适合骑车", ["公园", "骑行"]),
    ("中国美术学院象山校区", "展馆", "西湖区", "建筑和校园都值得慢慢走", ["校园", "建筑"]),
]


async def ensure_seed(db: AsyncSession) -> int:
    existing = set((await db.execute(select(OutingSpot.name))).scalars().all())
    added = 0
    for index, (name, kind, area, note, tags) in enumerate(OUTING_SEED):
        if name in existing:
            continue
        db.add(
            OutingSpot(
                name=name, kind=kind, area=area, note=note, tags=tags,
                sort=index, source="seed",
            )
        )
        added += 1
    if added:
        await db.commit()
    return added


async def options(db: AsyncSession, q: str | None = None) -> list[dict]:
    stmt = select(OutingSpot).where(OutingSpot.hidden.is_(False))
    if q:
        stmt = stmt.where(OutingSpot.name.like(f"%{q.strip()}%"))
    rows = (
        await db.execute(stmt.order_by(OutingSpot.sort, OutingSpot.id))
    ).scalars().all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "kind": row.kind,
            "area": row.area,
            "note": row.note,
            "tags": list(row.tags or []),
        }
        for row in rows
    ]
