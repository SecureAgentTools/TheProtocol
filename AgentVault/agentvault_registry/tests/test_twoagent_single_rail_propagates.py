"""§TWOAGENT #30 (2026-09-23) — the SINGLE-agent admin suspend/reinstate reaches the peers and the owner.

Measured on V0426 before the change: `POST /api/v1/admin/enforcement/agents/{did}/suspend` flipped the agent on its
home frame and nothing else. EU's mirror of a suspended ASIA agent still read `active` after 1200 s (118 polls), ASIA's
mirror of a suspended EU agent after 900 s (80 polls), and the owner's webhook, subscribed to agent.suspended and
agent.status_changed, received nothing. The coordinated (bulk) rail touches the card (§ENFPROP: only the CARD travels
to a peer) and fires the owner-scoped webhooks; the single rail did neither. Its `enforcement.since` therefore read the
card's last unrelated change (10:06:45Z for a 10:21:30Z suspension).

RED on V0429: the card is never touched and no owner webhook is dispatched, on either leg. The controls (a re-suspend
of an already suspended agent dispatches nothing; nothing goes out unscoped) pass on both trees.
"""
from __future__ import annotations

import asyncio
import types

import pytest

from agentvault_registry.routers import enforcement_admin as ea


class _Result:
    def __init__(self, agent):
        self._a = agent

    def scalar_one_or_none(self):
        return self._a


class _DB:
    def __init__(self, agent, log):
        self.agent, self.log = agent, log

    async def execute(self, *a, **k):
        return _Result(self.agent)

    async def commit(self):
        self.log.append(("commit",))


def _wire(monkeypatch, agent_status):
    log: list = []
    agent = types.SimpleNamespace(did="did:theprotocol:asia.test:abc", status=agent_status,
                                  enforcement_status=agent_status, enforcement_level=3, rewards_paused_until=None)

    async def _policy(db):
        return None

    async def _action(db, **kw):
        return types.SimpleNamespace(id="act-1", executed_at=None, approved_by=None, **{})

    async def _touch(db, did):
        log.append(("touch", did))
        return 1

    async def _owner_dispatch(event, data, dids, source_label="endpoint"):
        log.append(("owner", event, tuple(dids), data.get("reason")))
        return 1

    async def _unscoped(event, data, source_label="reactor", developer_id=None):
        log.append(("unscoped" if developer_id is None else "scoped", event))
        return 1

    async def _notify(*a, **k):
        return None

    monkeypatch.setattr(ea.crud_enforcement, "get_active_policy", _policy)
    monkeypatch.setattr(ea.crud_enforcement, "create_enforcement_action", _action)
    from agentvault_registry.services import enforcement_propagation as ep
    monkeypatch.setattr(ep, "touch_native_card_no_commit", _touch)
    from agentvault_registry.background_tasks import reactor_helpers as rh, push_notify as pn
    monkeypatch.setattr(rh, "dispatch_webhook_for_agents", _owner_dispatch)
    monkeypatch.setattr(rh, "dispatch_webhook_event", _unscoped)
    monkeypatch.setattr(pn, "notify_agent_owners", _notify)
    return agent, _DB(agent, log), log


async def _call(route, agent, db):
    admin = types.SimpleNamespace(id=1, email="admin@frame.test")
    req = types.SimpleNamespace(reason="twoagent: time the propagation")
    out = await route(agent.did, req, db=db, admin=admin)
    for _ in range(5):                 # let the fire-and-forget dispatch tasks run
        await asyncio.sleep(0)
    return out


async def test_suspend_touches_the_card_inside_the_commit(monkeypatch):
    agent, db, log = _wire(monkeypatch, "active")
    await _call(ea.suspend_agent, agent, db)
    assert ("touch", agent.did) in log, log
    assert log.index(("touch", agent.did)) < log.index(("commit",)), log   # the touch lands in the SAME commit


async def test_suspend_tells_the_owner(monkeypatch):
    agent, db, log = _wire(monkeypatch, "active")
    await _call(ea.suspend_agent, agent, db)
    events = [e[1] for e in log if e[0] == "owner"]
    assert "agent.suspended" in events and "agent.status_changed" in events, log


async def test_reinstate_touches_the_card_and_tells_the_owner(monkeypatch):
    agent, db, log = _wire(monkeypatch, "suspended")
    await _call(ea.reinstate_agent, agent, db)
    assert ("touch", agent.did) in log and log.index(("touch", agent.did)) < log.index(("commit",)), log
    events = [e[1] for e in log if e[0] == "owner"]
    assert "agent.reinstated" in events and "agent.status_changed" in events, log


async def test_control_a_resuspend_notifies_nobody(monkeypatch):
    agent, db, log = _wire(monkeypatch, "suspended")
    await _call(ea.suspend_agent, agent, db)
    assert not [e for e in log if e[0] == "owner"], log


async def test_control_nothing_goes_out_unscoped(monkeypatch):
    agent, db, log = _wire(monkeypatch, "active")
    await _call(ea.suspend_agent, agent, db)
    agent2, db2, log2 = _wire(monkeypatch, "suspended")
    await _call(ea.reinstate_agent, agent2, db2)
    assert not [e for e in log + log2 if e[0] == "unscoped"], log + log2
