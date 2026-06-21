from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import board, digests, events, finance, insights, memory, voice
from app.config import settings
from app.database import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="Life Secretary API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events.router)
app.include_router(finance.router)
app.include_router(insights.router)
app.include_router(digests.router)
app.include_router(board.router)
app.include_router(memory.router)
app.include_router(voice.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
