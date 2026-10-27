"""§TESTBED (2026-09-19): a federated broadcast is authored locally on the registry that receives it.

admin_broadcasts.created_by is NOT NULL and a foreign key to developers on the RECEIVER; the reactor used the sender's
developer id, so the insert failed wherever that id did not exist (measured on a kit sandbox's cloud operator:
created_by 5 against developers 1-3) and the duplicate branch reported "no row found". The row now names the
receiver's first admin.
"""
import contextlib

from agentvault_registry.background_tasks import reactor_admin_broadcast_received as r


class _Result:
    def __init__(self, v):
        self.v = v

    def scalar_one_or_none(self):
        return self.v


class _Db:
    def __init__(self, admins, developers):
        self.admins, self.developers, self.added = admins, developers, []

    async def execute(self, stmt):
        is_admin_query = "is_admin" in str(stmt)
        pool = self.admins if is_admin_query else self.developers
        return _Result(min(pool) if pool else None)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        pass

    async def refresh(self, row):
        row.id = 42

    async def rollback(self):
        pass


def _ctx(db):
    @contextlib.asynccontextmanager
    async def _get():
        yield db
    return _get


_EVENT = {"source_frame": "Larch Sandbox", "broadcast_id": 1, "title": "fed-test-bcast", "created_by": 5,
          "broadcast_type": "info"}


async def test_the_row_is_authored_by_the_receivers_admin_not_the_senders_id(monkeypatch):
    db = _Db(admins=[1], developers=[1, 2, 3])
    monkeypatch.setattr(r, "get_db_context", _ctx(db))
    monkeypatch.setattr(r, "LOCAL_FRAME", "cloud-op-larchsbxop")
    assert await r._materialize_received_broadcast(dict(_EVENT)) == 42
    assert db.added[0].created_by == 1 and db.added[0].source_frame == "Larch Sandbox"


async def test_no_admin_falls_back_to_the_first_developer(monkeypatch):
    db = _Db(admins=[], developers=[7, 9])
    monkeypatch.setattr(r, "get_db_context", _ctx(db))
    monkeypatch.setattr(r, "LOCAL_FRAME", "cloud-op-x")
    assert await r._materialize_received_broadcast(dict(_EVENT)) == 42
    assert db.added[0].created_by == 7


async def test_a_registry_with_no_developer_skips_and_writes_nothing(monkeypatch):
    db = _Db(admins=[], developers=[])
    monkeypatch.setattr(r, "get_db_context", _ctx(db))
    monkeypatch.setattr(r, "LOCAL_FRAME", "cloud-op-x")
    assert await r._materialize_received_broadcast(dict(_EVENT)) is None
    assert db.added == []
