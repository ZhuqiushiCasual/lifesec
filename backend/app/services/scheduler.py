"""内置调度 —— 问候 + 总结意识。

刻意不引入 APScheduler：一个 asyncio 循环 + 分钟级判断就够，
依赖更少、行为更可读（也方便将来把这部分逻辑搬去别处）。

    早 morning_hour  问候（议程三问）
    晚 evening_hour  今日小结 + 走一遍每日兜底
    00:00            每日兜底（CLOCK 3）：距上次迭代 >PORTRAIT_HOURS 且有新增才补跑
    INGEST_HOUR:INGEST_MINUTE
                     采集任务（消息推送输入侧）：建一个 queued 任务并喊 Hermes

对应架构图：调度器 →（定时触发）→ 意图路由，问候走的是同一条对话管道
（问候也落进同一个窗口表 messages，只是 role=secretary）。
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import async_session
from app.models.job import STATUS_DONE, STATUS_RUNNING, JobRun
from app.models.message import KIND_GREETING, ROLE_SECRETARY, Message
from app.models.user import User
from app.services.deps import DEFAULT_USER_ID, DEFAULT_USER_NAME
from app.services.ingest import dispatch
from app.services.ingest import tasks as ingest_tasks
from app.services.memory import lifecycle
from app.services.memory import stats
from app.utils import now_local

log = logging.getLogger("selfsec.scheduler")

# 议程，不是自由聊天（architecture 5.2）
MORNING_AGENDA = ["睡好了吗", "今天最重要的一件事", "昨天有什么没放下"]

_fired: set[str] = set()


async def _load_user(db) -> User:
    user = (await db.execute(select(User).where(User.id == DEFAULT_USER_ID))).scalar_one_or_none()
    if not user:
        user = User(id=DEFAULT_USER_ID, name=DEFAULT_USER_NAME)
        db.add(user)
        await db.commit()
    return user


async def _morning(db) -> None:
    user = await _load_user(db)
    db.add(
        Message(
            user_id=user.id,
            role=ROLE_SECRETARY,
            kind=KIND_GREETING,
            content="早。今天最重要的一件事是什么？",
            card={"kind": "greeting", "title": "早上好", "lines": MORNING_AGENDA, "meta": {}},
        )
    )
    await db.commit()


async def _evening(db) -> None:
    user = await _load_user(db)
    stat_data = await stats.collect(db, user.id)
    # 不再强制重算：走每日兜底那套条件（>24h 且确有新增才写），
    # 否则就是"没有新信息也在重写画像"——画像会缓慢漂移（设计文档 4.4 防漂移）
    await lifecycle.daily(db, user.id)

    db.add(
        Message(
            user_id=user.id,
            role=ROLE_SECRETARY,
            kind=KIND_GREETING,
            content=f"今天记了 {stat_data['today_total']} 件。",
            card={"kind": "greeting", "title": "今天", "lines": [stats.render(stat_data)], "meta": {}},
        )
    )
    await db.commit()


async def _midnight(db) -> None:
    """00:00 兜底：距上次迭代超过 PORTRAIT_HOURS 且确有新增，就补跑一次。"""
    user = await _load_user(db)
    result = await lifecycle.daily(db, user.id)
    log.info("每日兜底：%s", result)


async def _ingest(db) -> None:
    """每日采集：建一个 queued 任务，能推就推，推不到就等 Hermes pull。

    锁用 job_runs 的 (job, day) 唯一键：进程重启、多实例都不会同一天建两次任务。
    """
    period = f"day:{now_local():%Y-%m-%d}"
    run = JobRun(job="ingest_daily", period_key=period, status=STATUS_RUNNING)
    db.add(run)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        log.info("今日采集任务已创建过，跳过")
        return

    try:
        task = await ingest_tasks.create_task(
            db, trigger=ingest_tasks.TRIGGER_SCHEDULE
        )
        if settings.hermes_webhook_url and settings.hermes_webhook_secret:
            await dispatch.dispatch_task(task)
        run.status = STATUS_DONE
        run.detail = f"任务 {task.id}"
        run.finished_at = now_local()
        await db.commit()
        log.info("每日采集任务：%s", task.id)
    except Exception as e:  # noqa: BLE001
        # 失败释放锁，下个周期还能重试（同一天再次命中时会补建）
        try:
            await db.delete(run)
            await db.commit()
        except Exception:  # noqa: BLE001
            pass
        log.warning("每日采集任务创建失败: %s", e)


async def fire(kind: str) -> None:
    """手动触发一次定时任务（"morning" / "evening" / "midnight" / "ingest"）。"""
    async with async_session() as db:
        if kind == "morning":
            await _morning(db)
        elif kind == "midnight":
            await _midnight(db)
        elif kind == "ingest":
            await _ingest(db)
        else:
            await _evening(db)
    log.info("已触发定时任务：%s", kind)


async def loop() -> None:
    """分钟级轮询：命中整点且当天未触发过，就执行一次。"""
    log.info(
        "内置调度已启动：问候 %02d:00 / %02d:00，采集 %02d:%02d，时区偏移 UTC+%d",
        settings.morning_hour,
        settings.evening_hour,
        settings.ingest_hour,
        settings.ingest_minute,
        settings.tz_offset_hours,
    )
    while True:
        try:
            now = now_local()
            for kind, hour in (
                ("morning", settings.morning_hour),
                ("evening", settings.evening_hour),
                ("midnight", 0),          # CLOCK 3：每日兜底
            ):
                key = f"{now:%Y-%m-%d}:{kind}"
                if now.hour == hour and key not in _fired:
                    _fired.add(key)
                    await fire(kind)

            # 采集：分钟级判断用 >=，避免循环漂移刚好错过那一分钟
            if (
                settings.ingest_enabled
                and now.hour == settings.ingest_hour
                and now.minute >= settings.ingest_minute
            ):
                key = f"{now:%Y-%m-%d}:ingest"
                if key not in _fired:
                    _fired.add(key)
                    await fire("ingest")
            # 只保留当天的标记，避免无限增长
            today = f"{now:%Y-%m-%d}"
            for k in [k for k in _fired if not k.startswith(today)]:
                _fired.discard(k)
        except Exception as e:  # noqa: BLE001 —— 调度循环永不退出
            log.warning("调度循环异常: %s", e)
        await asyncio.sleep(60)


def start() -> asyncio.Task | None:
    if not settings.scheduler_enabled:
        log.info("内置调度已禁用（SCHEDULER_ENABLED=0）")
        return None
    return asyncio.create_task(loop())
