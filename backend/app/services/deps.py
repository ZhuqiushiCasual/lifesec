"""鉴权 + 单用户。

单用户项目：没有注册/登录，users 表只有一行，仅作外键锚点。
首次启动自动创建，因此不再需要 mock_data.sql 种子。
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User

DEFAULT_USER_ID = "u0010000-0000-4000-8000-000000000001"
DEFAULT_USER_NAME = "我"


async def verify_token(request: Request) -> None:
    """固定 token 鉴权：API_TOKEN 为空则跳过（本地开发）。"""
    if not settings.api_token:
        return
    if request.headers.get("X-API-Token") != settings.api_token:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


async def ensure_default_user() -> None:
    """启动时调用：确保锚点用户存在。"""
    from app.database import async_session

    async with async_session() as db:
        exists = (await db.execute(select(User).where(User.id == DEFAULT_USER_ID))).scalar_one_or_none()
        if not exists:
            db.add(User(id=DEFAULT_USER_ID, name=DEFAULT_USER_NAME))
            await db.commit()


async def get_current_user(db: AsyncSession = Depends(get_db)) -> User:
    user = (await db.execute(select(User).where(User.id == DEFAULT_USER_ID))).scalar_one_or_none()
    if not user:
        user = User(id=DEFAULT_USER_ID, name=DEFAULT_USER_NAME)
        db.add(user)
        await db.commit()
    return user
