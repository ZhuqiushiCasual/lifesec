"""动作演示媒体导入（本地运行，媒体不随仓库分发）。

用法：
    python -m app.services.fitness_media --source D:\\gifs
    python -m app.services.fitness_media --source D:\\exercises.zip

按文件名匹配动作的英文名 / 中文名（忽略大小写、空格与标点），
复制到 backend/media/exercises/{exercise_id}.gif，并写回 exercises.media_path。
匹配不到的文件会列出来；没有媒体的动作在训练详情里只显示文字。

许可提示：exercises-dataset 的元数据是 MIT，图片/动画版权存在争议。
本脚本只处理你本地已有的文件，不下载、不分发媒体。
"""

from __future__ import annotations

import argparse
import re
import shutil
import zipfile
from pathlib import Path

from sqlalchemy import select

from app.database import async_session
from app.models.exercise import Exercise

MEDIA_DIR = Path(__file__).resolve().parents[2] / "media" / "exercises"
SUFFIXES = {".gif", ".png", ".jpg", ".jpeg", ".webp", ".mp4"}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def _iter_source(source: Path):
    """产出 (文件名, 读取函数)。目录与 zip 统一成同一种形式。"""
    if source.is_dir():
        for path in sorted(source.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUFFIXES:
                yield path.name, path.read_bytes
        return
    if source.is_file() and source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as zf:
            for name in zf.namelist():
                if name.endswith("/") or Path(name).suffix.lower() not in SUFFIXES:
                    continue
                yield Path(name).name, (lambda n=name: zf.read(n))
        return
    raise SystemExit("--source 必须是目录或 .zip")


async def _run(source: Path) -> None:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    async with async_session() as db:
        exercises = (await db.execute(select(Exercise))).scalars().all()
        by_key: dict[str, Exercise] = {}
        for ex in exercises:
            for key in (ex.name_en, ex.name):
                slug = _slug(key)
                if slug:
                    by_key.setdefault(slug, ex)

        matched = 0
        unmatched: list[str] = []
        for filename, read in _iter_source(source):
            stem = Path(filename).stem
            slug = _slug(stem)
            ex = by_key.get(slug)
            if ex is None:
                unmatched.append(filename)
                continue
            suffix = Path(filename).suffix.lower()
            dest = MEDIA_DIR / f"{ex.id}{suffix}"
            dest.write_bytes(read())
            ex.media_path = f"exercises/{dest.name}"
            matched += 1

        await db.commit()

    print(f"matched={matched} media_dir={MEDIA_DIR}")
    if unmatched:
        print(f"unmatched={len(unmatched)}")
        for name in unmatched[:20]:
            print("  -", name)


def main() -> None:
    parser = argparse.ArgumentParser(description="导入本地动作演示媒体")
    parser.add_argument("--source", required=True, help="包含 gif/png/webp/mp4 的目录或 zip")
    args = parser.parse_args()
    import asyncio

    asyncio.run(_run(Path(args.source)))


if __name__ == "__main__":
    main()
