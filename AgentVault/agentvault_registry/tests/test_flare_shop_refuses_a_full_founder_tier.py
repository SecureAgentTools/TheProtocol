"""§DOCSFIX D6-396 (2026-10-16): the flare shop refuses a founder purchase once the founder tier is full, before any
money moves.

Founder is capped at 100 bearers; past the cap the shared grant writer falls back to architect. The shop charged the
founder price first and only then granted, so a buyer was charged 10000 for an architect flare worth 2500 (the
catalog's `cap_full` said so, the purchase did not ask). A new founder purchase now counts the bearers the way the grant
writer does and refuses with 409 and "nothing was charged" when the tier is full. A stranded purchase whose money
already moved is still resumed (and granted what the writer grants).

RED on the pre-change tree: the full-tier test. The controls are green before and after.
"""
from __future__ import annotations

import asyncio
import types

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import flare_shop as fs
from agentvault_registry.services import flare_grants

BUYER = "did:theprotocol:eu.theprotocol.cloud:buyer-0000"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Db:
    def __init__(self, founders, pending=None):
        self.founders = founders
        self.pending = pending
        self.buyer = types.SimpleNamespace(did=BUYER, creator_developer_id=5, status="active")

    async def execute(self, stmt, *a, **k):
        sql = str(stmt).lower()
        if "count(" in sql:
            return types.SimpleNamespace(scalar=lambda: self.founders)
        if "flare_shop_purchases" in sql:
            return types.SimpleNamespace(scalar_one_or_none=lambda: self.pending)
        return types.SimpleNamespace(scalar_one_or_none=lambda: self.buyer)

    def add(self, obj):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


@pytest.fixture
def shop(monkeypatch):
    calls = types.SimpleNamespace(charged=[], granted=[])

    async def _charge(*, buyer, amount, purchase_id, tier, db, row):
        calls.charged.append((tier, amount))
        return "tx-1", None

    async def _grant(db, *, developer_id, target_agent_did, proposed, source_kind, source_id, commit=True):
        calls.granted.append(proposed)
        return {"granted": proposed, "founder_cap_fallback": False}
    monkeypatch.setenv("FLARE_LOCAL_PURCHASE_ENABLED", "true")
    monkeypatch.delenv("FLARE_SHOP_PRICES", raising=False)
    monkeypatch.setattr(fs, "_charge_buyer", _charge)
    monkeypatch.setattr(flare_grants, "grant_flare_tier", _grant)
    return calls


def _buy(db, tier="founder"):
    dev = types.SimpleNamespace(id=5, flare_tier=None, email="buyer@example.org")
    return _run(fs.purchase_flare(fs.FlarePurchaseRequest(tier=tier, buyer_agent_did=BUYER), db=db, current_dev=dev))


def test_a_founder_purchase_with_the_tier_full_is_refused_before_any_charge(shop):
    with pytest.raises(HTTPException) as e:
        _buy(_Db(founders=flare_grants.FOUNDER_CAP))
    assert e.value.status_code == 409 and "nothing was charged" in e.value.detail.lower()
    assert shop.charged == [] and shop.granted == []


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_a_founder_purchase_under_the_cap_is_charged_and_granted(shop):
    out = _buy(_Db(founders=flare_grants.FOUNDER_CAP - 1))
    assert shop.charged == [("founder", fs._DEFAULT_PRICES["founder"])] and out["granted"] == "founder"


def test_control_a_stranded_founder_purchase_is_resumed_even_with_the_tier_full(shop):
    pending = types.SimpleNamespace(id="p-1", tier="founder", target_agent_did=BUYER, status="pending")
    out = _buy(_Db(founders=flare_grants.FOUNDER_CAP, pending=pending))
    assert out["resumed"] is True and shop.charged == [("founder", fs._DEFAULT_PRICES["founder"])]


def test_control_another_tier_is_not_counted_against_the_founder_cap(shop):
    out = _buy(_Db(founders=flare_grants.FOUNDER_CAP), tier="architect")
    assert out["granted"] == "architect"
