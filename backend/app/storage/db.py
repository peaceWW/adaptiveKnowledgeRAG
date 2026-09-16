from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.storage.models import Base

settings = get_settings()
SQLITE_URL = "sqlite+aiosqlite:///./data/akrag.db"


def _create_engine(url: str):
    Path("data").mkdir(exist_ok=True)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_async_engine(url, echo=False, pool_pre_ping=not url.startswith("sqlite"), connect_args=connect_args)


engine = _create_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    global engine, SessionLocal
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_migrate_schema)
        return
    except Exception:
        engine = _create_engine(SQLITE_URL)
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_migrate_schema)


def _migrate_schema(sync_conn) -> None:
    inspector = inspect(sync_conn)
    tables = inspector.get_table_names()
    if "knowledge_strategy" in tables:
        strategy_columns = {col["name"] for col in inspector.get_columns("knowledge_strategy")}
        if "extraction_policy" not in strategy_columns:
            sync_conn.execute(text("ALTER TABLE knowledge_strategy ADD COLUMN extraction_policy JSON"))
    if "document" in tables:
        columns = {col["name"] for col in inspector.get_columns("document")}
        if "enabled" not in columns:
            if sync_conn.dialect.name == "sqlite":
                sync_conn.execute(text("ALTER TABLE document ADD COLUMN enabled BOOLEAN DEFAULT 0"))
            else:
                sync_conn.execute(text("ALTER TABLE document ADD COLUMN enabled BOOLEAN DEFAULT FALSE"))
            sync_conn.execute(
                text("UPDATE document SET enabled = 1 WHERE status IN ('review', 'indexed')")
            )
        if "size_bytes" not in columns:
            sync_conn.execute(text("ALTER TABLE document ADD COLUMN size_bytes INTEGER DEFAULT 0"))
        if "index_keywords" not in columns:
            sync_conn.execute(text("ALTER TABLE document ADD COLUMN index_keywords JSON"))
        if "index_meta" not in columns:
            sync_conn.execute(text("ALTER TABLE document ADD COLUMN index_meta JSON"))
    if "knowledge_unit" in tables:
        unit_columns = {col["name"] for col in inspector.get_columns("knowledge_unit")}
        if "unit_meta" not in unit_columns:
            sync_conn.execute(text("ALTER TABLE knowledge_unit ADD COLUMN unit_meta JSON"))
    if "query_trace" in tables:
        columns = {col["name"] for col in inspector.get_columns("query_trace")}
        if "session_id" not in columns:
            sync_conn.execute(text("ALTER TABLE query_trace ADD COLUMN session_id VARCHAR(36)"))


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
