"""Batch 2 item 2 — the four bond money rails must be HEARD by the emitter (the §EMITKEY hole:
30 bond tests stayed green while every emit was lost, because nothing asserted receipt).
Each rail is driven with fakes for the DB, the ledger and the card touch; the emitter is the
STRICT double (real signatures) and the test asserts the event AND its deterministic key.
"""
import os
from decimal import Decimal
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("API_KEY_SECRET", "test-only-secret-value-0123456789abcdef")

from agentvault_registry.services import reputation_bond as rb  # noqa: E402
from agentvault_registry.services import escrow as escrow_mod  # noqa: E402
import agentvault_registry.event_emitter as ee  # noqa: E402
from tests._doubles import StrictEmitter  # noqa: E402


class FakeDB:
    def __init__(self): self.added, self.commits = [], 0
    def add(self, o): self.added.append(o)
    async def commit(self): self.commits += 1
    async def refresh(self, o): pass
    async def execute(self, *a, **k): raise AssertionError("unexpected db.execute — patch the loader the rail uses")


def _agent(did="did:theprotocol:strict-1"):
    return SimpleNamespace(did=did, reputation_bond_amount=None, reputation_bond_status="none", staked_balance=Decimal("0"))


def _bond(did, **kw):
    b = SimpleNamespace(id=7, agent_did=did, status="none", amount=None, escrow_ref=None, funder_did=None,
                        funded_by=None, teg_transaction_id=None, locked_at=None, matured_at=None, released_at=None,
                        release_ref=None, release_teg_transaction_id=None, forfeit_ref=None, forfeited_at=None,
                        updated_at=None, created_at=None)
    for k, v in kw.items(): setattr(b, k, v)
    return b


@pytest.fixture
def wired(monkeypatch):
    em = StrictEmitter()
    monkeypatch.setattr(ee, "get_event_emitter", lambda: em)
    async def touch(db, did): return 1
    monkeypatch.setattr(rb, "touch_native_card", touch)
    async def pol(db): return {}
    monkeypatch.setattr(rb, "policy_json", pol)
    monkeypatch.setattr(rb, "bond_amount", lambda policy=None: Decimal("250"))
    monkeypatch.setattr(rb, "bond_mode", lambda: "shadow")
    return em


@pytest.mark.asyncio
async def test_deposit_is_heard_with_its_key(wired, monkeypatch):
    agent = _agent(); bond = _bond(agent.did)
    async def load(db, did): return bond
    monkeypatch.setattr(rb, "load_bond", load)
    moved = []
    async def dep(funder, amt, ref, reason=None): moved.append((funder, amt, ref, reason)); return {"transaction_id": "tx-dep"}
    monkeypatch.setattr(escrow_mod, "escrow_deposit", dep)
    await rb.deposit(FakeDB(), agent, funder_did=agent.did, funded_by="self", actor="test", amount=Decimal("250"), policy={})
    assert moved and moved[0][3] == "reputation_bond"
    rec = wired.assert_received("ReputationBondDeposited", key=f"repbond-dep-{bond.escrow_ref}")
    assert rec["aggregate_id"] == agent.did and rec["data"]["amount"] == "250"


@pytest.mark.asyncio
async def test_backstop_is_heard_with_its_key(wired, monkeypatch):
    agent = _agent("did:theprotocol:strict-2"); bond = _bond(agent.did)
    async def load(db, did): return bond
    monkeypatch.setattr(rb, "load_bond", load)
    monkeypatch.setattr(rb, "treasury_backstop_enabled", lambda: True, raising=False)
    await rb.backstop(FakeDB(), agent, actor="developer:1", policy={})
    wired.assert_received("ReputationBondDeposited", key=f"repbond-dep-{bond.escrow_ref}")
    assert wired.received[-1]["data"]["funded_by"] == "treasury"


@pytest.mark.asyncio
async def test_forfeit_is_heard(wired, monkeypatch):
    agent = _agent("did:theprotocol:strict-3")
    bond = _bond(agent.did, status="locked", amount=Decimal("250"), escrow_ref="repbond-x-1")
    async def load(db, did): return bond
    monkeypatch.setattr(rb, "load_bond", load)
    await rb.forfeit(FakeDB(), agent, amount=None, reason="test", ref="slash-1", actor="engine")
    rec = wired.assert_received("ReputationBondForfeited")
    assert rec["idempotency_key"] and rec["aggregate_id"] == agent.did


@pytest.mark.asyncio
async def test_matured_is_heard_with_its_key(wired, monkeypatch):
    agent = _agent("did:theprotocol:strict-4")
    bond = _bond(agent.did, status="locked", amount=Decimal("250"), escrow_ref="repbond-x-4")
    async def load_agent(db, did): return agent
    monkeypatch.setattr(rb, "load_agent", load_agent)
    await rb.stamp_matured(FakeDB(), bond, {"matured": True}, agent=agent)
    wired.assert_received("ReputationBondMatured", key=f"repbond-mat-{bond.id}-{bond.escrow_ref}")


def test_a_wrong_keyword_fails_inside_the_test_not_in_a_log():
    """The property the whole class rests on: the strict double refuses the shape that shipped."""
    import asyncio
    em = StrictEmitter()
    loop = asyncio.new_event_loop()  # §DEPS: a private loop, never the test-order-dependent shared one
    try:
        with pytest.raises(TypeError):
            loop.run_until_complete(
                em.emit_event(aggregate_id="d", event_type="X", event_data={}, idempotency_key="k"))
    finally:
        loop.close()
    em.assert_nothing_received()
