import logging
from typing import AsyncGenerator
import os # Import os to check environment

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
# --- ADDED: Import InvalidRequestError for specific catch ---
from sqlalchemy.exc import InvalidRequestError
# --- END ADDED ---


# Import settings to get the database URL
from .config import settings

logger = logging.getLogger(__name__)

# --- Database Engine Setup ---
DATABASE_URL_TO_USE = settings.DATABASE_URL

# ⚠ THESE TWO LINES LOGGED THE WHOLE DSN, password included, at WARNING and at ERROR — the widest of the four
# sites, because they run on every registry whose URL needs the adjustment rather than only on a seed.
from agentvault_registry.core.dsn import redact_dsn

# --- ADDED: Explicitly ensure asyncpg dialect in URL ---
if not DATABASE_URL_TO_USE.startswith("postgresql+asyncpg"):
    if DATABASE_URL_TO_USE.startswith("postgresql"):
        DATABASE_URL_TO_USE = DATABASE_URL_TO_USE.replace("postgresql://", "postgresql+asyncpg://", 1)
        logger.warning(f"Database URL adjusted to use asyncpg in database.py: {redact_dsn(DATABASE_URL_TO_USE)}")
    else:
        # Log error but allow to proceed, create_async_engine will likely fail anyway
        logger.error(f"DATABASE_URL in settings does not start with postgresql: {redact_dsn(DATABASE_URL_TO_USE)}")
# --- END ADDED ---


def pool_settings(env=None) -> tuple:
    """(pool_size, max_overflow) for this process's engine, from DB_POOL_SIZE / DB_MAX_OVERFLOW (defaults 40 / 40).

    §MCPTEST30 (V0527, 2026-10-01): the two were literals. A pool keeps up to pool_size IDLE connections per process, so a
    registry with 9 gunicorn workers can hold 360 idle connections against a database whose max_connections is 100 (no
    pgbouncer on the sandbox frames). Measured on sbx-alpha during round 9: every one of the 100 backends belonged to the
    registry and was idle, and the database refused 10 to 28 new connections a minute ("too many clients"; JWT decode,
    governance, the guild reaper and others failed with it). The defaults stay what they were, so nothing changes until a
    frame sets them; size them so that workers x (pool_size + max_overflow) stays under the database's max_connections.
    A value that is not a whole number >= 0 falls back to the default, loudly."""
    env = os.environ if env is None else env
    out = []
    for name, default in (("DB_POOL_SIZE", 40), ("DB_MAX_OVERFLOW", 40)):
        raw = (env.get(name) or "").strip()
        if not raw:
            out.append(default)
            continue
        try:
            val = int(raw)
            if val < 0:
                raise ValueError(raw)
            out.append(val)
        except ValueError:
            logger.error(f"{name}={raw!r} is not a whole number >= 0: the default {default} is used")
            out.append(default)
    if out[0] == 0:
        logger.error("DB_POOL_SIZE=0 keeps no connection at all: the default 40 is used")
        out[0] = 40
    return out[0], out[1]


_POOL_SIZE, _MAX_OVERFLOW = pool_settings()
logger.info(f"database pool per process: pool_size={_POOL_SIZE} max_overflow={_MAX_OVERFLOW} "
            f"(up to {_POOL_SIZE} idle and {_POOL_SIZE + _MAX_OVERFLOW} in all; DB_POOL_SIZE / DB_MAX_OVERFLOW)")

# Create an asynchronous engine instance.
try:
    engine = create_async_engine(
        DATABASE_URL_TO_USE, # Use the potentially adjusted URL
        pool_pre_ping=True,
        pool_recycle=1800,  # recycle connections older than 30m (defense-in-depth vs server-side idle/idle-in-txn reaps)
        pool_size=_POOL_SIZE,      # §MCPTEST30 V0527: DB_POOL_SIZE (default 40), see pool_settings
        max_overflow=_MAX_OVERFLOW,  # DB_MAX_OVERFLOW (default 40)
        # §2026-06-22 — lock_timeout / idle_in_transaction_session_timeout are provided at the
        # CATALOG level via `ALTER DATABASE … SET …` (applied live fleet-wide). They are NOT valid
        # asyncpg startup `server_settings` (PostgreSQL rejects them in the startup packet →
        # `ProtocolViolationError: unsupported startup parameter: lock_timeout`), so do NOT put them
        # in connect_args. A recreate-proof in-app version (a SQLAlchemy "connect" event that runs
        # `SET lock_timeout = '10s'`) can be added later; the catalog guards cover it for now.
        # echo=True, # Uncomment for debugging SQL
    )
    logger.info("SQLAlchemy async engine created successfully.")
# --- ADDED: Specific catch for the driver error ---
except InvalidRequestError as e:
    if "The asyncio extension requires an async driver" in str(e):
        logger.critical(
            f"FATAL: SQLAlchemy async engine creation failed! It detected the synchronous 'psycopg2' driver "
            f"instead of the required 'asyncpg', despite the URL being '{DATABASE_URL_TO_USE}'. "
            f"Ensure 'asyncpg' is installed and potentially check for conflicting SQLAlchemy/Alembic configurations or environment variables."
        )
    else:
        logger.critical(f"FATAL: SQLAlchemy InvalidRequestError during engine creation: {e}", exc_info=True)
    raise # Re-raise the original error after logging critical info
# --- END ADDED ---
except Exception as e:
    logger.critical(f"FATAL: Failed to create SQLAlchemy engine: {e}", exc_info=True)
    raise

# D6-815: every statement names its release (core/release_sql_tag.py). Behind pgbouncer, a column whose type a
# migration changes would otherwise meet the old release's prepared plan on every pooled server connection.
from agentvault_registry.core.release_sql_tag import RELEASE_SQL_TAG, tag_engine_statements

_RELEASE_TAG_LISTENER = tag_engine_statements(engine)
logger.info(f"statements carry the release comment {RELEASE_SQL_TAG.strip()}")

# --- Session Factory ---
AsyncSessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
logger.info("SQLAlchemy async session maker configured.")


# --- Base Class for Declarative Models ---
Base = declarative_base()
logger.info("SQLAlchemy declarative base created.")


# --- Dependency for FastAPI ---
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an SQLAlchemy asynchronous session.

    §pass16 (2026-05-16) — Quieter logging. The previous `except Exception`
    branch logged a full traceback at ERROR level for ANY exception, including
    HTTPException(401/403/404/422) which is the NORMAL FastAPI 4xx mechanism.
    Every expired JWT (HTTPException(401, "Token expired")) was producing a
    multi-frame Python traceback in registry logs. Now: HTTPException paths
    still rollback the session (correct), but skip the ERROR log + traceback
    (only routine 4xx noise). errors.py http_exception_handler still logs
    the user-facing status at WARNING (one line, no stack).
    """
    # Local import to avoid circular dependency at module load.
    from fastapi import HTTPException, WebSocketException
    from fastapi.exceptions import RequestValidationError
    from starlette.websockets import WebSocketDisconnect
    # 2026-07-14 — dead-connection-tolerant teardown. On pgbouncer-fronted
    # frames a request that idles past the pooler's server timeout (e.g. the
    # minutes-long api-tester flows: the auth dependency's session sits idle
    # while the engine runs) comes back to a CLOSED connection; the old
    # `async with` __aexit__ then raised InterfaceError("cannot call
    # Transaction.rollback(): the underlying connection is closed") and
    # converted an already-successful response into a 500. There is nothing
    # to roll back on a dead connection (the server already destroyed the
    # txn); any UNCOMMITTED write was lost when the connection died, and a
    # handler that commits gets its real failure at commit time inside the
    # handler — so swallowing teardown-only errors is semantically safe.
    session = AsyncSessionLocal()
    logger.debug(f"Yielding database session: {session}")
    try:
        yield session
    except (HTTPException, WebSocketException, WebSocketDisconnect, RequestValidationError):
        # Normal FastAPI 4xx/5xx flow — rollback any pending state,
        # re-raise so FastAPI translates to the HTTP response. Don't log
        # at ERROR level: the handler in errors.py already logs at WARNING.
        # §BATCH0911 — a websocket refusal (1008) or disconnect is the same kind of control
        # flow, not a database failure; it used to log a full traceback on every refused reconnect.
        # §MCPTEST30 (V0545): a request that fails validation is the same (RequestValidationError is not an
        # HTTPException; FastAPI raises it after the yield dependencies are entered): 51 tracebacks in 30 minutes on
        # sbx-alpha from one tester sweep.
        await _rollback_quietly(session)
        raise
    except Exception as exc:
        if caller_caused_db_error(exc):
            # §MCPTEST30 (V0545): a value the CALLER sent that the database refused (an id past int32, invalid input):
            # errors.py answers it 422; one line, not a traceback at ERROR, which any caller could fill the log with
            logger.warning("Database session rolled back on a value the caller sent: %s",
                           (str(exc).split("\n", 1)[0])[:240])
        else:
            logger.exception("Exception occurred during database session, rolling back.")
        await _rollback_quietly(session)
        raise
    finally:
        try:
            await session.close()
        except Exception as close_exc:
            logger.warning(f"DB session close on dead connection ignored: {close_exc!r}")
        logger.debug(f"Database session closed: {session}")


def caller_caused_db_error(exc: BaseException) -> bool:
    """Is this a database error the caller's VALUE caused (the class errors.py answers 422), not the server's?

    The same classification as errors.db_error_answer (one rule for the answer and for the log), read from the
    exception's first line: the driver's message is there, the statement and its parameters follow on later lines."""
    try:
        from agentvault_registry.errors import db_error_answer
        return db_error_answer(str(exc).split("\n", 1)[0]) is not None
    except Exception:  # noqa: BLE001 — a log decision must never raise
        return False


async def _rollback_quietly(session) -> None:
    """Rollback that tolerates a connection the pooler/reaper already closed —
    the original exception (re-raised by the caller) is the one that matters."""
    try:
        await session.rollback()
    except Exception as rb_exc:
        logger.warning(f"DB rollback on dead connection ignored: {rb_exc!r}")

# --- Helper functions for CLI tools ---
def get_async_engine():
    """Get the async engine for CLI tools"""
    return engine

def get_async_session_maker():
    """Get the async session maker for CLI tools"""
    return AsyncSessionLocal


# --- Context manager for background tasks ---
from contextlib import asynccontextmanager

@asynccontextmanager
async def get_db_context():
    """Context manager for database sessions in background tasks.
    Same dead-connection-tolerant teardown as get_db (2026-07-14)."""
    session = AsyncSessionLocal()
    try:
        yield session
    except Exception:
        logger.exception("Exception in database context, rolling back.")
        await _rollback_quietly(session)
        raise
    finally:
        try:
            await session.close()
        except Exception as close_exc:
            logger.warning(f"DB context close on dead connection ignored: {close_exc!r}")
        finally:
            await session.close()
