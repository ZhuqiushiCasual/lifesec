"""selfsec 后端入口。

只做四件事：建表 → 确保锚点用户 → 拉起内置调度 → 挂路由与静态页。
"""

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.staticfiles import StaticFiles

# ── 日志 ──────────────────────────────────────────────────
# uvicorn 只管自己的访问日志；应用自己的 logger（selfsec.*）默认会被 root logger
# 的 WARNING 级别挡住，info 全部丢失。这里显式给 selfsec 命名空间挂 handler。
_selfsec_logger = logging.getLogger("selfsec")
_selfsec_logger.setLevel(logging.INFO)
if not _selfsec_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-7s %(name)-18s %(message)s", datefmt="%H:%M:%S")
    )
    _selfsec_logger.addHandler(_handler)
    _selfsec_logger.propagate = False  # 避免重复输出

import app.models  # noqa: F401 —— 注册全部模型，create_all 才能看到
from app.api import chat, insights, memory, messages, plans
from app.database import Base, engine
from app.services import scheduler
from app.services.deps import ensure_default_user, verify_token

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_default_user()
    task = scheduler.start()
    try:
        yield
    finally:
        if task:
            task.cancel()
        await engine.dispose()


app = FastAPI(title="selfsec API", version="0.3.0", lifespan=lifespan)

# 所有 /api/* 统一挂固定 token 鉴权（API_TOKEN 为空时不校验）
api_router = APIRouter(dependencies=[Depends(verify_token)])
api_router.include_router(chat.router)
api_router.include_router(messages.router)
api_router.include_router(insights.router)
api_router.include_router(plans.router)
api_router.include_router(memory.router)
app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# 前端：唯一一个聊天窗口。挂载在最后，/api/* 与 /health 优先匹配
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
