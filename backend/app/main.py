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
from app.api import chat, insights, memory, messages, onboarding, plans
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
api_router.include_router(onboarding.router)
app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# 前端：唯一一个聊天窗口。挂载在最后，/api/* 与 /health 优先匹配
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


@app.middleware("http")
async def static_revalidate(request, call_next):
    """静态页与脚本一律要求浏览器回源校验（no-cache = 用之前先问一声，不是不缓存）。

    StaticFiles 不返 Cache-Control，浏览器就按启发式规则自行决定缓存多久——
    部署新前端后，用户手里会出现"新 HTML + 缓存里的旧 app.js"这种错配
    （表现为：按钮在 HTML 里躺着，但没脚本把它放出来；服务端日志里甚至看不到
    那个 .js 的请求）。带 ETag / Last-Modified 时回源是 304，代价可以忽略。
    """
    response = await call_next(request)
    path = request.url.path
    if path in ("/", "/index.html") or path.endswith((".js", ".css", ".html")):
        response.headers["Cache-Control"] = "no-cache"
    return response
