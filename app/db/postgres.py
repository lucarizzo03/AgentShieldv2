from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings

settings = get_settings()


def _build_sync_dsn(raw_dsn: str) -> str:
    if raw_dsn.startswith("postgresql://"):
        return raw_dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw_dsn


def _build_async_dsn(raw_dsn: str) -> str:
    if raw_dsn.startswith("postgresql://"):
        return raw_dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    if raw_dsn.startswith("sqlite:///"):
        return raw_dsn.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if raw_dsn.startswith("sqlite://"):
        return raw_dsn.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return raw_dsn


postgres_dsn_sync = _build_sync_dsn(settings.postgres_dsn)
postgres_dsn_async = _build_async_dsn(settings.postgres_dsn)

# Keep a sync engine for compatibility paths/tests.
engine = create_engine(postgres_dsn_sync, echo=False)
async_engine = create_async_engine(postgres_dsn_async, echo=False)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


async def create_db_and_tables() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

