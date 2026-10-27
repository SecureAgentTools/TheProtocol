"""§DEPS sqla21 (2026-09-29): the registry's session factory does not autoflush, which is what keeps SQLAlchemy 2.1's
autoflush before Core statements (issue #9809) away from its ~650 `execute(text(...))` sites.

On 2.1 a Session flushes its pending ORM objects before ANY statement it executes, Core ones (text(), insert(),
update()) included, when its `autoflush` is on; on 2.0 only ORM statements did. Measured live on Postgres 16.15 and
18.6 through asyncpg (2026-09-29): a pending row is invisible to a text() in the same session with autoflush=False on
2.0.54 AND 2.1.1, and visible with the default autoflush=True on 2.1.1 only. The request and worker sessions come from
database.AsyncSessionLocal (autoflush=False), so no raw-SQL site changes behaviour; the boot seeds that keep the default
run no raw SQL after an add, or flush explicitly right after each one.

The CONTROL proves the instrument on the installed SQLAlchemy with an in-memory SQLite database (no network): the
setting decides, and on 2.1 the default setting flushes.
"""
from __future__ import annotations

import sqlalchemy
from sqlalchemy import Integer, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

_SA_21 = tuple(int(p) for p in sqlalchemy.__version__.split(".")[:2]) >= (2, 1)


class _Base(DeclarativeBase):
    pass


class _Row(_Base):
    __tablename__ = "sqla21_autoflush_probe"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


def _pending_row_seen_by_text(autoflush: bool) -> int:
    eng = create_engine("sqlite://")
    _Base.metadata.create_all(eng)
    try:
        with Session(eng, autoflush=autoflush) as s:
            s.add(_Row(id=1))
            n = s.execute(text("select count(*) from sqla21_autoflush_probe")).scalar()
            s.rollback()
        return n
    finally:
        eng.dispose()


def test_the_request_session_factory_does_not_autoflush():
    from agentvault_registry import database

    assert database.AsyncSessionLocal.kw.get("autoflush") is False, (
        "database.AsyncSessionLocal autoflushes: on SQLAlchemy 2.1 every raw-SQL statement would first flush the "
        "session's pending ORM objects (earlier IntegrityErrors, a different lock order in the money paths)"
    )


def test_control_core_statement_autoflush_follows_the_session_setting():
    assert _pending_row_seen_by_text(autoflush=False) == 0
    assert _pending_row_seen_by_text(autoflush=True) == (1 if _SA_21 else 0), sqlalchemy.__version__
