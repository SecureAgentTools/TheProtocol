"""§DOCSFIX D6-439 (2026-10-16): the dispute escalation's correlation multiplier applies once.

EnforcementEngine.evaluate_dispute_outcome multiplied the slash percent by the correlation multiplier (capped at 100%)
and then multiplied the slash amount by the same multiplier again: a correlated slash was squared, and could exceed the
disputed amount the cap was there to bound (60% at a 2x multiplier slashed 200% of it). The amount is now the disputed
amount times the (multiplied, capped) percent.

RED on the pre-change tree: the two multiplied cases. The control (no correlation) is green before and after.
"""
from __future__ import annotations

import asyncio
import types
from decimal import Decimal

import pytest

from agentvault_registry.services import enforcement_engine as ee
from tests._doubles import StrictEmitter


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Db:
    async def commit(self):
        pass


def _slash(monkeypatch, *, slash_percent, multiplier, disputed=100):
    created = []
    policy = {"dispute_escalation": {"levels": {"1": {
        "action_types": ["slash_liquid", "warn"], "slash_percent": slash_percent,
        "pause_days": 0, "admin_review_required": True}}}}

    async def _policy(self, db):
        return policy

    async def _offenses(self, db, did, pol):
        return 0

    async def _corr(self, db, did, pol):
        return 3, multiplier

    async def _agent(self, db, did):
        return types.SimpleNamespace(offense_count=0, last_offense_at=None, enforcement_level=0,
                                     rewards_paused_until=None, enforcement_status="active", status="active")

    async def _version(self, db):
        return 1

    async def _create(**kw):
        created.append(kw)
        return types.SimpleNamespace(id="act-1", status=kw["status"])
    emitter = StrictEmitter()
    monkeypatch.setattr(ee.EnforcementEngine, "_load_policy", _policy)
    monkeypatch.setattr(ee.EnforcementEngine, "_count_recent_offenses", _offenses)
    monkeypatch.setattr(ee.EnforcementEngine, "_calculate_correlation_multiplier", _corr)
    monkeypatch.setattr(ee.EnforcementEngine, "_get_agent", _agent)
    monkeypatch.setattr(ee.EnforcementEngine, "_policy_version", _version)
    monkeypatch.setattr(ee, "create_enforcement_action", _create)
    monkeypatch.setattr(ee, "get_event_emitter", lambda: emitter)
    _run(ee.EnforcementEngine().evaluate_dispute_outcome(_Db(), "did:theprotocol:defendant", "7",
                                                        disputed_amount=disputed))
    [action] = created
    # the record of the action carries the amount the action holds
    assert emitter.assert_received("EnforcementActionCreated", via="emit_event")["event_data"]["amount"] == action["amount"]
    return action


def test_a_correlated_slash_multiplies_the_percent_once(monkeypatch):
    action = _slash(monkeypatch, slash_percent=10, multiplier=2.0)
    assert action["amount"] == Decimal("20") and action["correlation_multi"] == 2.0


def test_the_100_percent_cap_bounds_the_slash_to_the_disputed_amount(monkeypatch):
    action = _slash(monkeypatch, slash_percent=60, multiplier=2.0)
    assert action["amount"] == Decimal("100")


# ── control: green before and after ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("disputed,expected", [(100, Decimal("10")), (5, Decimal("1"))])
def test_control_an_uncorrelated_slash_is_the_percent_of_the_disputed_amount(monkeypatch, disputed, expected):
    # 10% of 5 is 0.5: a slash is at least 1 unit
    assert _slash(monkeypatch, slash_percent=10, multiplier=1.0, disputed=disputed)["amount"] == expected
