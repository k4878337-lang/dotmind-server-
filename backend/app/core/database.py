from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from typing import AsyncGenerator
from app.config import settings

# Engine configuration (supporting SQLite aiosqlite & Postgres asyncpg)
connect_args = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args=connect_args,
    future=True
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

Base = declarative_base()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an async database session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db() -> None:
    """Creates database tables if they do not exist and runs safe auto-migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
        def run_migrations(connection):
            from sqlalchemy import inspect, text
            inspector = inspect(connection)
            if "messages" in inspector.get_table_names():
                cols = [c["name"] for c in inspector.get_columns("messages")]
                if "attachments" not in cols:
                    connection.execute(text("ALTER TABLE messages ADD COLUMN attachments TEXT"))

        await conn.run_sync(run_migrations)

