"""One redaction for a database URL, because a truncation is not one.

⚠ `url[:50]` IS NOT A REDACTION. It is the same credential with fewer characters, and it was in four log lines:
operator_seed and prod_seed truncated at 50 (which reaches into the password on every DSN this fleet uses), and
database.py logged the WHOLE url twice, at WARNING and ERROR, on any registry whose URL needed the asyncpg
adjustment. agentvault2-6a found the first one in a live operator log on 2026-09-16 and tore the stack down so
that password died with its volume; the other three were found by grepping for the class rather than the instance.
"""
from __future__ import annotations

import re

_SCHEME = re.compile(r"^([a-zA-Z0-9+.\-]+://)(.*)$", re.S)


def redact_dsn(url: object) -> str:
    """`postgresql+asyncpg://registry:<redacted>@db:5432/agentvault_registry` — everything but the secret.

    The host, port, database and user are what a log line is FOR: they are how a reader tells one DSN from
    another. Only the password is removed, and it is removed entirely rather than shortened.

    ⚠ SPLIT ON THE LAST `@` OF THE AUTHORITY, NOT THE FIRST. A first-match regex leaves the tail of a password
    that itself contains `@` sitting in the log next to the host — measured on this function's own output before
    it was used anywhere, which is the only reason it is not in an image. Passwords here are generated without
    `@`, but a redactor that depends on the shape of its input is not a redactor.
    """
    if not url:
        return "<empty>"
    text = str(url)
    m = _SCHEME.match(text)
    if not m:
        return text
    scheme, rest = m.group(1), m.group(2)
    authority, sep, tail = rest.partition("/")
    if "@" not in authority:
        return text
    creds, _, host = authority.rpartition("@")
    if ":" not in creds:
        return text                      # a user with no password: nothing to remove
    user = creds.split(":", 1)[0]
    return f"{scheme}{user}:<redacted>@{host}{sep}{tail}"


# §DEPS sqla-driver-pin (2026-09-29): the driver a SYNC engine runs on is named here, never left to SQLAlchemy's
# default. A plain `postgresql://` means psycopg2 on SQLAlchemy 2.0 and psycopg (3) on 2.1; this image installs BOTH,
# so on 2.1 the migration bridge and alembic would switch drivers silently, behind pgbouncer's transaction pooling
# (psycopg 3 prepares a statement after its fifth execution). Naming psycopg2 keeps today's driver on 2.0 and 2.1.
SYNC_PG_DRIVER = "postgresql+psycopg2"
_SYNC_PG_REWRITE = frozenset({"postgresql", "postgresql+asyncpg"})


def sync_engine_url(url: str) -> str:
    """The URL a SYNC engine is built from: `postgresql://` and `postgresql+asyncpg://` name psycopg2.

    Only the scheme changes; user, password, host, port, database and query come back byte for byte (no parse and
    re-render, so a password is never re-quoted). A URL that already names a driver (`postgresql+psycopg2`,
    `postgresql+psycopg`, ...), any other database (sqlite) and an empty value come back unchanged. Async engines
    never pass through here: they name asyncpg themselves (database.py).
    """
    if not url:
        return url
    scheme, sep, rest = url.partition("://")
    if sep and scheme in _SYNC_PG_REWRITE:
        return f"{SYNC_PG_DRIVER}://{rest}"
    return url
