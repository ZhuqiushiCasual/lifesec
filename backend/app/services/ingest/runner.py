"""确定性采集 runner —— Hermes skill 的第一阶段（stage A）。

用法（在 backend/ 目录下）：

    python -m app.ingest.runner --task-id <id> --out ../.hermes/ingest-task.json
    python -m app.ingest.runner --source qbitai --out ../.hermes/qbitai.json
    python -m app.ingest.runner --all --out ../.hermes/all.json

它只做「拿页面 → 抽正文 → 日期过滤 → 去重 → 写 JSON」，
**不调模型**，也不直接写消息（消息由 skill 的 stage B 生成摘要后回调
`POST /api/ingest/messages`）。

为什么放在 selfsec 仓库却由 Hermes 执行：
源配置、解析器、降级链都可版本化、可离线测试；selfsec 进程本身不常驻抓取。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select

import app.models  # noqa: F401 —— 注册全部模型，create_all 才能看到
from app.config import settings
from app.database import Base, async_session, engine
from app.models.ingest import RUN_FAILED, RUN_SUCCEEDED, TASK_QUEUED, TASK_RUNNING, IngestSource, IngestTask
from app.schemas.ingest import RunIn
from app.services.ingest import tasks as task_service
from app.services.ingest.crawler import CrawlResult, crawl_source_sync
from app.services.ingest.sources import ensure_seed as ensure_ingest_sources


def _source_dict(src: IngestSource) -> dict[str, Any]:
    return {
        "key": src.key,
        "name": src.name,
        "home_url": src.home_url,
        "feed_url": src.feed_url,
        "kind": src.kind,
        "level": src.level,
        "category": src.category,
        "max_items": src.max_items,
        "config": src.config or {},
    }


async def _bootstrap() -> None:
    """Hermes 侧可能先于 selfsec 启动：至少保证采集三张表和源种子在。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as db:
        await ensure_ingest_sources(db)


async def _load_sources(task: Optional[IngestTask], only: list[str]) -> list[IngestSource]:
    async with async_session() as db:
        if only:
            rows = (
                await db.execute(
                    select(IngestSource)
                    .where(IngestSource.key.in_(only))
                    .order_by(IngestSource.priority.desc(), IngestSource.key)
                )
            ).scalars().all()
        elif task is not None:
            rows = await task_service.sources_for_task(db, task)
        else:
            rows = (
                await db.execute(
                    select(IngestSource)
                    .where(IngestSource.enabled.is_(True))
                    .order_by(IngestSource.priority.desc(), IngestSource.key)
                )
            ).scalars().all()
        return list(rows)


async def _prepare_task(task_id: str) -> IngestTask:
    async with async_session() as db:
        task = await db.get(IngestTask, task_id)
        if task is None:
            raise SystemExit(f"没有任务：{task_id}")
        if task.status == TASK_QUEUED:
            task.status = TASK_RUNNING
            task.worker = task.worker or "runner"
            from app.utils import now_local

            task.started_at = task.started_at or now_local()
            await db.commit()
        return task


async def _report(task_id: Optional[str], result: CrawlResult, elapsed: float) -> None:
    if not task_id:
        return
    async with async_session() as db:
        try:
            await task_service.report_run(
                db,
                task_id,
                RunIn(
                    source_key=result.source_key,
                    source_name=result.source_name,
                    status=RUN_SUCCEEDED if result.status == "succeeded" else RUN_FAILED,
                    fetch_level=result.fetch_level,
                    items_found=len(result.items),
                    items_failed=1 if result.status == "failed" else 0,
                    error=result.error,
                    detail={**result.detail, "elapsed_ms": int(elapsed * 1000)},
                ),
            )
        except Exception as e:  # noqa: BLE001 —— 上报失败不打断采集
            print(f"[warn] 上报运行记录失败：{e}", file=sys.stderr)


async def run(
    *,
    task_id: Optional[str] = None,
    only: Optional[list[str]] = None,
    lookback_hours: Optional[int] = None,
    out: Optional[str] = None,
) -> int:
    lookback = lookback_hours or settings.ingest_lookback_hours
    only = only or []
    await _bootstrap()
    task = await _prepare_task(task_id) if task_id else None
    sources = await _load_sources(task, only)

    if not sources:
        print("[error] 没有可执行的源（检查 enabled / source_keys）", file=sys.stderr)
        return 1

    items: list[dict] = []
    source_reports: list[dict] = []
    ok_count = 0

    for src in sources:
        started = datetime.now()
        result = crawl_source_sync(_source_dict(src), limit=src.max_items, lookback_hours=lookback)
        elapsed = (datetime.now() - started).total_seconds()
        if result.status == "succeeded":
            ok_count += 1
        await _report(task_id, result, elapsed)
        source_reports.append(
            {
                "source_key": result.source_key,
                "source_name": result.source_name,
                "status": result.status,
                "fetch_level": result.fetch_level,
                "items": len(result.items),
                "error": result.error,
                "elapsed_ms": int(elapsed * 1000),
            }
        )
        items.extend(result.items)
        print(
            f"[{result.status}] {result.source_name:<8} {len(result.items):>2} 条 "
            f"{result.fetch_level:<4} {elapsed:5.1f}s {result.error or ''}",
            file=sys.stderr,
        )

    payload = {
        "task_id": task_id,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lookback_hours": lookback,
        "sources": source_reports,
        "items": items,
    }

    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(str(path.resolve()))
    else:
        print(json.dumps(payload, ensure_ascii=False))

    return 0 if ok_count else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="selfsec 确定性采集 runner（stage A）")
    parser.add_argument("--task-id", help="任务 id；会领取并上报运行记录")
    parser.add_argument("--source", action="append", default=[], help="只跑指定源，可重复")
    parser.add_argument("--all", action="store_true", help="跑全部启用源（无任务时）")
    parser.add_argument("--lookback-hours", type=int, default=None)
    parser.add_argument("--out", help="输出 JSON 文件路径；不传则打到 stdout")
    args = parser.parse_args()

    only = list(args.source or [])
    code = asyncio.run(
        run(task_id=args.task_id, only=only, lookback_hours=args.lookback_hours, out=args.out)
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
