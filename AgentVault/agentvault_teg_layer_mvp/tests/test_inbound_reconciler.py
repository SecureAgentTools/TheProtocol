"""§SECFIX-15 (2026-09-25) — the inbound cross-TEG reconciler: each completed credit against the source's record.

Measured before building it: on EU, ASIA and the sandbox pair the last 50 completed inbound credits each (200) all found a
TokensTransferred with the transfer id as data.transaction_id and the SAME (gross) amount in the receiving frame's store,
and an operator's TEG read its parent's store by transaction id with its own SVID. So today the reconciler reports no
mismatch, and one it reports later means something.

RED control: the module does not exist on the tree before the fix.
"""
from __future__ import annotations

import asyncio
import pathlib
from decimal import Decimal

from teg_core_service.core.cross_teg import inbound_reconciler as ir

MAIN = pathlib.Path(ir.__file__).resolve().parents[2] / "main.py"


def _tt(amount):
    return {"event_type": "TokensTransferred", "data": {"amount": amount, "transaction_id": "t"}}


def test_classify():
    fee = {"event_type": "TransactionFeeCollected", "data": {"fee_amount": "0.0005"}}
    assert ir.classify(Decimal("0.1"), [fee, _tt("0.100000000000000000")]) == "verified"
    assert ir.classify("5", [_tt("4.99")]) == "mismatch"
    assert ir.classify("5", [fee]) == "missing"
    assert ir.classify("5", []) == "missing"
    assert ir.classify("5", [_tt("1"), _tt("5")]) == "verified", "a second record for the same id that matches"
    assert ir.classify("5", [_tt("not-a-number")]) == "mismatch"


class _Redis:
    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None, nx=False):
        if nx and k in self.kv:
            return False
        self.kv[k] = v
        return True

    async def expire(self, k, s):
        return True


def _drive(monkeypatch, rows, events_by_id, *, fail_ids=()):
    rec = ir.InboundReconciler()
    rec.max_wait = 3600

    async def _rows():
        return rows

    async def _events(session, base, tid):
        if tid in fail_ids:
            raise RuntimeError("HTTP 503")
        return events_by_id.get(tid, [])

    monkeypatch.setattr(rec, "_rows", _rows)
    monkeypatch.setattr(rec, "_events", _events)
    monkeypatch.setenv("EVENT_STORE_URL", "http://store.test:8200")
    r = _Redis()
    asyncio.run(rec._cycle_once(r))
    return rec, r


def test_a_cycle_judges_each_credit_once(monkeypatch):
    rows = [
        ("a", Decimal("0.1"), "teg-lisbon", "t0", 900),     # recorded, same amount
        ("b", Decimal("2"), "teg-lisbon", "t0", 900),       # recorded, different amount
        ("c", Decimal("3"), "teg-lisbon", "t0", 7200),      # no record, past the max wait
        ("d", Decimal("4"), "teg-lisbon", "t0", 600),       # no record yet, still young
        ("e", Decimal("5"), "unknown", "t0", 900),          # an async credit: its source is another store
        ("f", Decimal("6"), "teg-lisbon", "t0", 900),       # the store did not answer
    ]
    events = {"a": [_tt("0.1")], "b": [_tt("1.9")]}
    rec, r = _drive(monkeypatch, rows, events, fail_ids=("f",))
    assert rec.last == {"verified": 1, "mismatch": 1, "unrecorded": 1, "pending": 1, "skipped": 1, "unreachable": 1}
    done = {k.rsplit(":", 1)[1]: v for k, v in r.kv.items() if k.startswith("teg:xteg:reconciled:")}
    assert done == {"a": "verified", "b": "mismatch", "c": "unrecorded", "e": "skipped"}, "pending and unreachable are asked again"


def test_a_judged_credit_is_not_asked_again(monkeypatch):
    rows = [("a", Decimal("0.1"), "teg-lisbon", "t0", 900)]
    rec = ir.InboundReconciler()
    asked = []

    async def _rows():
        return rows

    async def _events(session, base, tid):
        asked.append(tid)
        return [_tt("0.1")]

    monkeypatch.setattr(rec, "_rows", _rows)
    monkeypatch.setattr(rec, "_events", _events)
    monkeypatch.setenv("EVENT_STORE_URL", "http://store.test:8200")
    r = _Redis()
    asyncio.run(rec._cycle_once(r))
    asyncio.run(rec._cycle_once(r))
    assert asked == ["a"]


def test_the_lease_outlives_the_sleep():
    rec = ir.InboundReconciler()
    r = _Redis()
    assert asyncio.run(rec._acquire_leader(r))
    other = ir.InboundReconciler()
    assert not asyncio.run(other._acquire_leader(r)), "one leader at a time"
    assert asyncio.run(rec._acquire_leader(r)), "the holder renews"


def test_main_starts_and_stops_it():
    src = MAIN.read_text(encoding="utf-8")
    assert "await start_inbound_reconciler()" in src and "await stop_inbound_reconciler()" in src


def test_classify_reads_the_sources_record_under_either_name():
    """W4 phase 1 (agentvault2-aa, 2026-10-25): once the source's registry writes UnitsTransferred (phase 2), a credit is
    verified against it as against TokensTransferred; a legacy spelling or another event is still no record of it."""
    def _ut(amount, name="UnitsTransferred"):
        return {"event_type": name, "data": {"amount": amount, "transaction_id": "t"}}
    assert ir.classify("5", [_ut("5")]) == "verified"
    assert ir.classify("5", [_ut("4.99")]) == "mismatch"
    assert ir.classify("5", [_ut("5", "TokenTransferred")]) == "missing"
    assert ir.classify("5", [_ut("5", "UnitsLocked")]) == "missing"
    assert ir.classify("5", [_tt("1"), _ut("5")]) == "verified"
