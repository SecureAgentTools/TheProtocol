"""IRONKEY cross-registry delegation — the rail PART 14 says must not be rebuilt.

`POST /agents/delegate-cross-registry` lets an agent on one registry hand a
bounded slice of its authority to an agent homed on ANOTHER. It is signed
(`ironkey.delegation.v1`), shipped over federation mTLS, and live `true` on all
16 core registries. It is also, until this file, tested by nothing.

That combination is how a session was once lost: the rail was reported absent,
because "it does not work" and "it is switched off" are indistinguishable from
outside. A test that drives it is the cheapest permanent answer to that
question, and it is worth having precisely because the alternative was rebuilding
a rail that already existed.

WHAT THE RAIL ACTUALLY DOES, and why both ends must be checked:
  * the issuer's home persists **nothing** — it signs, ships, writes an audit
    row and emits `AgentXRegDelegationIssued`, and that is its entire durable
    record (`agent_delegation_api.py`, the §auditfix comment);
  * the DELEGATE's home stores the credential AND opens an
    `agent_delegation_grants` row keyed `agent:<issuer_did>`;
  * the delegate exercises it by minting an act-token at ITS OWN home.
So a test that only asserts the POST returned 200 measures the signature and
the network, and nothing about whether any authority actually crossed.

⚠ Δ-IRRELEVANT: permission bookkeeping and a signature. No money moves at issue
time — PART 14 says so, and nothing here contradicts it.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
)
from agentvault_registry.api_tests.federation_suite.tests.test_ironkey_authority_clamp import (
    _call, _rest, _detail, _new_agent, _cleanup, _catalog, _set_roles,
    _pick_role_and_permission, _events_for, _saw, _event_types, _done,
)

_XREG_DISABLED = "cross-registry delegation is disabled"


async def _registry_name(rig, label: str) -> Optional[str]:
    """A frame's own name, read from its OWN signed card.

    Never inferred from a container name: the container label and the identity
    are different things and have disagreed before (§SLUGCONVERGE cost an hour
    of renames for exactly this).
    """
    # ⚠ the ADMIN label is required: `_rest` goes through `adminRequest`, which
    # lives only on /mcp/admin/rpc. Passing the public label here failed with
    # "could not read frame B's registry name", which reads like a missing card
    # and was really a missing bridge — a refusal blamed on the wrong end.
    code, body = await _rest(rig, "GET", "/.well-known/registry-card.json", label=label)
    if code != 200 or not isinstance(body, dict):
        return None
    ident = body.get("identity") or {}
    return ident.get("registry_name") or body.get("registry_name")


async def _peer_target(rig, from_label: str, want: str) -> Optional[str]:
    """The value `from_label` will accept as a delegate registry.

    `_resolve_peer_url` matches an ACTIVE peer by name OR base_url, so the peer
    NAME is the stable handle — a URL varies with mTLS remapping and port.
    """
    r, refused = await _call(rig, from_label, "listFederationPeers", {})
    if refused:
        return None
    body = r.get("response", r) if isinstance(r, dict) and "response" in r else r
    peers = body if isinstance(body, list) else (
        (body.get("peers") or body.get("items") or []) if isinstance(body, dict) else [])
    for p in peers:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or p.get("registry_name") or "")
        status = str(p.get("status") or "ACTIVE").upper()
        if name.lower() == (want or "").lower() and status == "ACTIVE":
            return name
    return None


async def _xreg_attempt(rig, issuer_did: str, issuer_jwt: str, delegate_did: str,
                        target: str, perms: List[str]) -> tuple:
    return await _rest(
        rig, "POST", "/api/v1/agents/delegate-cross-registry",
        body={"delegate_did": delegate_did, "delegate_registry_url": target,
              "permissions": perms, "ttl_hours": 1},
        jwt=issuer_jwt)


# ─── the gate ──────────────────────────────────────────────────────────────

@federation_test(
    name="ironkey_xreg_delegation_gate_matches_flag",
    category="ironkey_xreg",
    budget_sec=90.0,
    severity="high",
    requires=["sandbox-A", "sandbox-B", "sandbox-A-admin", "sandbox-B-admin"],
    tags=["ironkey", "xreg", "flag"],
)
async def test_xreg_gate_matches_flag(rig: FederationTestRig) -> AssertionResult:
    """The rail must be decisively open or decisively shut, and say which.

    This is the row that answers "does it not work, or is it switched off?"
    without anyone having to read a container's env. Both outcomes are a PASS —
    what fails is an ambiguous one: a 500, a hang, or a refusal that does not
    name its own flag. A disabled rail that refuses clearly is working exactly
    as designed; a disabled rail that refuses obscurely is how the last session
    concluded the feature was missing.
    """
    b_name = await _registry_name(rig, "sandbox-B-admin")
    if not b_name:
        raise PreconditionUnmet("could not read frame B's registry name from its own card")
    target = await _peer_target(rig, "sandbox-A", b_name)
    if not target:
        raise PreconditionUnmet(
            f"frame B ({b_name!r}) is not an ACTIVE peer of frame A — "
            f"the frames are not federated, so there is no rail to gate")

    issuer = await _new_agent(rig, "xreg-gate-i", label="sandbox-A")
    delegate = await _new_agent(rig, "xreg-gate-d", label="sandbox-B")
    cat = await _catalog(rig)
    role, perm = _pick_role_and_permission(cat)
    state: Dict[str, Any] = {"peer_target": target, "permission": perm}
    try:
        await _set_roles(rig, issuer["did"], [role], delegate=True)
        code, body = await _xreg_attempt(rig, issuer["did"], issuer["jwt"],
                                         delegate["did"], target, [perm])
        detail = _detail(body)
        state["status"] = code
        state["detail"] = detail[:220]

        if code == 403 and _XREG_DISABLED in detail.lower():
            state["verdict"] = "rail DISABLED and says so (AGENT_XREG_DELEGATION_ENABLED)"
            passed = True
        elif code == 200 and isinstance(body, dict):
            state["verdict"] = "rail ENABLED"
            state["credential_id"] = body.get("credential_id")
            state["ship_ok"] = body.get("ok")
            passed = True
        else:
            state["verdict"] = "neither cleanly open nor cleanly shut"
            passed = False
        return _done(passed, "cross-registry delegation gate is unambiguous", state)
    finally:
        await _cleanup(rig, [issuer["did"]], label="sandbox-A")
        await _cleanup(rig, [delegate["did"]], label="sandbox-B")


# ─── the rail, end to end ──────────────────────────────────────────────────

@federation_test(
    name="ironkey_xreg_delegation_lands_and_is_exercisable",
    category="ironkey_xreg",
    budget_sec=180.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-B", "sandbox-A-admin", "sandbox-B-admin"],
    tags=["ironkey", "xreg", "cross_frame"],
)
async def test_xreg_delegation_lands_and_is_exercisable(
        rig: FederationTestRig) -> AssertionResult:
    """Authority issued on frame A must be usable by an agent homed on frame B.

    Driven all the way to the only proof that counts: the delegate mints an
    act-token AT ITS OWN HOME naming the remote issuer as principal, and that
    token reports the delegated permission. Everything short of that — a 200
    from the issuer, a signed credential, a stored row — is consistent with a
    delegation that conveys nothing.

    The two ends are deliberately read from different frames, because that is
    the failure this catches: a credential that ships and stores but never
    opens the `agent_delegation_grants` row the act-token path actually reads
    would satisfy every issuer-side assertion and still hand the delegate
    nothing.
    """
    b_name = await _registry_name(rig, "sandbox-B-admin")
    if not b_name:
        raise PreconditionUnmet("could not read frame B's registry name from its own card")
    target = await _peer_target(rig, "sandbox-A", b_name)
    if not target:
        raise PreconditionUnmet(f"frame B ({b_name!r}) is not an ACTIVE peer of frame A")

    cat = await _catalog(rig)
    role, perm = _pick_role_and_permission(cat)
    issuer = await _new_agent(rig, "xreg-i", label="sandbox-A")
    delegate = await _new_agent(rig, "xreg-d", label="sandbox-B")
    state: Dict[str, Any] = {"peer_target": target, "permission": perm,
                             "issuer_frame": "sandbox-A", "delegate_frame": "sandbox-B",
                             "issuer": issuer["did"], "delegate": delegate["did"]}
    try:
        code, body = await _set_roles(rig, issuer["did"], [role], delegate=True)
        if code != 200 or perm not in set((body or {}).get("effective_permissions") or []):
            raise PreconditionUnmet(f"issuer could not be given {perm!r}: HTTP {code}")

        code, issued = await _xreg_attempt(rig, issuer["did"], issuer["jwt"],
                                           delegate["did"], target, [perm])
        detail = _detail(issued)
        state["issue_status"] = code
        if code == 403 and _XREG_DISABLED in detail.lower():
            raise PreconditionUnmet(
                "AGENT_XREG_DELEGATION_ENABLED is off on this frame — the rail is "
                "shut, which the gate test asserts; there is no delegation to follow")
        if code != 200 or not isinstance(issued, dict):
            return _done(False, "cross-registry delegation issued", {
                **state, "issue_detail": detail[:300]})
        state["credential_id"] = issued.get("credential_id")
        state["ship_ok"] = issued.get("ok")
        state["peer_response"] = str(issued.get("peer_response"))[:220]

        # ── the far end: the delegate exercises it at ITS OWN home ──
        principal = f"agent:{issuer['did']}"
        code, tok = await _rest(rig, "POST", "/api/v1/agents/act-token",
                                label="sandbox-B-admin",
                                body={"act_as": principal}, jwt=delegate["jwt"])
        state["act_token_status"] = code
        eff: List[str] = []
        if isinstance(tok, dict):
            eff = list(tok.get("effective_permissions") or [])
            state["delegate_effective"] = sorted(eff)
        else:
            state["act_token_detail"] = _detail(tok)

        passed = bool(issued.get("ok")) and code == 200 and perm in set(eff)
        return _done(
            passed,
            "authority delegated across registries is exercisable at the delegate's home",
            state)
    finally:
        await _cleanup(rig, [issuer["did"]], label="sandbox-A")
        await _cleanup(rig, [delegate["did"]], label="sandbox-B")


@federation_test(
    name="ironkey_xreg_refuses_a_local_delegate",
    category="ironkey_xreg",
    budget_sec=120.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["ironkey", "xreg", "negative"],
)
async def test_xreg_refuses_a_local_delegate(rig: FederationTestRig) -> AssertionResult:
    """The cross-registry rail must refuse a LOCAL delegate and point at L3.

    Not pedantry about a status code: the two rails have different revocation
    stories. A local delegation is a row this registry owns and can revoke; a
    cross-registry credential is shipped elsewhere and revoked best-effort with
    no retry and no alert. Letting a local delegation through the remote rail
    would quietly move it into the weaker of the two.
    """
    cat = await _catalog(rig)
    role, perm = _pick_role_and_permission(cat)
    issuer = await _new_agent(rig, "xreg-loc-i", label="sandbox-A")
    victim = await _new_agent(rig, "xreg-loc-d", label="sandbox-A")
    state: Dict[str, Any] = {"permission": perm}
    try:
        await _set_roles(rig, issuer["did"], [role], delegate=True)
        code, body = await _xreg_attempt(rig, issuer["did"], issuer["jwt"],
                                         victim["did"], "any-peer", [perm])
        detail = _detail(body)
        state["status"] = code
        state["detail"] = detail[:220]
        if code == 403 and _XREG_DISABLED in detail.lower():
            raise PreconditionUnmet(
                "AGENT_XREG_DELEGATION_ENABLED is off — the flag check precedes the "
                "local-delegate check, so this refusal cannot be measured here")
        passed = code == 400 and "local" in detail.lower()
        return _done(passed, "a local delegate is refused by the cross-registry rail", state)
    finally:
        await _cleanup(rig, [issuer["did"], victim["did"]], label="sandbox-A")


@federation_test(
    name="ironkey_xreg_issue_is_evented",
    category="ironkey_xreg",
    budget_sec=180.0,
    severity="high",
    requires=["sandbox-A", "sandbox-B", "sandbox-A-admin"],
    tags=["ironkey", "xreg", "event_emission"],
)
async def test_xreg_issue_is_evented(rig: FederationTestRig) -> AssertionResult:
    """`AgentXRegDelegationIssued` must reach the EventStore.

    This emission matters more than the others in the file. The issuer's home
    persists NOTHING about a cross-registry delegation — no row, no table — so
    the audit entry and this event are the only durable evidence, on the only
    side that can be asked, that the authority was ever granted. Lose the emit
    and a delegation becomes deniable from the side that made it.
    """
    b_name = await _registry_name(rig, "sandbox-B-admin")
    if not b_name:
        raise PreconditionUnmet("could not read frame B's registry name from its own card")
    target = await _peer_target(rig, "sandbox-A", b_name)
    if not target:
        raise PreconditionUnmet(f"frame B ({b_name!r}) is not an ACTIVE peer of frame A")

    cat = await _catalog(rig)
    role, perm = _pick_role_and_permission(cat)
    issuer = await _new_agent(rig, "xreg-ev-i", label="sandbox-A")
    delegate = await _new_agent(rig, "xreg-ev-d", label="sandbox-B")
    state: Dict[str, Any] = {"issuer": issuer["did"], "permission": perm}
    try:
        await _set_roles(rig, issuer["did"], [role], delegate=True)
        code, issued = await _xreg_attempt(rig, issuer["did"], issuer["jwt"],
                                           delegate["did"], target, [perm])
        if code == 403 and _XREG_DISABLED in _detail(issued).lower():
            raise PreconditionUnmet("AGENT_XREG_DELEGATION_ENABLED is off — nothing is issued")
        if code != 200 or not isinstance(issued, dict):
            raise PreconditionUnmet(f"xreg issue failed: HTTP {code} {_detail(issued)}")
        cred = issued.get("credential_id")
        state["credential_id"] = cred

        async def predicate() -> bool:
            events = await _events_for(rig, issuer["did"])
            if events is None:
                state["eventstore"] = "unreadable"
                return False
            state["eventstore"] = "readable"
            state["events_on_aggregate"] = len(events)
            state["event_types"] = sorted(set(_event_types(events)))[:15]
            return _saw(events, "AgentXRegDelegationIssued", {"credential_id": cred})

        result = await rig.assert_within(
            budget_sec=60.0, poll_interval_sec=3.0, predicate=predicate,
            description="AgentXRegDelegationIssued reaches the EventStore",
            capture_state=lambda: state,
        )
        if not result.passed and state.get("eventstore") == "unreadable":
            raise PreconditionUnmet("EventStore unreadable — emission not measured")
        return result
    finally:
        await _cleanup(rig, [issuer["did"]], label="sandbox-A")
        await _cleanup(rig, [delegate["did"]], label="sandbox-B")
