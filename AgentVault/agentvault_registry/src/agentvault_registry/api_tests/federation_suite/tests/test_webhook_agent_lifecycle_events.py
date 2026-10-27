"""An agent's owner hears its agent being created, updated and deleted (§TWOAGENT, 2026-09-24).

`agent.created` and `agent.updated` were subscribable and documented (agent.created is the API reference's example
event) and nothing dispatched them. Measured on the V0438 sandbox: a create, a card rewrite (200) and a self-delete
recorded agent.created 0, agent.updated 0, agent.deleted 1 (the control, dispatched since A1).

The flow subscribes one hook (the frame admin, who owns the agent) to all three, creates an agent, rewrites its card's
description through PUT /agent-cards/{did}, lets the agent delete itself, and requires ONE delivery of each event naming
the agent. The hook points at a `.invalid` host and is deleted at the end (its deliveries cascade). No money moves.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
)

_A, _ADMIN = "sandbox-A", "sandbox-A-admin"
_EVENTS = ("agent.created", "agent.updated", "agent.deleted")
_WAIT_SEC = 30.0


async def _call(rig, label: str, tool: str, args: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    try:
        r = await rig.mcp(label).call(tool, args, timeout=60)
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    if isinstance(r, dict) and set(r) == {"_text"}:
        return r, r["_text"]
    return r, None


async def _counts(rig, hook_id: str, did: str) -> Optional[Dict[str, int]]:
    r, refused = await _call(rig, _A, "getWebhookDeliveries", {"webhook_id": hook_id, "limit": 100})
    if refused or not isinstance(r, dict) or not isinstance(r.get("deliveries"), list):
        return None
    out = {e: 0 for e in _EVENTS}
    for d in r["deliveries"]:
        ev = d.get("event_type") if isinstance(d, dict) else None
        if ev not in out:
            continue
        p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
        data = p.get("data") if isinstance(p.get("data"), dict) else p
        if str(data.get("agent_did") or "") == did:
            out[ev] += 1
    return out


@federation_test(
    name="webhook_agent_lifecycle_events_reach_the_owner",
    category="webhooks",
    budget_sec=120.0,
    severity="high",
    requires=[_A, _ADMIN],
    tags=["webhooks", "agent_events", "single_frame"],
)
async def test_webhook_agent_lifecycle_events(rig: FederationTestRig) -> AssertionResult:
    """Create, rewrite, self-delete: one delivery of agent.created, agent.updated and agent.deleted each."""
    t0 = time.monotonic()
    hook: Optional[str] = None
    state: Dict[str, Any] = {}
    passed = False
    try:
        h, refused = await _call(rig, _A, "createWebhook", {
            "url": f"https://fedsuite-agev-{uuid.uuid4().hex[:10]}.invalid/hook", "events": list(_EVENTS),
            "description": "federation suite: agent lifecycle events (.invalid host)"})
        if refused or not isinstance(h, dict) or not h.get("id"):
            raise PreconditionUnmet(f"createWebhook refused: {refused or str(h)[:160]}")
        hook = h["id"]
        r, refused = await _call(rig, _A, "createAgent", {"name": f"fedsuite-agev-{uuid.uuid4().hex[:8]}",
                                                          "description": "federation suite agent lifecycle probe"})
        did = r.get("did") or r.get("agent_did") if isinstance(r, dict) else None
        throwaways.made(_A, did)  # V0641: retired once its test's verdict is in (throwaways)
        cid, sec = (r.get("client_id"), r.get("client_secret")) if isinstance(r, dict) else (None, None)
        if refused or not (did and cid and sec):
            raise PreconditionUnmet(f"createAgent refused: {refused or 'no credential triple'}")
        card, _ = await _call(rig, _ADMIN, "adminRequest", {"method": "GET", "endpoint": f"/api/v1/agent-cards/{did}"})
        cd = ((card or {}).get("response") or {}).get("card_data") if isinstance(card, dict) else None
        if not isinstance(cd, dict):
            raise PreconditionUnmet("the new agent's card could not be read back")
        cd = dict(cd, description="federation suite: the card rewritten (agent.updated)")
        up, _ = await _call(rig, _ADMIN, "adminRequest", {"method": "PUT", "endpoint": f"/api/v1/agent-cards/{did}",
                                                          "body": {"card_data": cd}})
        state["update_status"] = up.get("status_code") if isinstance(up, dict) else None
        t, tref = await _call(rig, _A, "getAgentToken", {"client_id": cid, "client_secret": sec})
        jwt = t.get("access_token") if isinstance(t, dict) else None
        d, dref = await _call(rig, _A, "deleteMyAgent", {"agent_jwt": jwt}) if jwt else (None, tref)
        state["self_delete"] = dref or "ok"
        if not dref:
            throwaways.retired(did)      # its own delete is the act
        end = time.monotonic() + _WAIT_SEC
        counts: Optional[Dict[str, int]] = None
        while True:
            counts = await _counts(rig, hook, did)
            if (counts and all(v == 1 for v in counts.values())) or time.monotonic() >= end:
                break
            await asyncio.sleep(3.0)
        state["deliveries"] = counts
        passed = state["update_status"] == 200 and not dref and bool(counts) and all(v == 1 for v in counts.values())
    finally:
        if hook:
            await _call(rig, _A, "deleteWebhook", {"webhook_id": hook})
    return AssertionResult(
        passed=passed, description="an agent's owner hears agent.created, agent.updated and agent.deleted, once each",
        budget_sec=0.0, elapsed_sec=time.monotonic() - t0, polling_attempts=1, last_state=state,
        failure_detail=None if passed else json.dumps(state, default=str)[:400])
