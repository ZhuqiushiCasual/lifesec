"""迭代的三个时钟 + 一把幂等锁（设计文档 4.4）。

    CLOCK 1  档迭代     每 TAG_ITER_TURNS 条用户消息 → 重算「有新增事件的那些标签」的档首摘要
    CLOCK 2  画像迭代   新增轮次 ≥ PORTRAIT_USER_TURNS，或（>PORTRAIT_HOURS 且 新增事件 ≥ N）
    CLOCK 3  每日兜底   00:00 检查：距上次迭代超过 PORTRAIT_HOURS 且确有新增 → 补跑

为什么需要锁：三个时钟会**打架** —— 同一条消息触发"每 10 轮"的档迭代，
同时 00:00 的兜底也在跑，没有锁就是同一次迭代算两遍（白花钱，两次结果还互相覆盖）。

    job_runs(job, period_key) 唯一键：插得进就跑，插不进说明这个周期跑过了。

刻意不引 APScheduler、不引分布式锁：单用户单实例，一张表就够。
失败时把占位行删掉（而不是标 failed），这样下个周期还能正常跑。
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.job import STATUS_DONE, STATUS_RUNNING, JobRun
from app.services.memory import library, profile
from app.utils import now_local, today_local

log = logging.getLogger("selfsec.jobs")


async def _claim(db: AsyncSession, job: str, period_key: str) -> JobRun | None:
    """抢锁：插得进返回那行，插不进返回 None（这个周期已经跑过 / 正在跑）。"""
    row = JobRun(job=job, period_key=period_key, status=STATUS_RUNNING)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return None
    return row


async def _finish(db: AsyncSession, row: JobRun, detail: str) -> None:
    row.status = STATUS_DONE
    row.detail = (detail or "")[:255]
    row.finished_at = now_local()
    await db.commit()


async def _release(db: AsyncSession, row: JobRun) -> None:
    """失败时释放占位（否则这个周期再也不会重试）。"""
    try:
        await db.delete(row)
        await db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("释放迭代锁失败: %s", e)


async def tag_iteration(db: AsyncSession, user_id: str, turns: int) -> dict:
    """CLOCK 1 · 档迭代：重建索引卡的计数，然后**只**重算有新增的标签摘要。"""
    run = await _claim(db, "tag_iter", f"turn:{turns}")
    if run is None:
        return {"job": "tag_iter", "skipped": True}
    try:
        rebuilt = await library.rebuild_index(db, user_id)
        updated = await library.digest_pending(db, user_id)
        await _finish(db, run, f"标签 {rebuilt} 个，重算摘要 {len(updated)} 个")
        log.info("档迭代（%s 轮）：标签 %s 个，重算摘要 %s 个 %s", turns, rebuilt, len(updated), updated)
        return {"job": "tag_iter", "turns": turns, "tags": rebuilt, "updated": updated}
    except Exception as e:  # noqa: BLE001
        log.warning("档迭代失败: %s", e)
        await _release(db, run)
        return {"job": "tag_iter", "error": str(e)}


async def portrait_iteration(db: AsyncSession, user_id: str, *, reason: str, period: str) -> dict:
    """CLOCK 2 · 画像迭代。是否真的重算由 profile.should_iterate 决定（防漂移）。"""
    run = await _claim(db, "portrait_iter", period)
    if run is None:
        return {"job": "portrait_iter", "skipped": True}
    try:
        row = await profile.refresh(db, user_id, reason=reason)
        if row is None:
            await _finish(db, run, "条件不满足，未重算")
            return {"job": "portrait_iter", "iterated": False, "reason": reason}
        await _finish(db, run, f"v{row.version} · {row.summary}")
        return {"job": "portrait_iter", "iterated": True, "version": row.version, "summary": row.summary}
    except Exception as e:  # noqa: BLE001
        log.warning("画像迭代失败: %s", e)
        await _release(db, run)
        return {"job": "portrait_iter", "error": str(e)}


async def tick(db: AsyncSession, user_id: str) -> list[dict]:
    """每次对话结束后调用。返回本次真正跑了什么（日志与测试用）。

    注意这里**不做条件判断**：档迭代按轮次窗口触发，画像迭代交给 should_iterate。
    """
    out: list[dict] = []
    turns = await profile.count_user_msgs(db, user_id)
    if not turns:
        return out

    # CLOCK 1
    if turns % settings.tag_iter_turns == 0:
        out.append(await tag_iteration(db, user_id, turns))

    # CLOCK 2（轮次分支）
    if turns % settings.portrait_user_turns == 0:
        out.append(
            await portrait_iteration(db, user_id, reason=f"新增 {turns} 轮对话", period=f"turn:{turns}")
        )

    return out


async def daily(db: AsyncSession, user_id: str) -> dict:
    """CLOCK 3 · 每日兜底（调度器 00:00 调用）。

    语义是"每天至少看一眼"：距上次迭代超过 PORTRAIT_HOURS 且确有新增事件才补跑。
    所以刚在晚上跑过的话，这里会安静地跳过——不是无条件重写。
    """
    day = f"day:{today_local():%Y-%m-%d}"
    run = await _claim(db, "daily", day)
    if run is None:
        return {"job": "daily", "skipped": True}
    try:
        result = await portrait_iteration(db, user_id, reason="每日兜底", period=day)
        await _finish(db, run, "兜底检查完成")
        return {"job": "daily", "day": str(today_local()), "result": result}
    except Exception as e:  # noqa: BLE001
        log.warning("每日兜底失败: %s", e)
        await _release(db, run)
        return {"job": "daily", "error": str(e)}
