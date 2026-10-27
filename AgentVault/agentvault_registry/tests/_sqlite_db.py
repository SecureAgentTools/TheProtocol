"""An in-memory SQLite database behind the AsyncSession calls a router makes, for route tests that must read REAL rows.

A filter that leaks shows only when rows are actually filtered: a fake session that answers canned rows, or a compiled
statement, cannot tell a WHERE clause that removes another person's row from one that keeps it. The registry's models
are Postgres-typed, so SQLite renders JSONB and ARRAY as JSON and INET as TEXT here (DDL only; the tests write plain
values). The shim answers the AsyncSession surface the routers use, synchronously underneath (one connection, so a
request served on another thread sees the same rows).
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@compiles(JSONB, "sqlite")
def _jsonb(_type, _compiler, **_kw):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _array(_type, _compiler, **_kw):
    return "JSON"


@compiles(INET, "sqlite")
def _inet(_type, _compiler, **_kw):
    return "TEXT"


class AsyncSessionShim:
    """The AsyncSession methods the routers await, over a synchronous Session."""

    def __init__(self, session: Session):
        self.sync = session

    async def execute(self, *a, **k):
        return self.sync.execute(*a, **k)

    async def scalar(self, *a, **k):
        return self.sync.scalar(*a, **k)

    async def get(self, *a, **k):
        return self.sync.get(*a, **k)

    def add(self, obj):
        self.sync.add(obj)

    def add_all(self, objs):
        self.sync.add_all(objs)

    async def delete(self, obj):
        self.sync.delete(obj)

    async def flush(self, *a, **k):
        self.sync.flush(*a, **k)

    async def commit(self):
        self.sync.commit()

    async def rollback(self):
        self.sync.rollback()

    async def refresh(self, obj, *a, **k):
        self.sync.refresh(obj, *a, **k)

    async def close(self):
        pass


def sqlite_db(*models) -> AsyncSessionShim:
    """A fresh in-memory database holding the tables of `models`, and a session over it (objects stay loaded after a
    commit, as with the registry's own sessions)."""
    from agentvault_registry.models import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[m.__table__ for m in models])
    return AsyncSessionShim(Session(engine, expire_on_commit=False))
