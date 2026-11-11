"""Every statement the TEG sends names its release, so no release ever runs another release's prepared plan (D6-817).

The registry's D6-815 (core/release_sql_tag.py there), for the TEG. Every operator's teg_layer database sits behind
pgbouncer in transaction pooling (pgbouncer 1.25, max_prepared_statements at its default), which keeps the prepared
statements of the TEG's asyncpg engine on its server connections and hands a server-side statement to any later client
that prepares the same TEXT. A TEG migration that changes a column's type would leave every pooled statement that
returns the column planned for the old type, and Postgres refuses to re-plan it ("cached plan must not change result
type"): after the TEG's recreate every read of that table would fail while /health answers 200. The registry measured
the class on a throwaway database behind pgbouncer 1.25.2 (6 of 6 reads failed for a new client sending the old text, 12
of 12 passed sending the new release's text).

So the text differs per release: a leading comment naming the TEG's own release (core/release.TEG_RELEASE, never an env
value), added where every statement passes (before_cursor_execute), on both of the TEG's engines. A comment changes no
plan, result or parameter, and pg_stat_activity shows which release sent a query.
"""
from __future__ import annotations

from sqlalchemy import event

from ..core.release import TEG_RELEASE

assert "*/" not in TEG_RELEASE and "/*" not in TEG_RELEASE, TEG_RELEASE
RELEASE_SQL_TAG = f"/* {TEG_RELEASE} */ "


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
