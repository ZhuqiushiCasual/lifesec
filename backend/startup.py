"""启动脚本：等 DB 就绪 → 建表 → 起 uvicorn。

建表与锚点用户由 app.main 的 lifespan 负责，这里只做"等 DB 起来"这一件事。
"""

import asyncio
import os
import sys
import time

import uvicorn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("DEBUG", "1")


async def wait_for_db(max_retries: int = 10, delay: float = 2.0) -> None:
    from sqlalchemy import text

    from app.database import engine

    for attempt in range(1, max_retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            print("[OK] 数据库可达")
            return
        except Exception as e:  # noqa: BLE001
            print(f"[{attempt}/{max_retries}] 等待数据库… {e}")
            await asyncio.sleep(delay)
    print("[FAIL] 连不上数据库")
    sys.exit(1)


async def main():
    print("=== selfsec backend ===\n")
    await wait_for_db()

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("DEBUG", "0").lower() in ("1", "true")

    print(f"\n[OK] http://{host}:{port}\n")
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    asyncio.run(main())
