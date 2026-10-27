"""§TWOAGENT #34 (2026-09-23, Session B's finding) — an owner-private webhook goes to its owner, never to the frame.

Measured on production (V0428), both directions: Session B's ASIA webhook received the EU Scrivener's agent.suspended
(its reason, the actor's developer id and the EU frame admin's email) at 11:08:26Z, and Session A's EU webhook received
Straits Assay's at 11:08:09Z; then the same for agent.reinstated (11:09:34Z, 11:10:29Z). The lifecycle reactors
dispatched with no developer_id, which the helper's own docstring reserves for platform-public events, and the
§TRUSTWIRE bridge feeds a peer frame's events into the same reactors. A census found the same broadcast on every
owner-private event the reactors fan out (slash, attestations, retry exhaustion, balance correction, bridge expiry,
health, arena invites), plus two readers that took a BRIDGED event's developer id as a local one.

The tree gate at the end keeps the class closed. RED on the pre-change tree (measured: 17 of these 18 fail there):
every test except `test_the_gate_can_see_a_broadcast`, the gate's own control.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import pathlib
import time
import types

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
H = importlib.import_module("agentvault_registry.background_tasks.reactor_helpers")

LOCAL = "did:theprotocol:eu.theprotocol.cloud:950eadac-6787-4302-a3b9-4d66d944015b"
FOREIGN = "did:theprotocol:asia.theprotocol.cloud:011dbd40-1039-4ef9-a457-404d87f2e130"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Rec:
    def __init__(self, ret=1):
        self.calls = []
        self.ret = ret

    async def __call__(self, *a, **k):
        self.calls.append((a, k))
        return self.ret


async def _none(*a, **k):
    return None


async def _no_fanout(*a, **k):
    return {"attempted": 0, "successful": 0}


def _wire(monkeypatch, modname):
    mod = importlib.import_module(f"agentvault_registry.background_tasks.{modname}")
    broadcast, for_agents = _Rec(), _Rec()
    monkeypatch.setattr(mod, "dispatch_webhook_event", broadcast, raising=False)
    monkeypatch.setattr(mod, "dispatch_webhook_for_agents", for_agents, raising=False)
    for name in ("block_agent_on_teg", "unblock_agent_on_teg"):
        monkeypatch.setattr(mod, name, _none, raising=False)
    for name in ("block_agent_on_remote_frames", "unblock_agent_on_remote_frames"):
        monkeypatch.setattr(mod, name, _no_fanout, raising=False)
    if hasattr(mod, "_last_notif_at"):
        monkeypatch.setattr(mod, "_last_notif_at", time.monotonic())  # inside the toast throttle: no WS call
    monkeypatch.setattr(mod, "is_notification_stale", lambda d: (False, 0), raising=False)
    for name in ("get_developer_email_for_agent", "send_reactor_email"):
        monkeypatch.setattr(mod, name, _none, raising=False)
    wsmod = importlib.import_module("agentvault_registry.routers.websocket")
    monkeypatch.setattr(wsmod, "broadcast_notification", _none, raising=False)
    return mod, broadcast, for_agents


def _handle(mod, cls, data):
    _run(getattr(mod, cls).handle_event(types.SimpleNamespace(name=cls), data))


def _unscoped(rec):
    return [c for c in rec.calls if c[1].get("developer_id") is None]


@pytest.mark.parametrize("modname,cls,event,key", [
    ("reactor_agent_suspended", "AgentSuspendedReactor", "agent.suspended", "target_agent_did"),
    ("reactor_agent_reinstated", "AgentReinstatedReactor", "agent.reinstated", "agent_did"),
])
@pytest.mark.parametrize("did,extra", [(LOCAL, {}), (FOREIGN, {"_foreign_frame_id": "asia.theprotocol.cloud"})])
def test_agent_lifecycle_goes_to_the_owner_only(monkeypatch, modname, cls, event, key, did, extra):
    mod, broadcast, for_agents = _wire(monkeypatch, modname)
    data = {key: did, "reason": "twoagent", "actor_email": "admin@frame.example", **extra}
    _handle(mod, cls, data)
    assert _unscoped(broadcast) == [], "no fan-out to every subscriber on the frame"
    assert [(c[0][0], c[0][2]) for c in for_agents.calls] == [(event, [did])], \
        "owner-scoped by the agent: a foreign DID has no owner here and reaches nobody"


@pytest.mark.parametrize("modname,cls,dev_event,agent_event", [
    ("reactor_developer_suspended", "DeveloperSuspendedReactor", "developer.suspended", "agent.suspended"),
    ("reactor_developer_reinstated", "DeveloperReinstatedReactor", "developer.reinstated", "agent.reinstated"),
])
def test_developer_lifecycle_goes_to_that_developer_only(monkeypatch, modname, cls, dev_event, agent_event):
    mod, broadcast, for_agents = _wire(monkeypatch, modname)
    _handle(mod, cls, {"target_developer_id": 7, "target_email": "dev7@example.org",
                       "cascade_results": [{"agent_did": LOCAL}]})
    assert _unscoped(broadcast) == []
    assert [(c[1]["event_type"], c[1]["developer_id"]) for c in broadcast.calls] == [(dev_event, 7)]
    assert [(c[0][0], c[0][2]) for c in for_agents.calls] == [(agent_event, [LOCAL])]


@pytest.mark.parametrize("modname,cls", [
    ("reactor_developer_suspended", "DeveloperSuspendedReactor"),
    ("reactor_developer_reinstated", "DeveloperReinstatedReactor"),
])
def test_a_bridged_developer_event_names_no_local_developer(monkeypatch, modname, cls):
    mod, broadcast, _ = _wire(monkeypatch, modname)
    _handle(mod, cls, {"target_developer_id": 7, "_foreign_frame_id": "asia.theprotocol.cloud", "cascade_results": []})
    assert broadcast.calls == [], "a peer's developer 7 is not ours: no developer-scoped (or any) dispatch"


@pytest.mark.parametrize("modname,cls,event,key", [
    ("reactor_agent_slashed", "AgentSlashedReactor", "agent.slashed", "defendant_did"),
    ("reactor_attestation_due_reminder", "AttestationDueReminderReactor", "attestation.due_reminder", "agent_did"),
    ("reactor_attestation_expired", "AttestationExpiredReactor", "attestation.expired", "agent_did"),
    ("reactor_bridge_transfer_expired", "BridgeTransferExpiredReactor", "bridge.transfer_expired", "source_agent_did"),
    ("reactor_attestation_revoked", "AttestationRevokedReactor", "attestation.revoked", "agent_did"),
    ("reactor_balance_corrected", "BalanceCorrectedReactor", "treasury.balance_corrected", "agent_did"),
])
def test_the_class_agent_keyed_events_go_to_the_owner(monkeypatch, modname, cls, event, key):
    mod, broadcast, for_agents = _wire(monkeypatch, modname)
    if not hasattr(mod, cls):
        pytest.fail(f"{modname} has no {cls}: the census names a reactor that moved")
    _handle(mod, cls, {key: LOCAL, "amount": "1", "reason": "x"})
    assert _unscoped(broadcast) == []
    assert [(c[0][0], c[0][2]) for c in for_agents.calls] == [(event, [LOCAL])]


def test_retry_exhausted_goes_to_the_webhooks_owner_and_a_bridged_one_to_nobody(monkeypatch):
    mod, broadcast, _ = _wire(monkeypatch, "reactor_webhook_retry_exhausted")
    mails = _Rec(ret="dev7@example.org")
    monkeypatch.setattr(mod, "get_developer_email", mails)
    monkeypatch.setattr(mod, "send_reactor_email", _none)
    _handle(mod, "WebhookRetryExhaustedReactor", {"webhook_id": "w", "developer_id": 7, "target_url": "https://x"})
    assert [(c[1]["event_type"], c[1]["developer_id"]) for c in broadcast.calls] == [("webhook.retry_exhausted", 7)]
    assert [c[0][0] for c in mails.calls] == [7]
    broadcast.calls.clear(); mails.calls.clear()
    _handle(mod, "WebhookRetryExhaustedReactor", {"webhook_id": "w", "developer_id": 7, "target_url": "https://x",
                                                  "_foreign_frame_id": "asia.theprotocol.cloud"})
    assert broadcast.calls == [] and mails.calls == [], "a peer's developer 7 is neither webhooked nor emailed here"


# ── the helper ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_local_developer_id():
    f = H.local_developer_id
    assert f({"target_developer_id": 12}) == 12 and f({"target_developer_id": "12"}) == 12
    assert f({"target_developer_id": 12, "_foreign_frame_id": "asia.theprotocol.cloud"}) is None
    assert f({"target_developer_id": "?"}) is None and f({}) is None and f(None) is None
    assert f({"developer_id": 3}, key="developer_id") == 3


# ── the tree gate: an owner-private event is never dispatched unscoped ────────────────────────────────────────────

PUBLIC = {
    "governance.proposal_created", "governance.proposal_passed", "governance.proposal_failed", "governance.vote_cast",
    "federation.peer_added", "federation.peer_removed", "federation.sync_completed", "federation.drift_detected",
    "federation.dry_run_drift", "federation.emission_policy_updated", "frame_federation.revoked",
    "operator.application_revoked", "supply.invariant_breach",
}
# dynamic event types, each reviewed: the helpers take it as a parameter and pass developer_id through; the tally
# chooses between two governance.* outcomes; the governance/federation helpers are public by name.
DYNAMIC_OK = {
    ("background_tasks/reactor_helpers.py", "dispatch_webhook_event"),
    ("background_tasks/reactor_helpers.py", "dispatch_webhook_for_agents"),
    ("background_tasks/reactor_proposal_tallied.py", "handle_event"),
    ("services/webhook_service.py", "emit_governance_event"),
    ("services/webhook_service.py", "emit_federation_event"),
}


def _enclosing(tree):
    parent = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parent[c] = n
    return parent


def _census():
    bad = []
    for p in sorted(SRC.rglob("*.py")):
        rel = p.relative_to(SRC).as_posix()
        if rel.startswith(("api_tests/", "tests/")):
            continue
        tree = ast.parse(p.read_text())
        parent = _enclosing(tree)
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
            if name == "dispatch_webhook_event":
                scoped = any(k.arg == "developer_id" for k in n.keywords)
            elif name == "emit_event" and isinstance(f, ast.Attribute) and getattr(f.value, "id", "") in (
                    "svc", "service", "ws", "self", "webhook_service"):
                scoped = any(k.arg == "developer_id" for k in n.keywords) or len(n.args) >= 5
            else:
                continue
            ev = None
            for k in n.keywords:
                if k.arg == "event_type" and isinstance(k.value, ast.Constant):
                    ev = k.value.value
            if ev is None and n.args and isinstance(n.args[0], ast.Constant):
                ev = n.args[0].value
            if scoped or (ev in PUBLIC):
                continue
            fn = n
            while fn in parent and not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = parent[fn]
            fname = getattr(fn, "name", "<module>")
            if ev is None and (rel, fname) in DYNAMIC_OK:
                continue
            bad.append(f"{rel}:{n.lineno} {name}({ev or '<dynamic>'}) in {fname}")
    return bad


@pytest.mark.skipif(not SRC.is_dir(), reason="registry source not mounted: gate NOT run")
def test_no_owner_private_event_is_dispatched_unscoped():
    bad = _census()
    assert bad == [], "owner-private webhooks dispatched to every subscriber on the frame:\n" + "\n".join(bad)


@pytest.mark.skipif(not SRC.is_dir(), reason="registry source not mounted: gate NOT run")
def test_the_gate_can_see_a_broadcast():
    """The census must find a planted broadcast, or its green means nothing."""
    planted = ast.parse('async def f():\n    await dispatch_webhook_event(event_type="agent.suspended", event_data={})\n')
    calls = [n for n in ast.walk(planted) if isinstance(n, ast.Call)]
    assert calls and not any(k.arg == "developer_id" for k in calls[0].keywords)
    assert "agent.suspended" not in PUBLIC
    assert len(list(SRC.rglob("reactor_*.py"))) >= 20, "the scan found too few reactors: the source is not where the gate looks"
