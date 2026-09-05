from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import board, digests, events, finance, insights, memory
from app.database import Base, engine
from app.services.deps import verify_token

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="Life Secretary API",
    version="0.2.0",
    lifespan=lifespan,
)

# 所有 API 统一挂 token 鉴权（API_TOKEN 为空时不校验）
api_router = APIRouter(dependencies=[Depends(verify_token)])
api_router.include_router(events.router)
api_router.include_router(finance.router)
api_router.include_router(insights.router)
api_router.include_router(digests.router)
api_router.include_router(board.router)
api_router.include_router(memory.router)
app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# 前端静态页（单文件 HTML+CSS+JS），路由注册在其后，/api/* 优先匹配
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
