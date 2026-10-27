"""An event with several subscribed webhooks records a delivery for EVERY one of them (§TWOAGENT, 2026-09-23).

`WebhookService.emit_event` delivers to every subscribed hook concurrently. Until b0c9c49a every task wrote its
delivery row into the one session the call was given, and a session cannot run two operations at once, so with two or
more subscribers NO row survived: every POST was sent and none was recorded. That lost the delivery history, the retry
schedule and the failure count that disables a dead receiver, and nothing said so. Measured on the V0437 sandbox: one
hook recorded 1, and four hooks recorded 0 of 4, three runs out of three.

The flow subscribes three hooks (one developer, the frame admin) to `agent.deleted`, lets a throwaway agent delete
itself, and requires each hook's own record to hold exactly one delivery naming that agent. Hooks point at a `.invalid`
host (nothing leaves the box) and are deleted at the end (deliveries cascade). No money moves.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
)

_A = "sandbox-A"
_HOOKS = 3
_WAIT_SEC = 30.0


async def _call(rig, tool: str, args: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    try:
        r = await rig.mcp(_A).call(tool, args, timeout=60)
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    if isinstance(r, dict) and set(r) == {"_text"}:
        return r, r["_text"]
    return r, None


async def _held(rig, hook_id: str, did: str) -> Optional[int]:
    """Deliveries of agent.deleted naming `did` in this hook's record, or None when the record is unreadable."""
    r, refused = await _call(rig, "getWebhookDeliveries", {"webhook_id": hook_id, "limit": 100})
    if refused or not isinstance(r, dict) or not isinstance(r.get("deliveries"), list):
        return None
    n = 0
    for d in r["deliveries"]:
        if not isinstance(d, dict) or d.get("event_type") != "agent.deleted":
            continue
        p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
        data = p.get("data") if isinstance(p.get("data"), dict) else p
        if str(data.get("agent_did") or "") == did:
            n += 1
    return n


@federation_test(
    name="webhook_fanout_records_every_delivery",
    category="webhooks",
    budget_sec=90.0,
    severity="high",
    requires=[_A],
    tags=["webhooks", "fanout", "single_frame"],
)
async def test_webhook_fanout_records(rig: FederationTestRig) -> AssertionResult:
    """Three hooks on one event: each hook's record holds the delivery."""
    t0 = time.monotonic()
    hooks: List[str] = []
    state: Dict[str, Any] = {}
    passed = False
    try:
        for _ in range(_HOOKS):
            r, refused = await _call(rig, "createWebhook", {
                "url": f"https://fedsuite-whfan-{uuid.uuid4().hex[:10]}.invalid/hook", "events": ["agent.deleted"],
                "description": "federation suite: webhook fan-out records (.invalid host)"})
            if refused or not isinstance(r, dict) or not r.get("id"):
                raise PreconditionUnmet(f"createWebhook refused: {refused or str(r)[:160]}")
            hooks.append(r["id"])
        r, refused = await _call(rig, "createAgent", {"name": f"fedsuite-whfan-{uuid.uuid4().hex[:8]}",
                                                      "description": "federation suite webhook fan-out probe"})
        did = (r or {}).get("did") or (r or {}).get("agent_did") if isinstance(r, dict) else None
        throwaways.made(_A, did)  # V0641: retired once its test's verdict is in (throwaways)
        cid, sec = ((r or {}).get("client_id"), (r or {}).get("client_secret")) if isinstance(r, dict) else (None, None)
        if refused or not (did and cid and sec):
            raise PreconditionUnmet(f"createAgent refused: {refused or 'no credential triple'}")
        t, tref = await _call(rig, "getAgentToken", {"client_id": cid, "client_secret": sec})
        jwt = t.get("access_token") if isinstance(t, dict) else None
        if tref or not jwt:
            raise PreconditionUnmet(f"getAgentToken refused: {tref}")
        d, dref = await _call(rig, "deleteMyAgent", {"agent_jwt": jwt})
        state["self_delete"] = dref or "ok"
        if dref:
            raise PreconditionUnmet(f"the agent could not delete itself: {dref}")
        throwaways.retired(did)      # its own delete is the act

        end = time.monotonic() + _WAIT_SEC
        held: Dict[str, Optional[int]] = {}
        while True:
            held = {h[:8]: await _held(rig, h, did) for h in hooks}
            if all(v == 1 for v in held.values()) or time.monotonic() >= end:
                break
            await asyncio.sleep(3.0)
        state["held_per_hook"] = held
        passed = len(held) == _HOOKS and all(v == 1 for v in held.values())
    finally:
        for h in hooks:
            await _call(rig, "deleteWebhook", {"webhook_id": h})
    return AssertionResult(
        passed=passed,
        description=f"one event with {_HOOKS} subscribed hooks leaves one delivery record in each",
        budget_sec=0.0, elapsed_sec=time.monotonic() - t0, polling_attempts=1, last_state=state,
        failure_detail=None if passed else json.dumps(state, default=str)[:400])
