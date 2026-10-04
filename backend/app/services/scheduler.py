"""内置调度 —— 问候 + 总结意识。

刻意不引入 APScheduler：一个 asyncio 循环 + 分钟级判断就够，
依赖更少、行为更可读（也方便将来把这部分逻辑搬去别处）。

    早 morning_hour  问候（议程三问）
    晚 evening_hour  今日小结 + 强制重算画像

对应架构图：调度器 →（定时触发）→ 意图路由，问候走的是同一条对话管道。
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models.message import KIND_GREETING, Message
from app.models.user import User
from app.services.deps import DEFAULT_USER_ID, DEFAULT_USER_NAME
from app.services.memory import profile as mem_profile
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
            kind=KIND_GREETING,
            content="早。今天最重要的一件事是什么？",
            card={"kind": "greeting", "title": "早上好", "lines": MORNING_AGENDA, "meta": {}},
        )
    )
    await db.commit()


async def _evening(db) -> None:
    user = await _load_user(db)
    stat_data = await stats.collect(db, user.id)
    await mem_profile.refresh(db, user.id, force=True)

    db.add(
        Message(
            user_id=user.id,
            kind=KIND_GREETING,
            content=f"今天记了 {stat_data['today_total']} 条。",
            card={"kind": "greeting", "title": "今天", "lines": [stats.render(stat_data)], "meta": {}},
        )
    )
    await db.commit()


async def fire(kind: str) -> None:
    """手动触发一次定时任务（"morning" / "evening"）。调度循环与测试都走这里。"""
    async with async_session() as db:
        if kind == "morning":
            await _morning(db)
        else:
            await _evening(db)
    log.info("已触发定时任务：%s", kind)


async def loop() -> None:
    """分钟级轮询：命中整点且当天未触发过，就执行一次。"""
    log.info(
        "内置调度已启动：问候 %02d:00 / %02d:00，时区偏移 UTC+%d",
        settings.morning_hour,
        settings.evening_hour,
        settings.tz_offset_hours,
    )
    while True:
        try:
            now = now_local()
            for kind, hour in (("morning", settings.morning_hour), ("evening", settings.evening_hour)):
                key = f"{now:%Y-%m-%d}:{kind}"
                if now.hour == hour and key not in _fired:
                    _fired.add(key)
                    await fire(kind)
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
