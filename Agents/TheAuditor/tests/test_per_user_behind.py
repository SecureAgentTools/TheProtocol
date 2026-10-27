"""§LEDGERGATE E (2026-10-11): a negative projection whose balance changes the TEG still holds is BEHIND, not a breach.

His ask 2026-10-11 ("check how we make agent accounts impossible to go negative on teg ... it was flagged in the
auditor on legacy frame"). The TEG cannot persist a negative; a negative in the store's projection under one writer is
a balance change that has not landed yet, or a projection that broke. I3 (per-user) asked the TEG only whether the
agent exists there, so a projection that was merely behind read as a BREACH, exactly like a broken one. It now also
asks the TEG's journal whether rows for that agent are still waiting to be emitted:
  1. waiting rows, the oldest younger than PER_USER_BEHIND_MAX_S: behind (counted, not a breach);
  2. no waiting rows: a breach, as before;
  3. waiting rows older than the bound (a ledger that stopped draining): a breach again, never masked for long;
  4. a journal that cannot be read: every genuine negative is a breach (fail loud, as the presence check already is).
CONTROLS that pass on the base: a negative with no TEG row is orphan transit, excluded, as before (5), and one with no
waiting rows is a breach, as before (2). RED on the base (run 2026-10-11): 1, 3 and 4.

§LEDGERGATE F (2026-10-11, FINDINGS §9 S2): the TEG's own census, every cycle. 6: no negative row on the TEG reads 0 and
OK; 7: a negative row on the TEG is a BREACH even when the projection shows none; 8: a census that cannot be read is not
checked (None), and neither breaks nor passes the check on its own. RED on defa919: 6, 7 and 8.
"""
import asyncio
import importlib
import json
import os

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.getenv("AUDITOR_TREE") or HERE


def _purge():
    import sys
    for name in [n for n in list(sys.modules) if n == "src" or n.startswith("src.")]:
        del sys.modules[name]


class Con:
    def __init__(self, routes):
        self.routes = routes

    async def fetch(self, sql, *args):
        for needle, answer in self.routes:
            if needle in sql:
                if isinstance(answer, Exception):
                    raise answer
                return answer(*args) if callable(answer) else answer
        return []

    async def fetchrow(self, sql, *args):
        rows = await self.fetch(sql, *args)
        return rows[0] if rows else None


class Pool:
    def __init__(self, con):
        self.con = con

    def acquire(self):
        con = self.con

        class A:
            async def __aenter__(s):
                return con

            async def __aexit__(s, *a):
                return False
        return A()


@pytest.fixture()
def main(tmp_path, monkeypatch):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "frames.json").write_text("[]")
    _purge()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FRONTEND_DIR", os.path.join(TREE, "frontend"))
    monkeypatch.setenv("AUDITOR_SOLO", "true")
    monkeypatch.setenv("AUDITOR_ADMIN_TOKEN", "t" * 32)
    monkeypatch.setenv("AUDITOR_EXTRA_FRAMES_FILE", str(frames_dir / "frames.json"))
    monkeypatch.syspath_prepend(TREE)
    m = importlib.import_module("src.auditor.main")
    monkeypatch.setattr(m, "_read_federated_agents", lambda fid: None)
    return m


def _wire(m, monkeypatch, negatives, present, pending=None, journal_error=None, census=(0, 0.0)):
    es = Con([("FROM materialized_balances", [{"agent_did": d, "liq": liq, "stk": stk} for d, liq, stk in negatives]),
              ("FROM events", [])])
    # the census first: its SQL names agent_teg_profiles too
    census_answer = census if isinstance(census, Exception) else [{"n": census[0], "worst": census[1]}]
    teg_routes = [("token_balance < 0", census_answer),
                  ("FROM agent_teg_profiles", [{"agent_id": d} for d in present])]
    if journal_error is not None:
        teg_routes.append(("FROM balance_ledger_journal", journal_error))
    else:
        teg_routes.append(("FROM balance_ledger_journal",
                           [{"agent_id": d, "rows": n, "oldest_s": age} for d, (n, age) in (pending or {}).items()]))
    teg = Con(teg_routes)

    async def gp(frame):
        return Pool(es)

    async def gt(frame):
        return Pool(teg)
    monkeypatch.setattr(m, "_get_pool", gp)
    monkeypatch.setattr(m, "_get_teg_pool", gt)


def _run(m):
    return asyncio.run(m._per_user_integrity({"id": "teg-test"}))


def test_waiting_rows_make_a_negative_behind_not_a_breach(main, monkeypatch):
    _wire(main, monkeypatch, [("did:a", -5.0, 0.0)], present={"did:a"}, pending={"did:a": (2, 3.5)})
    r = _run(main)
    assert r["status"] == "OK" and r["negative_agents"] == 0, r
    assert r["behind_agents"] == 1 and r["behind_total"] == 5.0 and r["behind_pending_rows"] == 2, r
    assert r["teg_cross_checked"] and r["teg_journal_checked"], r


def test_no_waiting_rows_is_a_breach_as_before(main, monkeypatch):
    _wire(main, monkeypatch, [("did:a", -5.0, 0.0)], present={"did:a"}, pending={})
    r = _run(main)
    assert r["status"] == "BREACH" and r["negative_agents"] == 1 and r.get("behind_agents", 0) == 0, r


def test_rows_waiting_past_the_bound_are_a_breach_again(main, monkeypatch):
    _wire(main, monkeypatch, [("did:a", -5.0, 0.0)], present={"did:a"},
          pending={"did:a": (1, main.PER_USER_BEHIND_MAX_S + 1)})
    r = _run(main)
    assert r["status"] == "BREACH" and r["behind_agents"] == 0, r


def test_an_unreadable_journal_reads_nothing_as_behind(main, monkeypatch):
    _wire(main, monkeypatch, [("did:a", -5.0, 0.0), ("did:b", 0.0, -2.0)], present={"did:a", "did:b"},
          journal_error=Exception("relation balance_ledger_journal does not exist"))
    r = _run(main)
    assert r["status"] == "BREACH" and r["negative_agents"] == 2 and not r["teg_journal_checked"], r


def test_control_a_negative_with_no_teg_row_is_orphan_transit(main, monkeypatch):
    _wire(main, monkeypatch, [("did:gone", -1.0, 0.0)], present=set())
    r = _run(main)
    assert r["status"] == "OK" and r["orphan_transit_excluded"] == 1 and r.get("behind_agents", 0) == 0, r


def test_the_teg_census_reads_zero_and_ok(main, monkeypatch):
    _wire(main, monkeypatch, [], present=set())
    r = _run(main)
    assert r["status"] == "OK" and r["teg_negative_rows"] == 0 and r["teg_census_checked"] is True, r


def test_a_negative_row_on_the_teg_is_a_breach_whatever_the_projection_says(main, monkeypatch):
    _wire(main, monkeypatch, [], present=set(), census=(2, -3.5))
    r = _run(main)
    assert r["status"] == "BREACH" and r["negative_agents"] == 0, r
    assert r["teg_negative_rows"] == 2 and r["teg_negative_worst"] == -3.5, r


def test_an_unreadable_census_is_not_checked(main, monkeypatch):
    _wire(main, monkeypatch, [], present=set(), census=Exception("permission denied for table agent_teg_profiles"))
    r = _run(main)
    assert r["teg_census_checked"] is False and r["teg_negative_rows"] is None and r["status"] == "OK", r
