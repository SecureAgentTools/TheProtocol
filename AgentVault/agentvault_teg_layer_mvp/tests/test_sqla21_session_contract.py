"""§DEPS sqla21 (2026-09-29): the TEG's session factories do not autoflush, which is what keeps SQLAlchemy 2.1's autoflush
before Core statements (issue #9809) away from the TEG's raw-SQL sites (the money paths among them).

On 2.1 a Session flushes its pending ORM objects before ANY statement it executes, Core ones included, when its
`autoflush` is on; on 2.0 only ORM statements did. Every TEG request runs on database.db_session.SessionLocal (sync)
or AsyncSessionLocal (async), both autoflush=False, so no transfer, escrow or treasury path changes behaviour. The
CONTROL proves the instrument on the installed SQLAlchemy with an in-memory SQLite database (no network).
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, "/app")

import sqlalchemy  # noqa: E402
from sqlalchemy import Integer, create_engine, text  # noqa: E402
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column  # noqa: E402

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


def test_the_teg_session_factories_do_not_autoflush():
    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        pytest.skip("DATABASE_URL is not a postgresql URL here; the TEG suites always run with one")
    from src.teg_core_service.database import db_session

    assert db_session.SessionLocal.kw.get("autoflush") is False
    assert db_session.AsyncSessionLocal is not None
    assert db_session.AsyncSessionLocal.kw.get("autoflush") is False


def test_control_core_statement_autoflush_follows_the_session_setting():
    assert _pending_row_seen_by_text(autoflush=False) == 0
    assert _pending_row_seen_by_text(autoflush=True) == (1 if _SA_21 else 0), sqlalchemy.__version__
