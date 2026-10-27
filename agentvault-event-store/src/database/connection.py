from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")

# P3-002: SQL echo disabled for production. Set SQL_ECHO=true to enable.
# P3-003: Use proper connection pooling instead of NullPool
from sqlalchemy.pool import AsyncAdaptedQueuePool

_sql_echo = os.getenv("SQL_ECHO", "false").lower() in ("true", "1", "yes")

# 2026-05-01: pool bumped from 20+10 → 40+20 after Frame A connection-pool
# saturation incident. The EventStore is the central event log; --workers 8
# multiplies every API call's connection demand, plus the cross-frame
# replicator + materialized-balances cache + supply-audit handler all hold
# connections concurrently. Old 30-max ceiling was hitting QueuePool TimeoutError
# under restart pressure. New 60-max gives headroom; env-overridable so prod
# can tune further without a rebuild.
_pool_size = int(os.getenv("DB_POOL_SIZE", "40"))
_max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "20"))
_pool_timeout = int(os.getenv("DB_POOL_TIMEOUT", "60"))
_pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "1800"))

engine = create_async_engine(
    DATABASE_URL,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=_pool_size,
    max_overflow=_max_overflow,
    pool_timeout=_pool_timeout,
    pool_recycle=_pool_recycle,
    echo=_sql_echo,
    pool_pre_ping=True,  # detect stale connections after server restart
)

AsyncSessionLocal = sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()