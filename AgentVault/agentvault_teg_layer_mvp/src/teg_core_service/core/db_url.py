"""The URL a SYNC engine is built from, with its driver named: psycopg2, on SQLAlchemy 2.0 and 2.1 alike.

§DEPS sqla-driver-pin (2026-09-29). A plain `postgresql://` means psycopg2 on SQLAlchemy 2.0 and psycopg (3) on 2.1.
The TEG installs psycopg2 only, so on 2.1 every sync engine built from a plain URL fails at creation ("No module named
psycopg"), the engine in database/db_session.py (every transfer's) first, at import. Installing psycopg 3 instead
would swap the driver under the money engine: it prepares a statement after its fifth execution, and most TEG DSNs
go through pgbouncer's transaction pooling (the TEG's asyncpg engine turns its statement cache off for the same
reason). Naming the driver keeps today's; no DATABASE_URL carrier changes.

Dependency-free on purpose: the migration bridge imports it before the app exists, and `..database` builds its
engines at import, so the helper cannot live there.
"""
from __future__ import annotations

SYNC_PG_DRIVER = "postgresql+psycopg2"
_SYNC_PG_REWRITE = frozenset({"postgresql", "postgresql+asyncpg"})


def sync_engine_url(url: str) -> str:
    """`postgresql://` and `postgresql+asyncpg://` name psycopg2; everything else comes back unchanged.

    Only the scheme changes; user, password, host, port, database and query come back byte for byte (no parse and
    re-render, so a password is never re-quoted). A URL that already names a driver (`postgresql+psycopg2`,
    `postgresql+psycopg`, ...), sqlite (the tests' and fresh installs' default) and an empty value are left alone.
    The async engine never passes through here: db_session builds its `postgresql+asyncpg://` URL itself.
    """
    if not url:
        return url
    scheme, sep, rest = url.partition("://")
    if sep and scheme in _SYNC_PG_REWRITE:
        return f"{SYNC_PG_DRIVER}://{rest}"
    return url
