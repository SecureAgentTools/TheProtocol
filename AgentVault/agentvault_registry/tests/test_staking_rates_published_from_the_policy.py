"""§DOCSFIX CB-124 (2026-10-16): where a registry pays a reward on locked units, the rate it publishes is the rate it pays.

The daily distribution builds its rate engine from the registry's resolved policy document
(`DynamicAPYEngine.from_policy`, services/staking_rewards_service), but GET /api/v1/staking/apy-tiers, the rate stored
when a lock opens and the rate GET /staking/my-positions shows came from the engine singleton built from code defaults.
A frame whose `staking_rewards` policy differs (the lock premium is free, the floor and the TVL target are bounded) paid
another rate than it published. Those three readers use the policy's engine now (the code defaults only when the policy
cannot be read). The reward switch is off on the production frames, where these routes publish no rate at all.

§DOCSFIX review: the rate a new lock stores is computed BEFORE the TEG locks the units. It reads the policy document,
the registry's locked total and the TEG treasury (none of which the lock changes); computed after the lock, a read that
failed left units locked on the TEG with no position on the registry to unstake them from.

RED on the pre-change tree: the two policy tests and the stored rate. RED before the review: the failed rate read that
must leave nothing locked. The controls are green before and after.
"""
from __future__ import annotations

import asyncio
import copy
import types
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks, HTTPException

from agentvault_registry.background_tasks import reactor_helpers
from agentvault_registry.routers import staking_enhanced as se
from agentvault_registry.services import frame_policy
from agentvault_registry.services.dynamic_apy_engine import DynamicAPYEngine

AGENT = types.SimpleNamespace(id=7, did="did:theprotocol:sbx-alpha.theprotocol.cloud:staker-0000")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _policy():
    doc = copy.deepcopy(frame_policy.resolve(None))
    doc["staking_rewards"].update({"max_apy_percent": 8.0, "lock_premium_base_rate_percent": 4.0,
                                   "min_apy_percent": 2.0})
    return doc


@pytest.fixture
def rewards_on(monkeypatch):
    async def _tvl(self, db):
        return 12.0
    monkeypatch.setenv("STAKING_ENABLED", "true")
    monkeypatch.setenv("STAKING_REWARDS_ENABLED", "true")
    monkeypatch.setattr(DynamicAPYEngine, "get_current_tvl_pct", _tvl)


def _with_policy(monkeypatch, doc):
    async def _load(db):
        return types.SimpleNamespace(doc=doc)
    monkeypatch.setattr(frame_policy, "load", _load)


class _Db:
    def __init__(self, stakes):
        self.results = [stakes, []]

    async def execute(self, *a, **k):
        rows = self.results.pop(0)
        return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: rows))


def _stake(lock_days):
    return types.SimpleNamespace(id="s-1", agent_did=AGENT.did, amount=Decimal("100"), lock_period_days=lock_days,
                                 staked_at=datetime(2026, 10, 1, tzinfo=timezone.utc), is_active=True,
                                 apy_rate=Decimal("3.0"))


def test_the_published_tiers_are_the_policys(rewards_on, monkeypatch):
    doc = _policy()
    _with_policy(monkeypatch, doc)
    out = _run(se.get_apy_tiers(db=None))
    assert out["tiers"] == DynamicAPYEngine.from_policy(doc).get_tier_display(12.0)
    assert out["metadata"]["r_max"] == 8.0


def test_a_position_shows_the_rate_the_policy_pays(rewards_on, monkeypatch):
    doc = _policy()
    _with_policy(monkeypatch, doc)
    [pos] = _run(se.get_my_staking_positions(db=_Db([_stake(90)]), current_agent=AGENT))
    assert pos["apy"] == DynamicAPYEngine.from_policy(doc).calculate_apy(90, 12.0)


class _Teg:
    def __init__(self):
        self.locked = []

    async def get_balance(self, did):
        return Decimal("1000")

    async def stake_tokens(self, agent_id, amount):
        self.locked.append((agent_id, amount))
        return {"stake_id": "teg-s-1", "transaction_id": "teg-tx-1"}


class _StakeDb:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass

    async def rollback(self):
        pass


def _open_lock(monkeypatch, lock_days=90):
    teg, db = _Teg(), _StakeDb()

    async def _no_webhook(*a, **k):
        return None
    monkeypatch.setattr(se, "get_teg_client", lambda: teg)
    monkeypatch.setattr(reactor_helpers, "dispatch_webhook_for_agents", _no_webhook)
    agent = types.SimpleNamespace(id=7, did=AGENT.did, staked_balance=Decimal("0"), liquid_balance=Decimal("1000"))

    async def _go():
        return await se.stake_tokens(se.StakeRequest(amount=Decimal("100"), lock_period=lock_days), BackgroundTasks(),
                                     db=db, current_agent=agent, idempotency_key=None)
    return teg, db, _go


def test_a_new_lock_stores_the_rate_the_policy_pays(rewards_on, monkeypatch):
    doc = _policy()
    _with_policy(monkeypatch, doc)
    teg, db, go = _open_lock(monkeypatch)
    _run(go())
    [stake] = [o for o in db.added if isinstance(o, se.Stake)]
    assert stake.apy_rate == Decimal(str(DynamicAPYEngine.from_policy(doc).calculate_apy(90, 12.0)))
    assert teg.locked == [(AGENT.did, Decimal("100"))]


def test_a_rate_that_cannot_be_read_locks_nothing(rewards_on, monkeypatch):
    _with_policy(monkeypatch, _policy())

    async def _broken(self, db, lock_period):
        raise RuntimeError("locked total unreadable")
    monkeypatch.setattr(DynamicAPYEngine, "calculate_current_apy", _broken)
    teg, db, go = _open_lock(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _run(go())
    assert e.value.status_code == 500
    assert teg.locked == [] and db.added == []   # nothing locked on the TEG, nothing written here


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_the_factory_policy_publishes_the_default_tiers(rewards_on, monkeypatch):
    _with_policy(monkeypatch, frame_policy.resolve(None))
    out = _run(se.get_apy_tiers(db=None))
    assert out["tiers"] == DynamicAPYEngine().get_tier_display(12.0)


def test_control_no_rate_is_published_where_the_reward_switch_is_off(monkeypatch):
    monkeypatch.setenv("STAKING_ENABLED", "true")
    monkeypatch.setenv("STAKING_REWARDS_ENABLED", "false")
    out = _run(se.get_apy_tiers(db=None))
    assert out["tiers"] == [] and out["metadata"]["engine"] == "disabled"
