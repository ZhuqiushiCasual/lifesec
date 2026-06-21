from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User

DEFAULT_USER_ID = "u0010000-0000-4000-8000-000000000001"


async def get_current_user(
    db: AsyncSession = Depends(get_db),
) -> User:
    result = await db.execute(select(User).where(User.id == DEFAULT_USER_ID))
    user = result.scalar_one_or_none()
    if not user:
        raise RuntimeError(f"Default user {DEFAULT_USER_ID} not found. Run mock_data.sql first.")
    return user
