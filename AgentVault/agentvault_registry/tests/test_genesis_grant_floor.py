"""§MONEY-M2 / R14 — the genesis-grant treasury floor.

The reward waterfall is honest about running dry: it commits what it can and
reports `partial`. What it cannot do is DECLINE. On a low-supply network a burst
of registrations empties the treasury one complete grant at a time, and the
first person to arrive at an empty treasury gets a partial grant — a worse
outcome than being told the network is full.

The floor makes that a refusal instead: status `deferred`, no legs, no money.

Three properties are pinned here, and the third is the one that usually rots:
  * disabled by default (0) ⇒ the treasury is not even read ⇒ byte-inert
  * below the floor ⇒ `deferred`, and the waterfall is never called
  * treasury UNREADABLE ⇒ a third state, not silently folded into either. It
    fails OPEN (a transient TEG read must not stop a person's first agent) and
    says so loudly, because a guard whose failures are invisible is not a guard.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agentvault_registry.core import network_profile as np
from agentvault_registry.routers import onboarding


class _FakeTEG:
    def __init__(self, balance=None, raises=None):
        self._balance, self._raises = balance, raises

    async def get_treasury_info(self):
        if self._raises:
            raise self._raises
        return {"treasury_balance": str(self._balance)}


@pytest.fixture
def wired(monkeypatch):
    """Wire the two collaborators and record whether the waterfall ran."""
    calls = {"waterfall": 0}

    async def _fake_waterfall(db, **kw):
        calls["waterfall"] += 1
        return {
            "status": "completed", "first_transaction_id": "tx-1",
            "legs": [{"source": "treasury"}], "events_emitted": 2,
            "funded_amount": kw.get("amount"), "shortfall": "0",
        }

    import agentvault_registry.services.reward_funding as rf
    monkeypatch.setattr(rf, "fund_reward_via_waterfall", _fake_waterfall)
    monkeypatch.delenv("NETWORK_PROFILE", raising=False)
    monkeypatch.delenv("GENESIS_GRANT_TREASURY_FLOOR", raising=False)
    np.reset_cache()
    return calls


def _set_teg(monkeypatch, teg):
    import agentvault_registry.teg_client as tc
    monkeypatch.setattr(tc, "get_teg_client", lambda: teg)


# ── disabled by default ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_floor_disabled_by_default_never_reads_the_treasury(wired, monkeypatch):
    class _Explodes:
        async def get_treasury_info(self):
            raise AssertionError("the treasury must not be read when the floor is 0")
    _set_teg(monkeypatch, _Explodes())
    status, _ = await onboarding.mint_genesis_grant("did:theprotocol:x", db=None)
    assert status == "completed"
    assert wired["waterfall"] == 1


# ── above / below ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_comfortably_above_the_floor_grants(wired, monkeypatch):
    monkeypatch.setenv("GENESIS_GRANT_TREASURY_FLOOR", "200000")
    _set_teg(monkeypatch, _FakeTEG(balance="1000000"))
    status, _ = await onboarding.mint_genesis_grant("did:theprotocol:x", db=None)
    assert status == "completed"
    assert wired["waterfall"] == 1


@pytest.mark.asyncio
async def test_below_the_floor_defers_and_moves_no_money(wired, monkeypatch):
    monkeypatch.setenv("GENESIS_GRANT_TREASURY_FLOOR", "200000")
    _set_teg(monkeypatch, _FakeTEG(balance="200500"))   # 200500 - 1000 < 200000
    status, tx = await onboarding.mint_genesis_grant("did:theprotocol:x", db=None)
    assert status == "deferred"
    assert tx == "deferred_treasury_floor"
    assert wired["waterfall"] == 0, "a deferred grant must not call the waterfall at all"


@pytest.mark.asyncio
async def test_the_boundary_is_inclusive(wired, monkeypatch):
    """Landing exactly ON the floor is allowed; the floor is a floor, not a moat."""
    monkeypatch.setenv("GENESIS_GRANT_TREASURY_FLOOR", "200000")
    _set_teg(monkeypatch, _FakeTEG(balance="201000"))   # 201000 - 1000 == 200000
    status, _ = await onboarding.mint_genesis_grant("did:theprotocol:x", db=None)
    assert status == "completed"


# ── the third state ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_unreadable_treasury_fails_open_and_is_counted(wired, monkeypatch, caplog):
    monkeypatch.setenv("GENESIS_GRANT_TREASURY_FLOOR", "200000")
    _set_teg(monkeypatch, _FakeTEG(raises=RuntimeError("TEG down")))
    with caplog.at_level("ERROR"):
        status, _ = await onboarding.mint_genesis_grant("did:theprotocol:x", db=None)
    assert status == "completed", "a transient TEG read must not block a first agent"
    assert wired["waterfall"] == 1
    assert any("could NOT be enforced" in r.getMessage() for r in caplog.records), \
        "an unenforceable floor must say so at ERROR — silence here is the defect"


# ── the profile owns the value ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_floor_can_come_from_a_profile_file(wired, monkeypatch, tmp_path):
    (tmp_path / "network_profile.t.env").write_text("GENESIS_GRANT_TREASURY_FLOOR=200000\n")
    monkeypatch.setenv("NETWORK_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("NETWORK_PROFILE", "t")
    np.reset_cache()
    _set_teg(monkeypatch, _FakeTEG(balance="200500"))
    status, _ = await onboarding.mint_genesis_grant("did:theprotocol:x", db=None)
    assert status == "deferred"
    assert np.money_knob("GENESIS_GRANT_TREASURY_FLOOR", "0") == Decimal("200000")
