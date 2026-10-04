"""启动脚本：等 DB 就绪 → 起 uvicorn。

**不要**把 uvicorn.run() 写在 asyncio.run() 里面：uvicorn.run() 内部自己就会调用
asyncio.run()，在已运行的事件循环里再调它会抛
    RuntimeError: asyncio.run() cannot be called from a running event loop
所以拆成两步：先用一个独立事件循环把 DB 等待跑完（跑完即销毁 engine），
再回到同步上下文里启动 uvicorn。
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
            # engine 是模块级单例，连接池绑定在当前事件循环上。
            # 这个循环马上要被丢弃，必须释放，否则 uvicorn 的新循环会拿到失效连接。
            await engine.dispose()
            return
        except Exception as e:  # noqa: BLE001
            print(f"[{attempt}/{max_retries}] 等待数据库… {e}")
            await asyncio.sleep(delay)
    print("[FAIL] 连不上数据库")
    sys.exit(1)


def main():
    print("=== selfsec backend ===\n")

    # 独立事件循环，跑完即结束；uvicorn.run 必须在同步上下文里调用
    asyncio.run(wait_for_db())

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("DEBUG", "0").lower() in ("1", "true")

    print(f"\n[OK] http://{host}:{port}\n")
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
