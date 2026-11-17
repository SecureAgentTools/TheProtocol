"""D6-763 (V0663, gwo_49ccc7efec6ae43112f5bd72): staking.position_updated is sent, for the position that goes on after a partial release.

The event was in SUPPORTED_EVENTS and the console's list and documented "accepted but never sent": nothing dispatched it. A position
released in part is closed and its remainder continues as a new, smaller position (routers/staking_enhanced.unstake_tokens), which
is what "updated" says; the holder now hears of each remainder, after the release has committed. A webhook that cannot be delivered
never fails the release. RED control: against b27f2ebaf there is no dispatch_position_updated and unstake_tokens never names the event.
"""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

import agentvault_registry.background_tasks.reactor_helpers as rh
from agentvault_registry.routers import staking_enhanced as se

DID = "did:theprotocol:test:agent-1"
DOC = (Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "static" / "new_registry_frontend" / "src"
       / "assets" / "docs" / "oracle" / "21_webhooks.md")


def _pos(i, amount):
    return SimpleNamespace(id=i, amount=amount, lock_period_days=90)


def test_one_event_per_remainder_with_the_remainders_own_facts(monkeypatch):
    sent = []

    async def fake(event, data, dids, source_label=None):
        sent.append((event, data, dids, source_label))

    monkeypatch.setattr(rh, "dispatch_webhook_for_agents", fake)
    n = asyncio.run(se.dispatch_position_updated(DID, [_pos("p1", "40"), _pos("p2", "7")], "tx-1"))
    assert n == 2
    assert [s[0] for s in sent] == ["staking.position_updated"] * 2
    assert sent[0][1] == {"agent_did": DID, "position_id": "p1", "amount": "40", "lock_period_days": 90, "transaction_id": "tx-1"}
    assert sent[1][1]["position_id"] == "p2" and sent[1][2] == [DID]


def test_a_full_release_leaves_no_remainder_and_sends_nothing(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("must not dispatch")

    monkeypatch.setattr(rh, "dispatch_webhook_for_agents", boom)
    assert asyncio.run(se.dispatch_position_updated(DID, [], "tx-1")) == 0


def test_an_undeliverable_webhook_never_fails_the_release(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("dispatcher down")

    monkeypatch.setattr(rh, "dispatch_webhook_for_agents", boom)
    assert asyncio.run(se.dispatch_position_updated(DID, [_pos("p1", "1")], "tx-1")) == 0


def test_unstake_collects_the_remainder_of_a_partial_release_and_tells_the_holder_after_the_commit():
    src = inspect.getsource(se.unstake_tokens)
    assert "remainder_stakes = []" in src
    assert "remainder_stakes.append(new_stake)" in src
    commit_at, dispatch_at = src.index("await db.commit()"), src.index("dispatch_position_updated(")
    assert commit_at < dispatch_at, "the event goes out after the release has committed"


def test_the_docs_no_longer_say_it_is_never_sent():
    text = DOC.read_text(encoding="utf-8")
    assert "accepted but never sent" not in text
    assert "`staking.position_updated` is sent for a position that goes on after a partial release" in text
