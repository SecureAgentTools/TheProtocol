"""D6-684: a fork that names no royalty takes the published default.

/forge/status advertises ``royalty_default_bps`` (250, the switch FORGE_ROYALTY_DEFAULT_BPS) as the
default fork royalty, and the console's fork dialog proposes 250, but the fork routes stamped
``royalty_bps`` only when the caller named one: a fork made through the API kept NULL, and the
carve (``COALESCE(royalty_bps, 0)``) paid no royalty. A royalty the caller names wins, 0 included.
"""
import asyncio

from agentvault_registry.routers import bundles

CHILD = "11111111-1111-1111-1111-111111111111"
PARENT = "22222222-2222-2222-2222-222222222222"


class _Db:
    def __init__(self):
        self.calls = []

    async def execute(self, stmt, params=None):
        self.calls.append((str(stmt), dict(params or {})))

    async def commit(self):
        pass

    async def rollback(self):
        pass


def _stamp(royalty_bps):
    db = _Db()
    asyncio.run(bundles._record_fork_lineage(db, CHILD, PARENT, royalty_bps))
    assert len(db.calls) == 1, db.calls
    return db.calls[0]


def test_a_fork_without_a_royalty_takes_the_default(monkeypatch):
    monkeypatch.delenv("FORGE_ROYALTY_DEFAULT_BPS", raising=False)
    sql, params = _stamp(None)
    assert "royalty_bps = :rb" in sql
    assert params["rb"] == 250


def test_the_default_follows_its_switch(monkeypatch):
    monkeypatch.setenv("FORGE_ROYALTY_DEFAULT_BPS", "100")
    assert _stamp(None)[1]["rb"] == 100


def test_a_named_royalty_wins_and_zero_is_kept(monkeypatch):
    monkeypatch.setenv("FORGE_ROYALTY_DEFAULT_BPS", "100")
    assert _stamp(0)[1]["rb"] == 0
    assert _stamp(400)[1]["rb"] == 400


def test_the_lineage_is_stamped_with_it(monkeypatch):
    monkeypatch.delenv("FORGE_ROYALTY_DEFAULT_BPS", raising=False)
    sql, params = _stamp(None)
    assert "forked_from_bundle_id = CAST(:pid AS UUID)" in sql
    assert params["nid"] == CHILD and params["pid"] == PARENT
