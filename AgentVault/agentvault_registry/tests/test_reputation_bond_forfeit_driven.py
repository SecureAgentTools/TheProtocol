"""§BATCH7 — the forfeiture path DRIVEN, with receipt asserted (agentvault2-eb's coverage debt).

`ReputationBondForfeited` fired 26 times on the sandbox EventStore and never from a test. This drives
`services.reputation_bond.forfeit()` through a stub session with a locked bond, a fake emitter that RECORDS
what it received (never a fake that only accepts), and asserts: the money bookkeeping (absorbed / remaining /
status), the card touch, and the emitted event WITH its deterministic idempotency key (`repbond-forf-<ref>`),
for a full and a partial forfeit. No DB, no network.
"""
from __future__ import annotations

import asyncio
import pathlib
from decimal import Decimal

import pytest

import agentvault_registry as _pkg

SRC = pathlib.Path(_pkg.__file__).resolve().parent


@pytest.fixture
def rb(monkeypatch):
    import agentvault_registry.services.reputation_bond as mod  # the real module
    return mod


class _Bond:
    def __init__(self, amount="250", status="locked"):
        self.id = "bond-1"; self.amount = Decimal(amount); self.status = status; self.funded_by = "self"
        self.forfeit_ref = None; self.forfeited_at = None; self.forfeit_reason = None; self.updated_at = None


class _Agent:
    did = "did:theprotocol:drive-forfeit"
    reputation_bond_status = "locked"
    reputation_bond_amount = Decimal("250")


class _DB:
    def __init__(self): self.commits = 0
    async def commit(self): self.commits += 1


class _Emitter:
    """Records every emit; returns True (accepted)."""
    def __init__(self): self.received = []
    async def emit(self, **kw): self.received.append(kw); return True


def _drive(rb, monkeypatch, bond, amount):
    db = _DB(); agent = _Agent(); em = _Emitter(); touched = []
    async def _load(_db, did): return bond
    async def _touch(_db, did): touched.append(did)
    monkeypatch.setattr(rb, "load_bond", _load)
    monkeypatch.setattr(rb, "touch_native_card", _touch)
    import agentvault_registry.event_emitter as _ee  # the lazy import inside rb._emit reads THIS module
    monkeypatch.setattr(_ee, "get_event_emitter", lambda: em)
    monkeypatch.setattr(rb, "frame_currency", lambda: "JUICE", raising=False)
    absorbed = asyncio.run(rb.forfeit(db, agent, amount=amount, reason="enforcement slash", ref="slash-ref-1", actor="test"))
    return absorbed, bond, agent, db, em, touched


def test_full_forfeit_closes_the_bond_and_the_event_is_received_with_its_key(rb, monkeypatch):
    absorbed, bond, agent, db, em, touched = _drive(rb, monkeypatch, _Bond("250"), None)
    assert absorbed == Decimal("250")
    assert bond.status == "forfeited" and bond.forfeited_at is not None and bond.forfeit_ref == "slash-ref-1"
    assert agent.reputation_bond_status == "forfeited" and agent.reputation_bond_amount == Decimal(0)
    assert db.commits == 1 and touched == [agent.did]
    assert len(em.received) == 1, em.received
    ev = em.received[0]
    assert ev["event_type"] == "ReputationBondForfeited" and ev["aggregate_id"] == agent.did
    assert ev["idempotency_key"] == "repbond-forf-slash-ref-1"
    assert ev["data"]["amount"].startswith("250") and ev["data"]["remaining"].startswith("0")
    assert ev["data"]["currency"] == "JUICE" and ev["data"]["reason"] == "enforcement slash"


def test_partial_forfeit_keeps_the_bond_locked(rb, monkeypatch):
    absorbed, bond, agent, db, em, touched = _drive(rb, monkeypatch, _Bond("250"), Decimal("100"))
    assert absorbed == Decimal("100")
    assert bond.status == "locked" and bond.forfeited_at is None and bond.amount == Decimal("150")
    assert agent.reputation_bond_amount == Decimal("150") and agent.reputation_bond_status == "locked"
    assert em.received and em.received[0]["data"]["remaining"].startswith("150")


def test_no_bond_or_wrong_state_forfeits_nothing_and_emits_nothing(rb, monkeypatch):
    absorbed, bond, agent, db, em, touched = _drive(rb, monkeypatch, _Bond("250", status="released"), None)
    assert absorbed == Decimal(0) and db.commits == 0 and em.received == [] and touched == []


def test_control_a_fake_that_never_asserts_receipt_would_pass_on_a_dropped_emit(rb, monkeypatch):
    """The §EMITKEY lesson made explicit: an emitter that swallows proves nothing — this test's value is
    that `em.received` is asserted above. Here the emitter raises and forfeit() must NOT propagate (the
    service logs and continues), so a receipt-less test would still be green — the receipt assertion is
    what carries the coverage."""
    bond = _Bond("250"); db = _DB(); agent = _Agent(); touched = []
    class _Bad:
        async def emit(self, **kw): raise RuntimeError("ledger down")
    async def _load(_db, did): return bond
    async def _touch(_db, did): touched.append(did)
    monkeypatch.setattr(rb, "load_bond", _load); monkeypatch.setattr(rb, "touch_native_card", _touch)
    import agentvault_registry.event_emitter as _ee
    monkeypatch.setattr(_ee, "get_event_emitter", lambda: _Bad())
    absorbed = asyncio.run(rb.forfeit(db, agent, amount=None, reason="r", ref="x", actor="t"))
    assert absorbed == Decimal("250")  # the money bookkeeping happened; only the event was lost
