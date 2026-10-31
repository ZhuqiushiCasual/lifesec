"""训练日志 —— 动作库、落库、详情与统计。

判定在对话的那一次生成里完成（`workout.is_workout`）；这里只做：
  ① 动作名匹配（动作库 / 别名，匹配不到保留快照）
  ② 数字与日期校验
  ③ 按「事件 → 训练」去重，补充时整体重建组明细
  ④ 详情、上次某动作、区间统计
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import case, delete, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.exercise import Exercise
from app.models.user import User
from app.models.workout import Workout, WorkoutSet
from app.utils import today_local

# 常见动作种子：中文名 / 英文名 / 部位 / 器械 / 主要肌群 / 别名
EXERCISE_SEED: list[tuple[str, str, str, str, str, list[str]]] = [
    ("卧推", "Barbell Bench Press", "胸", "杠铃", "胸大肌", ["平板卧推", "bench press"]),
    ("上斜卧推", "Incline Bench Press", "胸", "杠铃", "上胸", ["incline press"]),
    ("哑铃卧推", "Dumbbell Bench Press", "胸", "哑铃", "胸大肌", ["dumbbell press"]),
    ("哑铃飞鸟", "Dumbbell Fly", "胸", "哑铃", "胸大肌", ["飞鸟", "fly"]),
    ("双杠臂屈伸", "Dips", "胸", "自重", "下胸 / 三头", ["dips"]),
    ("俯卧撑", "Push-up", "胸", "自重", "胸大肌", ["push up"]),
    ("器械推胸", "Chest Press Machine", "胸", "器械", "胸大肌", ["推胸机"]),
    ("绳索夹胸", "Cable Crossover", "胸", "绳索", "胸大肌", ["夹胸"]),
    ("引体向上", "Pull-up", "背", "自重", "背阔肌", ["pull up"]),
    ("高位下拉", "Lat Pulldown", "背", "器械", "背阔肌", ["下拉"]),
    ("杠铃划船", "Barbell Row", "背", "杠铃", "背阔肌 / 斜方肌", ["划船"]),
    ("哑铃单臂划船", "One-arm Dumbbell Row", "背", "哑铃", "背阔肌", ["单臂划船"]),
    ("坐姿划船", "Seated Cable Row", "背", "绳索", "背阔肌", ["坐姿划船"]),
    ("硬拉", "Deadlift", "背", "杠铃", "竖脊肌 / 臀腿", ["deadlift"]),
    ("直臂下压", "Straight-arm Pulldown", "背", "绳索", "背阔肌", ["直臂下拉"]),
    ("深蹲", "Back Squat", "腿", "杠铃", "股四头肌 / 臀", ["squat"]),
    ("前蹲", "Front Squat", "腿", "杠铃", "股四头肌", ["front squat"]),
    ("腿举", "Leg Press", "腿", "器械", "股四头肌", ["leg press"]),
    ("罗马尼亚硬拉", "Romanian Deadlift", "腿", "杠铃", "腘绳肌 / 臀", ["RDL"]),
    ("保加利亚分腿蹲", "Bulgarian Split Squat", "腿", "哑铃", "股四头肌 / 臀", ["分腿蹲"]),
    ("腿弯举", "Leg Curl", "腿", "器械", "腘绳肌", ["leg curl"]),
    ("腿屈伸", "Leg Extension", "腿", "器械", "股四头肌", ["leg extension"]),
    ("提踵", "Calf Raise", "腿", "器械", "小腿", ["calf raise"]),
    ("臀桥", "Glute Bridge", "臀", "自重", "臀大肌", ["glute bridge"]),
    ("髋推", "Hip Thrust", "臀", "杠铃", "臀大肌", ["hip thrust"]),
    ("侧抬腿", "Side Leg Raise", "臀", "自重", "臀中肌", ["侧卧抬腿"]),
    ("肩推", "Overhead Press", "肩", "杠铃", "三角肌", ["推肩", "ohp"]),
    ("哑铃侧平举", "Lateral Raise", "肩", "哑铃", "三角肌中束", ["侧平举"]),
    ("哑铃前平举", "Front Raise", "肩", "哑铃", "三角肌前束", ["前平举"]),
    ("俯身飞鸟", "Reverse Fly", "肩", "哑铃", "三角肌后束", ["反向飞鸟"]),
    ("面拉", "Face Pull", "肩", "绳索", "三角肌后束", ["face pull"]),
    ("耸肩", "Shrug", "肩", "哑铃", "斜方肌", ["shrug"]),
    ("杠铃弯举", "Barbell Curl", "手臂", "杠铃", "肱二头肌", ["弯举"]),
    ("哑铃弯举", "Dumbbell Curl", "手臂", "哑铃", "肱二头肌", ["dumbbell curl"]),
    ("锤式弯举", "Hammer Curl", "手臂", "哑铃", "肱肌", ["hammer curl"]),
    ("绳索下压", "Triceps Pushdown", "手臂", "绳索", "肱三头肌", ["三头下压"]),
    ("窄距卧推", "Close-grip Bench Press", "手臂", "杠铃", "肱三头肌", ["窄推"]),
    ("臂屈伸", "Triceps Extension", "手臂", "哑铃", "肱三头肌", ["三头"]),
    ("平板支撑", "Plank", "核心", "自重", "腹横肌", ["plank"]),
    ("侧平板", "Side Plank", "核心", "自重", "腹斜肌", ["side plank"]),
    ("卷腹", "Crunch", "核心", "自重", "腹直肌", ["crunch"]),
    ("悬垂举腿", "Hanging Leg Raise", "核心", "自重", "下腹", ["举腿"]),
    ("俄罗斯转体", "Russian Twist", "核心", "自重", "腹斜肌", ["转体"]),
    ("死虫", "Dead Bug", "核心", "自重", "核心稳定", ["dead bug"]),
    ("鸟狗", "Bird Dog", "核心", "自重", "核心稳定", ["bird dog"]),
    ("壶铃摆荡", "Kettlebell Swing", "全身", "其他", "臀 / 核心", ["壶铃"]),
    ("波比跳", "Burpee", "全身", "自重", "全身", ["burpee"]),
    ("划船机", "Rowing Machine", "全身", "器械", "全身 / 心肺", ["划船机"]),
    ("跑步机", "Treadmill", "全身", "器械", "心肺", ["跑步"]),
    ("椭圆机", "Elliptical", "全身", "器械", "心肺", ["椭圆"]),
    ("跳绳", "Jump Rope", "全身", "其他", "心肺 / 小腿", ["跳绳"]),
    ("爬楼机", "Stair Climber", "全身", "器械", "心肺 / 臀腿", ["爬楼"]),
    ("猫牛式", "Cat-Cow", "核心", "自重", "脊柱活动", ["猫牛"]),
    ("髋屈肌拉伸", "Hip Flexor Stretch", "腿", "自重", "髋前侧", ["拉伸"]),
]

MAX_WEIGHT = 1000.0
MAX_REPS = 100
MAX_SETS = 30
MAX_TOTAL_SETS = 80

_NORM = re.compile(r"[\s·・•|_\-—（）()【】\[\]「」,，。.!！?？:：/]+")


def _norm(value: Any) -> str:
    return _NORM.sub("", str(value or "")).lower()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y", "是")
    return False


def _as_int(value: Any, lo: int, hi: int) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(float(str(value)))
    except (TypeError, ValueError):
        found = re.search(r"\d+", str(value))
        if not found:
            return None
        number = int(found.group())
    return min(max(number, lo), hi)


def _as_float(value: Any, lo: float, hi: float) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        found = re.search(r"\d+(?:\.\d+)?", str(value))
        if not found:
            return None
        number = float(found.group())
    return round(min(max(number, lo), hi), 2)


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


def _match_exercise(name: str, exercises: list[Exercise]) -> Exercise | None:
    key = _norm(name)
    if not key:
        return None
    for ex in exercises:
        for candidate in [ex.name, ex.name_en, *(ex.aliases or [])]:
            if _norm(candidate) == key:
                return ex
    for ex in exercises:
        if key in _norm(ex.name) or _norm(ex.name) in key:
            return ex
    return None


async def ensure_seed(db: AsyncSession) -> int:
    existing = set((await db.execute(select(Exercise.name))).scalars().all())
    added = 0
    for name, name_en, body, equipment, target, aliases in EXERCISE_SEED:
        if name in existing:
            continue
        db.add(
            Exercise(
                name=name, name_en=name_en, body_part=body, equipment=equipment,
                target=target, aliases=aliases, source="seed",
            )
        )
        added += 1
    if added:
        await db.commit()
    return added


async def all_exercises(db: AsyncSession) -> list[Exercise]:
    return list(
        (await db.execute(select(Exercise).order_by(Exercise.body_part, Exercise.name))).scalars().all()
    )


async def apply(
    db: AsyncSession,
    user: User,
    event: Event | None,
    extraction: Any,
    *,
    content: str,
) -> tuple[Workout | None, list[str]]:
    """按模型给出的 workout 落一次训练；不是训练返回 (None, [])。"""
    if not isinstance(extraction, dict) or not _as_bool(extraction.get("is_workout")):
        return None, []

    fallback_date = event.occurred_on if event and event.occurred_on else today_local()
    performed_on = _as_date(extraction.get("performed_on"), fallback_date)
    if performed_on > today_local():
        return None, []  # 计划中的训练不是已发生记录

    raw_items = extraction.get("exercises")
    if not isinstance(raw_items, list) or not raw_items:
        return None, []

    exercises = await all_exercises(db)
    title = str(extraction.get("title") or "训练").strip()[:120] or "训练"
    place = str(extraction.get("place") or "").strip()[:120]
    duration = _as_int(extraction.get("duration_min"), 0, 600)
    notes = str(extraction.get("notes") or "").strip()[:2000]
    event_id = event.id if event is not None else None

    existing: Workout | None = None
    if event_id:
        existing = (
            await db.execute(
                select(Workout).where(Workout.user_id == user.id, Workout.event_id == event_id)
            )
        ).scalars().first()
    if existing is None:
        existing = (
            await db.execute(
                select(Workout).where(
                    Workout.user_id == user.id,
                    Workout.performed_on == performed_on,
                    func.lower(Workout.title) == title.lower(),
                )
            )
        ).scalars().first()

    workout = existing or Workout(user_id=user.id, performed_on=performed_on)
    workout.event_id = event_id or workout.event_id
    workout.performed_on = performed_on
    workout.title = title
    workout.place = place or workout.place
    workout.duration_min = duration if duration is not None else workout.duration_min
    workout.notes = notes or workout.notes
    workout.source = "chat"
    if existing is None:
        db.add(workout)
    await db.flush()

    # 补充时整体重建这一天的组明细：模型返回的是合并后的完整版本
    await db.execute(delete(WorkoutSet).where(WorkoutSet.workout_id == workout.id))

    lines: list[str] = []
    total = 0
    for exercise_order, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("exercise_name") or raw.get("name") or "").strip()[:120]
        if not name:
            continue
        matched = _match_exercise(name, exercises)
        set_count = _as_int(raw.get("sets"), 1, MAX_SETS) or 1
        reps = _as_int(raw.get("reps"), 1, MAX_REPS)
        weight = _as_float(raw.get("weight_kg"), 0, MAX_WEIGHT)
        duration_sec = _as_int(raw.get("duration_sec"), 1, 3600)
        rpe = _as_float(raw.get("rpe"), 1, 10)

        for index in range(1, set_count + 1):
            if total >= MAX_TOTAL_SETS:
                break
            db.add(
                WorkoutSet(
                    workout_id=workout.id,
                    exercise_id=matched.id if matched is not None else None,
                    exercise_name=matched.name if matched is not None else name,
                    exercise_order=exercise_order,
                    set_index=index,
                    weight_kg=weight,
                    reps=reps,
                    duration_sec=duration_sec,
                    rpe=rpe,
                    is_warmup=_as_bool(raw.get("is_warmup")),
                )
            )
            total += 1

        bit = f"{matched.name if matched is not None else name} {set_count} 组"
        if reps:
            bit += f" × {reps}"
        if weight is not None:
            bit += f" · {weight:g}kg"
        if duration_sec:
            bit += f" · {duration_sec} 秒"
        lines.append(bit)
        if total >= MAX_TOTAL_SETS:
            break

    if total == 0:
        return None, []
    await db.flush()
    return workout, lines


async def by_events(db: AsyncSession, user: User, event_ids: list[str]) -> dict[str, Workout]:
    if not event_ids:
        return {}
    rows = (
        await db.execute(
            select(Workout).where(
                Workout.user_id == user.id, Workout.event_id.in_(event_ids)
            )
        )
    ).scalars().all()
    return {row.event_id: row for row in rows if row.event_id}


def _set_dict(row: WorkoutSet) -> dict:
    return {
        "set_index": row.set_index,
        "weight_kg": row.weight_kg,
        "reps": row.reps,
        "duration_sec": row.duration_sec,
        "rpe": row.rpe,
        "is_warmup": row.is_warmup,
        "note": row.note,
    }


async def detail(db: AsyncSession, user: User, workout_id: str) -> dict | None:
    workout = (
        await db.execute(
            select(Workout).where(Workout.id == workout_id, Workout.user_id == user.id)
        )
    ).scalars().first()
    if workout is None:
        return None
    rows = (
        await db.execute(
            select(WorkoutSet)
            .where(WorkoutSet.workout_id == workout.id)
            .order_by(WorkoutSet.exercise_order.asc(), WorkoutSet.set_index.asc(), WorkoutSet.id.asc())
        )
    ).scalars().all()

    exercise_ids = {row.exercise_id for row in rows if row.exercise_id}
    media: dict[str, str] = {}
    if exercise_ids:
        exercise_rows = (
            await db.execute(select(Exercise).where(Exercise.id.in_(exercise_ids)))
        ).scalars().all()
        media = {row.id: row.media_path for row in exercise_rows}

    grouped: list[dict] = []
    index: dict[str, dict] = {}
    for row in rows:
        key = row.exercise_name or "动作"
        if key not in index:
            item = {
                "exercise_id": row.exercise_id,
                "exercise_name": key,
                "media_path": media.get(row.exercise_id or "", ""),
                "sets": [],
            }
            index[key] = item
            grouped.append(item)
        index[key]["sets"].append(_set_dict(row))

    volume = sum(
        (row.weight_kg or 0) * (row.reps or 0)
        for row in rows
        if row.weight_kg is not None and row.reps is not None
    )
    return {
        "id": workout.id,
        "title": workout.title,
        "performed_on": workout.performed_on,
        "place": workout.place,
        "duration_min": workout.duration_min,
        "notes": workout.notes,
        "exercises": grouped,
        "total_volume": round(volume, 1),
    }


async def last_for_exercise(db: AsyncSession, user: User, exercise: str) -> dict | None:
    like = f"%{exercise.strip()}%"
    row = (
        await db.execute(
            select(WorkoutSet, Workout)
            .join(Workout, Workout.id == WorkoutSet.workout_id)
            .where(
                Workout.user_id == user.id,
                WorkoutSet.exercise_name.like(like),
                Workout.performed_on <= today_local(),
            )
            .order_by(Workout.performed_on.desc(), WorkoutSet.id.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    workout_set, workout = row
    return {
        "exercise_name": workout_set.exercise_name,
        "weight_kg": workout_set.weight_kg,
        "reps": workout_set.reps,
        "performed_on": workout.performed_on,
        "workout_id": workout.id,
    }


async def stats(
    db: AsyncSession,
    user: User,
    *,
    exercise: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    stmt = (
        select(
            func.count(distinct(Workout.id)),
            func.max(WorkoutSet.weight_kg),
            func.sum(WorkoutSet.weight_kg * WorkoutSet.reps),
        )
        .select_from(WorkoutSet)
        .join(Workout, Workout.id == WorkoutSet.workout_id)
        .where(Workout.user_id == user.id)
    )
    if exercise:
        stmt = stmt.where(WorkoutSet.exercise_name.like(f"%{exercise.strip()}%"))
    if date_from is not None:
        stmt = stmt.where(Workout.performed_on >= date_from)
    if date_to is not None:
        stmt = stmt.where(Workout.performed_on <= date_to)
    workouts, max_weight, volume = (await db.execute(stmt)).one()
    return {
        "workout_count": int(workouts or 0),
        "max_weight_kg": max_weight,
        "total_volume": round(float(volume or 0), 1),
    }


async def options(
    db: AsyncSession,
    *,
    q: str | None = None,
    body_part: str | None = None,
    equipment: str | None = None,
) -> list[dict]:
    stmt = select(Exercise)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Exercise.name.like(like), Exercise.name_en.like(like)))
    if body_part:
        stmt = stmt.where(Exercise.body_part == body_part)
    if equipment:
        stmt = stmt.where(Exercise.equipment == equipment)
    body_order = case(
        (Exercise.body_part == "胸", 1),
        (Exercise.body_part == "背", 2),
        (Exercise.body_part == "腿", 3),
        (Exercise.body_part == "臀", 4),
        (Exercise.body_part == "肩", 5),
        (Exercise.body_part == "手臂", 6),
        (Exercise.body_part == "核心", 7),
        else_=9,
    )
    rows = (
        await db.execute(stmt.order_by(body_order, Exercise.name))
    ).scalars().all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "name_en": row.name_en,
            "body_part": row.body_part,
            "equipment": row.equipment,
            "target": row.target,
            "media_path": row.media_path,
        }
        for row in rows
    ]
