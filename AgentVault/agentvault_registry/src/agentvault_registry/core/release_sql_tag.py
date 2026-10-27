"""Every statement the registry sends names its release, so no release ever runs another release's prepared plan.

D6-815 (2026-10-24), measured before the migration that would have hit it. The operators and Frame A reach their
databases through pgbouncer in transaction pooling (pgbouncer 1.25, max_prepared_statements at its default), which keeps
asyncpg's prepared statements on its server connections and hands a server-side statement to any later client that
prepares the same TEXT. A migration that changes a column's type (0195: contracts.origin_ref varchar(80) -> varchar(120);
before it 0174's json -> jsonb, §JSONCAST-3) leaves every pooled statement that returns the column planned for the old
type, and Postgres refuses to re-plan it ("cached plan must not change result type", asyncpg's
InvalidCachedStatementError). The recreated registry is a new client of the same server connections, so every read of
that table fails, request after request, while /health answers 200. Measured on a throwaway database behind pgbouncer
1.25.2 with the operators' pool settings: after the widening, 6 of 6 reads failed for a new client sending the old text,
12 of 12 passed sending the new release's text, and after the narrowing back the old release's text passed again (a
rollback meets its own plans).

So the text differs per release: a leading comment naming the image's own release (BUNDLED_IMAGE_TAG, never IMAGE_TAG,
which an env file can set), added where every statement passes (before_cursor_execute). The old release's statements sit
unused on the server connections until pgbouncer's cache drops them. A comment changes no plan, result or parameter, and
pg_stat_activity shows which release sent a query. The pooled sessions need no recycling at a roll, by any driver, kit
or operator's own update.
"""
from __future__ import annotations

from sqlalchemy import event

from .registry_identity import BUNDLED_IMAGE_TAG

assert "*/" not in BUNDLED_IMAGE_TAG and "/*" not in BUNDLED_IMAGE_TAG, BUNDLED_IMAGE_TAG
RELEASE_SQL_TAG = f"/* {BUNDLED_IMAGE_TAG} */ "


def tag_with_release(statement: str) -> str:
    """The statement with the release comment in front, once."""
    return statement if statement.startswith(RELEASE_SQL_TAG) else RELEASE_SQL_TAG + statement


def tag_engine_statements(engine):
    """Every statement `engine` (async or sync) sends carries the release comment; returns the listener."""
    target = getattr(engine, "sync_engine", engine)

    def _release_tag(conn, cursor, statement, parameters, context, executemany):
        return tag_with_release(statement), parameters

    event.listen(target, "before_cursor_execute", _release_tag, retval=True)
    return _release_tag
