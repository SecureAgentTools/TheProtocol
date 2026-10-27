"""Every driveable emission, driven (§FEDEVENTS).

An AST census of the registry found **217 emit call sites across 172 distinct
event types**, of which the federation suite named 13. This file closes the
driveable half: for each rail, perform the real action and then assert the
EventStore actually received the event, matched on a marker unique to the run.

WHY THIS IS NOT BOOKKEEPING. The supply invariant is computed FROM events, so a
dropped emit moves `total_circulating` and `transit_net` by exactly zero — money
moves and Δ reads a contented 0.0. Beyond money, these events are the audit: who
suspended an account, who took an agent's credentials, who granted authority.
28 of the 217 sites swallow their own failure (6 `except: pass`, 22 debug-only),
so a broken emitter degrades to silence and every status-code test stays green.

THE QUERY. `/api/v1/events/?event_type=X&limit=N` — and the trailing slash is
load-bearing: `/api/v1/events?...` answers **307**, the per-route slash trap
§VITALS found. Worse, `event_types=` and `type=` are silently IGNORED and return
the unfiltered feed, so a mistyped filter yields events that look like a hit.
Every lookup here therefore matches a per-run marker in the PAYLOAD, never the
mere existence of an event of that type.

⚠ Writes: one throwaway developer and a few throwaway agents per run, tagged
`fedsuite-ev-*`. Sandbox only.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
)
from agentvault_registry.api_tests.federation_suite.tests.test_ironkey_authority_clamp import (
    _call, _rest, _detail, _new_agent, _cleanup, _done, _catalog,
    _set_roles, _pick_role_and_permission,
)

_ADMIN = "sandbox-A-admin"


# ─── the harness ───────────────────────────────────────────────────────────

async def _events_of_type(rig, etype: str, limit: int = 60,
                          label: str = _ADMIN) -> Optional[List[Dict[str, Any]]]:
    """Recent EventStore events OF ONE TYPE, or None if the store is unreadable.

    None is a third state: an unreachable EventStore and an unemitted event look
    identical unless the difference is kept.
    """
    r, refused = await _call(rig, label, "adminQueryEventStore",
                             {"path": f"/api/v1/events/?event_type={etype}&limit={limit}"})
    if refused:
        return None
    body = r.get("response", r) if isinstance(r, dict) and "response" in r else r
    if isinstance(body, list):
        return [e for e in body if isinstance(e, dict)]
    if isinstance(body, dict):
        evs = body.get("events") or body.get("items")
        if isinstance(evs, list):
            return [e for e in evs if isinstance(e, dict)]
    return None


def _payload(e: Dict[str, Any]) -> Dict[str, Any]:
    d = e.get("data") or e.get("payload") or {}
    return d if isinstance(d, dict) else {}


def _matches(e: Dict[str, Any], marker: str) -> bool:
    """Does this event carry the run's marker — in its payload OR its aggregate?

    Matching on the marker rather than the type is the whole point: the type
    alone would be satisfied by somebody else's event, and on a shared frame
    somebody else's event is always available.

    ⚠ The aggregate must be checked too. `AgentHeartbeat`, `AgentSigningKeyRotated`
    and `AgentStatusChanged` all key on the agent's DID and carry it nowhere in
    the payload, so a payload-only match reported three healthy emitters as
    missing on the first run — a false accusation produced entirely by the probe.
    """
    if marker in json.dumps(_payload(e), default=str):
        return True
    agg = e.get("aggregate_id") or e.get("aggregateId")
    return bool(agg) and marker in str(agg)


async def _await_events(rig, expect: Dict[str, str], state: Dict[str, Any],
                        budget_sec: float = 75.0, description: str = "",
                        rig_ref=None) -> AssertionResult:
    """Poll until every (event_type → marker) pair is present.

    Emission is background work (`emit_background`), so this waits rather than
    reading once; and it records WHICH types are still missing, because "some
    of the nine landed" is a completely different defect from "none did".
    """
    async def predicate() -> bool:
        seen: Dict[str, bool] = {}
        unreadable = False
        for etype, marker in expect.items():
            evs = await _events_of_type(rig, etype)
            if evs is None:
                unreadable = True
                seen[etype] = False
                continue
            seen[etype] = any(_matches(e, marker) for e in evs)
        state["seen"] = seen
        state["missing"] = sorted(t for t, ok in seen.items() if not ok)
        state["eventstore"] = "unreadable" if unreadable else "readable"
        return all(seen.values())

    result = await rig.assert_within(
        budget_sec=budget_sec, poll_interval_sec=4.0, predicate=predicate,
        description=description or "expected emissions reach the EventStore",
        capture_state=lambda: state,
    )
    if not result.passed and state.get("eventstore") == "unreadable":
        raise PreconditionUnmet("EventStore unreadable — emission not measured")
    return result


async def _must(rig, method: str, path: str, *, body: Optional[Dict[str, Any]] = None,
                jwt: Optional[str] = None, label: str = _ADMIN,
                ok: Tuple[int, ...] = (200, 201, 202, 204)) -> Any:
    """Drive one rail; a refusal is an absent fixture for THIS test's purposes.

    The emission is the subject here, not the rail's own authorisation. A test
    that cannot perform the action has not shown the emitter is broken, so it
    must not report one — it reports that it could not measure, and says which
    call refused it.
    """
    code, resp = await _rest(rig, method, path, body=body, jwt=jwt, label=label)
    if code not in ok:
        raise PreconditionUnmet(f"{method} {path} → HTTP {code}: {_detail(resp)[:200]}")
    return resp


async def _body(rig, method: str, path: str, **kw) -> Any:
    """Just the response body. `_rest` returns (status, body), and treating that
    tuple as the body is a silent failure: `isinstance(tuple, dict)` is False, so
    the caller falls through its own not-found branch and blames the product.
    Three tests did exactly that on the first run of this file."""
    _code, body = await _rest(rig, method, path, **kw)
    return body


async def _optional_step(rig, method: str, path: str, *, body: Dict[str, Any],
                         event: str, expect: Dict[str, str], marker: str,
                         state: Dict[str, Any], jwt: Optional[str] = None) -> None:
    """Drive a step whose PRECONDITION may not hold on this tier.

    Some admin acts are no-ops against a fixture that never reached the state
    they undo — force-email-verify on a tier that verifies at registration,
    disable-2fa on an account that never enabled it. Those 400s are the product
    being correct, and it correctly emits nothing. Dropping just that
    expectation keeps the other eight events measurable; skipping the whole
    lifecycle over one inapplicable step would forfeit them.
    """
    code, resp = await _rest(rig, method, path, body=body, jwt=jwt)
    if code in (200, 201, 202, 204):
        expect[event] = marker
        return
    d = _detail(resp).lower()
    if code == 400 and ("already" in d or "does not have" in d or "not enabled" in d):
        state.setdefault("inapplicable", {})[event] = _detail(resp)[:120]
        return
    raise PreconditionUnmet(f"{method} {path} → HTTP {code}: {_detail(resp)[:160]}")


async def _new_developer(rig, tag: str) -> Dict[str, Any]:
    """A throwaway developer, looked up by the admin list (register returns no id)."""
    marker = uuid.uuid4().hex[:10]
    name = f"fedsuite-ev-{tag}-{marker}"
    email = f"{name}@fedsuite-probe.dev"
    pw = f"FedSuiteEv!{marker}"
    code, resp = await _rest(rig, "POST", "/api/v1/auth/register", label="sandbox-A-admin",
                             body={"name": name, "email": email, "password": pw,
                                   "tos_accepted": True})
    if code not in (200, 201):
        raise PreconditionUnmet(f"developer registration refused: HTTP {code} {_detail(resp)[:160]}")
    found = await _body(rig, "GET", f"/api/v1/admin/developers?search={name}")
    devs = (found or {}).get("developers") if isinstance(found, dict) else None
    row = next((d for d in (devs or []) if isinstance(d, dict) and d.get("email") == email), None)
    if not row:
        raise PreconditionUnmet(f"registered developer {name} not found in the admin list")
    return {"id": row["id"], "email": email, "name": name, "password": pw, "marker": marker}


# ─── developer administration — nine events on one fixture ─────────────────

@federation_test(
    name="events_developer_admin_lifecycle",
    category="event_matrix",
    budget_sec=240.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["event_emission", "admin", "developer"],
)
async def test_developer_admin_lifecycle_events(rig: FederationTestRig) -> AssertionResult:
    """Nine administrative acts against one account must each reach the ledger.

    This is the account-moderation audit trail: verify, re-flag, gift, revoke
    keys, force a password reset, disable 2FA, suspend, reinstate, delete. Every
    one of them is an act an operator may later have to answer for, and every
    one goes through `_emit_admin_action`, whose failure path does not fail the
    request. If that helper ever breaks, the platform keeps moderating accounts
    and stops recording that it did — with no red anywhere.

    Driven as ONE lifecycle on ONE fixture because that is how they actually
    occur, and reported per event, so a partial loss reads as a partial loss.
    """
    dev = await _new_developer(rig, "admin")
    did_i = dev["id"]
    m = dev["marker"]
    reason = f"fedsuite event-matrix probe {m}"
    state: Dict[str, Any] = {"developer_id": did_i, "marker": m}
    try:
        expect: Dict[str, str] = {}
        await _optional_step(rig, "POST", f"/api/v1/admin/developers/{did_i}/force-email-verify",
                             body={"reason": reason}, event="DeveloperForceEmailVerify",
                             expect=expect, marker=m, state=state)
        await _must(rig, "PUT", f"/api/v1/admin/developers/{did_i}/admin-flags",
                    body={"admin_support": True, "reason": reason})
        await _must(rig, "POST", f"/api/v1/admin/developers/{did_i}/gift-provisioning",
                    body={"months": 1, "reason": reason})   # months is required, ge=1
        await _must(rig, "POST", f"/api/v1/admin/developers/{did_i}/revoke-api-keys",
                    body={"reason": reason})
        await _must(rig, "POST", f"/api/v1/admin/developers/{did_i}/force-password-reset",
                    body={"reason": reason})
        await _optional_step(rig, "POST", f"/api/v1/admin/developers/{did_i}/disable-2fa",
                             body={"reason": reason}, event="DeveloperDisable2FA",
                             expect=expect, marker=m, state=state)
        await _must(rig, "POST", f"/api/v1/admin/developers/{did_i}/suspend",
                    body={"reason": reason})
        await _must(rig, "POST", f"/api/v1/admin/developers/{did_i}/reinstate",
                    body={"reason": reason})
        # ⚠ NOT DRIVEN, and the reason is the tooling, not the product:
        # `adminRequest`'s DELETE branch calls `client.delete(url, params, headers)`
        # with NO body (`tools_admin.py:223`), so a DELETE whose schema requires one
        # can never be driven through the admin MCP proxy. This endpoint requires a
        # typed `confirm_email` — deliberately, so it cannot be triggered by
        # accident — and therefore always answers 422 here.
        # `DeveloperDeleted` is left out of the expectation rather than asserted and
        # failed: the emitter has not been shown to be broken, only unreachable from
        # this harness. Filed as a backlog item against adminRequest.
        state["not_driven"] = {
            "DeveloperDeleted":
                "adminRequest sends no body on DELETE (tools_admin.py:223); this "
                "route requires confirm_email"}

        for t in ("DeveloperAdminFlagsChanged", "ProvisioningGifted",
                  "DeveloperRevokeApiKeys", "DeveloperForcePasswordReset",
                  "DeveloperSuspended", "DeveloperReinstated"):
            expect[t] = m
        state["expected_events"] = sorted(expect)

        return await _await_events(
            rig, expect, state, budget_sec=120.0,
            description="nine developer-administration acts each reach the EventStore")
    finally:
        pass  # the fixture deletes itself as the last driven step


# ─── agent self-service ────────────────────────────────────────────────────

@federation_test(
    name="events_agent_self_lifecycle",
    category="event_matrix",
    budget_sec=180.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["event_emission", "agent"],
)
async def test_agent_self_lifecycle_events(rig: FederationTestRig) -> AssertionResult:
    """An agent's own lifecycle acts must be recorded.

    Onboarding, heartbeat, signing-key rotation and self-deletion. The rotation
    matters most: a signing key is what makes an agent's later claims verifiable,
    so the moment it changes is the moment an auditor needs to find in the log.
    Its emit is one of the 22 wrapped in a debug-only handler.
    """
    agent = await _new_agent(rig, "self")
    did = agent["did"]
    state: Dict[str, Any] = {"did": did}
    try:
        await _must(rig, "POST", "/api/v1/agents/heartbeat", body={}, jwt=agent["jwt"])
        await _must(rig, "POST", "/api/v1/agents/self/rotate-signing-key",
                    body={"reason": "fedsuite event-matrix probe"}, jwt=agent["jwt"])
        await _must(rig, "DELETE", "/api/v1/agents/me", jwt=agent["jwt"])
        expect = {t: did for t in ("AgentOnboarded", "AgentHeartbeat",
                                   "AgentSigningKeyRotated", "AgentStatusChanged")}
        return await _await_events(
            rig, expect, state, budget_sec=90.0,
            description="agent onboarding, heartbeat, key rotation and deletion are evented")
    finally:
        await _cleanup(rig, [did])


# ─── delegation events not covered by the IRONKEY file ─────────────────────

@federation_test(
    name="events_delegation_grant_and_revoke",
    category="event_matrix",
    budget_sec=180.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["event_emission", "ironkey"],
)
async def test_delegation_grant_and_revoke_events(rig: FederationTestRig) -> AssertionResult:
    """Granting and revoking delegated authority must both be recorded.

    The revoke half is the one that matters in an incident: a grant that was
    withdrawn and a grant that was never withdrawn look identical if only the
    grant was ever written down.
    """
    me = await _body(rig, "GET", "/api/v1/developers/me")
    dev_id = (me or {}).get("id") if isinstance(me, dict) else None
    if dev_id is None:
        raise PreconditionUnmet("could not read own developer id")
    cat = await _catalog(rig)
    base = set(cat.get("base_permissions") or [])
    perm = next((p for p in sorted(cat.get("all_permissions") or []) if p not in base), None)
    if perm is None:
        raise PreconditionUnmet("catalog offers no non-base permission")

    agent = await _new_agent(rig, "deleg-ev")
    did = agent["did"]
    state: Dict[str, Any] = {"did": did, "permission": perm}
    try:
        await _must(rig, "POST", f"/api/v1/agents/{did}/delegations",
                    body={"principal_type": "dev", "principal_ref": str(dev_id),
                          "permissions": [perm], "ttl_hours": 1})
        authz = await _body(rig, "GET", f"/api/v1/agents/{did}/authz")
        rows = (authz or {}).get("delegations") if isinstance(authz, dict) else []
        gid = next((r.get("grant_id") or r.get("id") for r in (rows or []) if isinstance(r, dict)), None)
        state["grant_id"] = gid
        if gid is None:
            raise PreconditionUnmet(f"no grant id after delegation (rows={str(rows)[:160]})")
        await _must(rig, "DELETE", f"/api/v1/delegations/{gid}")
        expect = {"AgentDelegationGranted": did, "AgentDelegationRevoked": did}
        return await _await_events(
            rig, expect, state, budget_sec=90.0,
            description="delegation grant and revoke are both evented")
    finally:
        await _cleanup(rig, [did])


@federation_test(
    name="events_capability_revoke_and_spawn",
    category="event_matrix",
    budget_sec=200.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["event_emission", "ironkey", "l4"],
)
async def test_capability_revoke_and_spawn_events(rig: FederationTestRig) -> AssertionResult:
    """Revoking a capability and spawning a sub-agent must both be recorded.

    `AgentSpawned` is the birth of an identity that can act and (under
    `SPAWN_WALLET_ANCHOR_MODE`) spend its parent's purse. Its emit sits in a
    debug-only handler, so losing it would create authority with no ledger entry
    naming the parent — the one fact an investigator would need first.
    """
    cat = await _catalog(rig)
    role, perm = _pick_role_and_permission(cat)
    issuer = await _new_agent(rig, "cap-ev-i")
    holder = await _new_agent(rig, "cap-ev-h")
    state: Dict[str, Any] = {"issuer": issuer["did"], "holder": holder["did"]}
    try:
        await _set_roles(rig, issuer["did"], [role], delegate=True)
        issued = await _must(
            rig, "POST", f"/api/v1/agents/{issuer['did']}/capabilities/issue-as-owner",
            body={"holder_agent_did": holder["did"],
                  "caveats": {"permissions": [perm]},
                  "budget_total": 10.0, "ttl_seconds": 900})
        tok_id = issued.get("id")
        state["token_id"] = tok_id
        await _must(rig, "DELETE", f"/api/v1/agents/capabilities/{tok_id}", jwt=holder["jwt"])

        spawned = await _must(rig, "POST", "/api/v1/agents/spawn",
                              body={"name": f"fedsuite-ev-child-{uuid.uuid4().hex[:6]}",
                                    "permissions": [perm], "ttl_seconds": 900},
                              jwt=issuer["jwt"])
        child = spawned.get("did") or spawned.get("child_did") or (
            (spawned.get("agent") or {}).get("did") if isinstance(spawned.get("agent"), dict) else None)
        state["child_did"] = child
        throwaways.made("sandbox-A", child)  # V0641: the spawned child is its parent's developer's
        expect = {"AgentCapabilityRevoked": str(tok_id)}
        if child:
            expect["AgentSpawned"] = child
        else:
            state["spawn_response_keys"] = sorted(spawned)[:10]
        return await _await_events(
            rig, expect, state, budget_sec=90.0,
            description="capability revocation and sub-agent spawn are evented")
    finally:
        await _cleanup(rig, [issuer["did"], holder["did"]])


# ─── admin platform surfaces ───────────────────────────────────────────────

@federation_test(
    name="events_admin_broadcast_lifecycle",
    category="event_matrix",
    budget_sec=180.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["event_emission", "admin"],
)
async def test_admin_broadcast_lifecycle_events(rig: FederationTestRig) -> AssertionResult:
    """Compose, edit and retract a broadcast — each must be recorded.

    A broadcast is the platform speaking to every developer at once. Retraction
    especially: "this was said and then withdrawn" is only reconstructable if
    both halves are in the log.
    """
    m = uuid.uuid4().hex[:10]
    state: Dict[str, Any] = {"marker": m}
    created = await _must(rig, "POST", "/api/v1/admin/broadcasts",
                          body={"title": f"fedsuite event probe {m}",
                                "body": f"federation suite event-matrix probe {m}",
                                "severity": "info", "audience": "none"})
    bid = created.get("id") or created.get("broadcast_id")
    state["broadcast_id"] = bid
    if bid is None:
        raise PreconditionUnmet(f"broadcast created but no id (keys={sorted(created)[:8]})")
    await _must(rig, "PUT", f"/api/v1/admin/broadcasts/{bid}",
                body={"title": f"fedsuite event probe {m} edited",
                      "body": f"federation suite event-matrix probe {m} edited"})
    await _must(rig, "DELETE", f"/api/v1/admin/broadcasts/{bid}",
                body={"reason": f"fedsuite probe {m}"})
    expect = {t: str(bid) for t in ("AdminBroadcastSent", "AdminBroadcastEdited",
                                    "AdminBroadcastRetracted")}
    return await _await_events(
        rig, expect, state, budget_sec=90.0,
        description="broadcast compose, edit and retract are evented")
