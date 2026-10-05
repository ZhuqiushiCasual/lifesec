from sqlalchemy import DateTime
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# 时间戳列统一用这个类型。
# MySQL 的 DATETIME 默认精度是「秒」（precision=0）：同一次对话里的事件和回应
# 落库时间只差几毫秒，会被截断成完全相等的时间戳，ORDER BY 分不出先后。
# 显式声明成 DATETIME(6)，其它方言保持普通 DateTime（SQLite 本来就存到微秒）。
DateTimeMicro = DateTime().with_variant(MySQLDateTime(fsp=6), "mysql")

_url = settings.database_url
# SQLite 需要关掉线程检查；MySQL(asyncmy) 不需要
_connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}

engine = create_async_engine(_url, echo=False, connect_args=_connect_args)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
