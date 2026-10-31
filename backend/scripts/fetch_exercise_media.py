"""从 exercises-dataset 拉取匹配的 GIF 到本地媒体目录（不随仓库分发）。

用法：
    cd backend
    python scripts/fetch_exercise_media.py
    python scripts/fetch_exercise_media.py --metadata D:\\exercises.json
    python scripts/fetch_exercise_media.py --base https://你的镜像/raw/

只下载动作库里 54 个动作能匹配上的文件；匹配不到的保持文字。
媒体写入 backend/media/exercises/，并写回 exercises.media_path。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

# 允许 `python scripts/fetch_exercise_media.py` 直接运行（backend 加入 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import async_session
from app.models.exercise import Exercise

DEFAULT_BASE = "https://hk.gh-proxy.com/https://raw.githubusercontent.com/hasaneyldrm/exercises-dataset/main/"
MEDIA_DIR = Path(__file__).resolve().parents[1] / "media" / "exercises"

MAP = {
    "Barbell Bench Press": "barbell bench press",
    "Incline Bench Press": "barbell incline bench press",
    "Dumbbell Bench Press": "dumbbell bench press",
    "Dumbbell Fly": "dumbbell fly",
    "Dips": "chest dip",
    "Push-up": "push-up",
    "Chest Press Machine": "lever chest press",
    "Cable Crossover": "cable standing up straight crossovers",
    "Pull-up": "pull-up",
    "Lat Pulldown": "cable lat pulldown full range of motion",
    "Barbell Row": "barbell bent over row",
    "One-arm Dumbbell Row": "dumbbell one arm bent-over row",
    "Seated Cable Row": "cable seated row",
    "Deadlift": "barbell deadlift",
    "Straight-arm Pulldown": "cable straight arm pulldown",
    "Back Squat": "barbell full squat",
    "Front Squat": "barbell front squat",
    "Leg Press": "sled 45° leg press (side pov)",
    "Romanian Deadlift": "barbell romanian deadlift",
    "Bulgarian Split Squat": "barbell split squat v. 2",
    "Leg Curl": "lever lying leg curl",
    "Leg Extension": "lever leg extension",
    "Calf Raise": "bodyweight standing calf raise",
    "Glute Bridge": "barbell glute bridge",
    "Overhead Press": "barbell seated overhead press",
    "Dumbbell Lateral Raise": "dumbbell lateral raise",
    "Dumbbell Front Raise": "dumbbell front raise",
    "Reverse Fly": "dumbbell reverse fly",
    "Shrug": "dumbbell shrug",
    "Barbell Curl": "barbell curl",
    "Dumbbell Curl": "dumbbell seated curl",
    "Hammer Curl": "dumbbell hammer curl",
    "Triceps Pushdown": "cable triceps pushdown (v-bar)",
    "Close-grip Bench Press": "barbell close-grip bench press",
    "Triceps Extension": "dumbbell seated triceps extension",
    "Plank": "weighted front plank",
    "Side Plank": "bodyweight incline side plank",
    "Crunch": "weighted crunch",
    "Hanging Leg Raise": "hanging leg raise",
    "Russian Twist": "russian twist",
    "Dead Bug": "dead bug",
    "Kettlebell Swing": "kettlebell swing",
    "Burpee": "burpee",
    "Treadmill": "walking on incline treadmill",
    "Elliptical": "walk elliptical cross trainer",
    "Jump Rope": "jump rope",
    "Hip Flexor Stretch": "intermediate hip flexor and quad stretch",
}


async def load_metadata(client: httpx.AsyncClient, base: str, path: str | None) -> list[dict]:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    resp = await client.get(base + "data/exercises.json")
    resp.raise_for_status()
    return resp.json()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", help="本地 exercises.json；不给就自动下载")
    parser.add_argument("--base", default=DEFAULT_BASE, help="GIF/元数据镜像前缀")
    args = parser.parse_args()

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
        data = await load_metadata(client, args.base, args.metadata)
        by_name = {item["name"].lower(): item for item in data}

        async with async_session() as db:
            exercises = (await db.execute(select(Exercise))).scalars().all()
            targets = []
            for exercise in exercises:
                dataset_name = MAP.get(exercise.name_en)
                item = by_name.get(dataset_name.lower()) if dataset_name else None
                if item is not None:
                    targets.append((exercise, item))

            sem = asyncio.Semaphore(4)
            imported = 0
            failed: list[tuple[str, str]] = []

            async def fetch(exercise: Exercise, item: dict) -> None:
                nonlocal imported
                dest = MEDIA_DIR / f"{exercise.id}.gif"
                if dest.exists() and dest.stat().st_size > 1000:
                    exercise.media_path = f"exercises/{dest.name}"
                    imported += 1
                    return
                async with sem:
                    try:
                        resp = await client.get(args.base + item["gif_url"])
                        resp.raise_for_status()
                        if len(resp.content) < 1000:
                            raise ValueError(f"too small: {len(resp.content)}")
                        dest.write_bytes(resp.content)
                        exercise.media_path = f"exercises/{dest.name}"
                        imported += 1
                        print(f"ok   {exercise.name} <- {item['name']}")
                    except Exception as exc:  # noqa: BLE001
                        failed.append((exercise.name, str(exc)))
                        print(f"fail {exercise.name}: {exc}")

            await asyncio.gather(*(fetch(*pair) for pair in targets))
            await db.commit()

    print(f"matched={len(targets)} imported={imported} failed={len(failed)}")
    for name, error in failed[:20]:
        print("  -", name, error)


if __name__ == "__main__":
    asyncio.run(main())
