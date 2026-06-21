"""Startup script: check DB, create tables, launch uvicorn."""

import asyncio
import os
import sys
import time

import uvicorn

# Prepend project root so "from app..." imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("DEBUG", "1")


async def check_db(max_retries: int = 10, delay: float = 2.0) -> None:
    from sqlalchemy import text
    from app.database import engine

    for attempt in range(1, max_retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            print("[OK] Database is reachable")
            return
        except Exception as e:
            print(f"[{attempt}/{max_retries}] Waiting for DB... {e}")
            await asyncio.sleep(delay)
    print("[FAIL] Could not connect to database")
    sys.exit(1)


async def create_tables() -> None:
    from app.database import Base, engine
    from app.models import user, event, finance, insight, digest  # noqa: F401 – register models

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[OK] Tables created (if not existed)")


async def main():
    print("=== Life Secretary Backend Startup ===\n")

    await check_db()
    await create_tables()

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("DEBUG", "0").lower() in ("1", "true")

    print(f"\n[OK] Starting server at http://{host}:{port}\n")
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    asyncio.run(main())
