"""Database session management"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from typing import Generator

from ..core.config import get_settings
from ..core.db_url import sync_engine_url

settings = get_settings()

# Create engine with increased pool for concurrent cross-TEG 2PC transfers.
# 2026-05-04: decoupled `echo` from `settings.debug`. Previously frame-b-teg ran
# with debug=True (default when DEBUG env unset) which forced SQLA echo=True →
# SQLA's create_async_engine called setLevel(INFO) on the engine logger AFTER
# our setup_logging() ran, overriding the WARNING level we set there. Result:
# ~1.6k SQL-noise lines/min on frame-b-teg drowning real errors. Echo is now
# explicitly opt-in via SQLALCHEMY_ECHO=true, never from settings.debug.
import os as _os
_sqla_echo = _os.getenv("SQLALCHEMY_ECHO", "false").lower() == "true"
# 2026-05-29 (§pass73.3.21): pool sizing is env-configurable (CLAUDE.md rule 15 —
# hardcoded→env). Defaults 10/20 preserve prod behaviour exactly; sandbox raises
# these to absorb the federation-suite balance-read bursts that were exhausting the
# per-worker pool (QueuePool TimeoutError → stalled balance-outbox emitter +
# CanaryRebalancerErrored balance_query_failed + get_agent_teg_status 500s).
_POOL_SIZE = int(_os.getenv("TEG_DB_POOL_SIZE", "10"))
_MAX_OVERFLOW = int(_os.getenv("TEG_DB_MAX_OVERFLOW", "20"))
# §DEPS sqla-driver-pin (2026-09-29): the sync driver is NAMED (psycopg2). A plain postgresql:// is psycopg 3 on
# SQLAlchemy 2.1, which this image does not install: this engine would fail at import. core/db_url.py says why.
engine = create_engine(
    sync_engine_url(settings.database_url),
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    echo=_sqla_echo,
    pool_size=_POOL_SIZE,
    max_overflow=_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=300,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    Dependency to get database session.
    Ensures proper cleanup after request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database by creating all tables.
    """
    from .models import Base
    Base.metadata.create_all(bind=engine)


# ----------------------------------------------------------------------
# Async engine (Vector C, 2026-05-04) — opt-in via TEG_BULK_USE_ASYNC_DB
# Coexists with the sync engine above. Hot-path endpoints can await this
# engine to handle multiple in-flight transactions per worker. asyncpg
# driver. PgBouncer transaction-mode requires statement_cache_size=0
# (prepared statements don't survive pgbouncer connection swaps).
# ----------------------------------------------------------------------
def _build_async_db_url(sync_url: str) -> str:
    if sync_url.startswith("postgresql+asyncpg://"):
        return sync_url
    if sync_url.startswith("postgresql://"):
        return sync_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return sync_url  # sqlite, etc — async engine won't be constructed below

_ASYNC_URL = os.environ.get(
    "DATABASE_URL_ASYNC",
    _build_async_db_url(settings.database_url),
)

# Only build the async engine when running against a postgres DB. The default
# sqlite URL (used by tests/fresh installs) doesn't have an async driver
# available, so we keep async support no-op there. Production always sets
# DATABASE_URL to postgresql://, so the async engine is always live.
async_engine = None
AsyncSessionLocal = None
if _ASYNC_URL.startswith("postgresql+asyncpg://"):
    async_engine = create_async_engine(
        _ASYNC_URL,
        echo=_sqla_echo,
        pool_size=_POOL_SIZE,
        max_overflow=_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            # NOTE (2026-05-16): The PG `statement_timeout=15s` guard lives at the
            # cluster level (docker-compose `-c statement_timeout=15000` on mainframe
            # TEG DBs; postgresql.conf on cloud-op TEG DBs). DO NOT set it here via
            # asyncpg `server_settings` — pgbouncer in transaction-pool mode rejects
            # the parameter with ProtocolViolationError because it's not in
            # `ignore_startup_parameters`. The cluster-level config applies to every
            # backend connection PG accepts, including those from pgbouncer's pool,
            # so this guard is fully active without needing to set it here.
        },
    )
    AsyncSessionLocal = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_async_db():
    """Async dependency for endpoints that opt into async SQLAlchemy."""
    if AsyncSessionLocal is None:
        raise RuntimeError(
            "Async DB engine is not configured. Set DATABASE_URL to a "
            "postgresql:// URL (or DATABASE_URL_ASYNC to postgresql+asyncpg://)."
        )
    async with AsyncSessionLocal() as db:
        yield db
