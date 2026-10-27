"""A cross-registry grant follows its issuer's CURRENT standing at home, and the delegate's owner hears it (§TWOAGENT G4
+ G3, V0431; TESTPLAN FB1 + FB3).

Before V0431 a cross-registry delegation outlived its issuer's clamp: suspending the issuer at home changed nothing at
the delegate's home, where the grant kept conveying until a revoke reached it (only a revoke cut it). G4 made the
delegate's home ask the issuer's home at use (`/federation/ironkey/issuer-authority`, a 60 s cache, fail closed). G3
made the delegate's OWNER hear the grant arrive and leave (`delegation.received` / `delegation.revoked`), which only a
local delegation used to do.

The flow issues a real delegation from an agent on sandbox-A to one on sandbox-B, then: the delegate's act-token
conveys it; the issuer is suspended AT HOME and within the cache window the delegate's act-token is refused naming the
issuer's state; reinstated, it conveys again; revoked, it is refused ("No live delegation grant"). The delegate's owner
hears `delegation.received` (cross_registry) and `delegation.revoked` for this credential; the issuer's owner hears
neither. Owners are heard through the dispatcher's own record on hooks whose host is `.invalid`.

⚠ Writes: two throwaway agents (`fedsuite-g4-*`, not bonded: a delegation is not a bond site, so no money moves), a
suspension of the throwaway issuer that is ALWAYS reinstated (in `finally` too), two hooks, one credential (revoked).
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
)
from agentvault_registry.api_tests.federation_suite.tests.test_ironkey_authority_clamp import (
    _call, _rest, _detail, _catalog, _set_roles, _pick_role_and_permission,
)
from agentvault_registry.api_tests.federation_suite.tests.test_ironkey_cross_registry_delegation import (
    _registry_name, _peer_target,
)

_TAG = "fedsuite-g4"
_CACHE_SEC = 60.0          # the issuer-authority cache at the delegate's home
_HEAR_SEC = 45.0
_REASON = "federation suite FB1: suspend a THROWAWAY issuer to prove the clamp crosses frames (reinstated at once)"


async def _agent(rig, label: str, tag: str, made: List[Tuple[str, str]]) -> Dict[str, str]:
    name = f"{_TAG}-{tag}-{uuid.uuid4().hex[:8]}"
    r, refused = await _call(rig, label, "createAgent", {"name": name, "description": "federation suite G4 probe"})
    if refused or not isinstance(r, dict) or r.get("error"):
        raise PreconditionUnmet(f"createAgent refused on {label}: {refused or r.get('error')}")
    creds = r.get("credentials") or {}
    cid, sec = r.get("client_id") or creds.get("client_id"), r.get("client_secret") or creds.get("client_secret")
    did = r.get("did") or r.get("agent_did")
    throwaways.made(label, did)  # V0641: retired once its test's verdict is in (throwaways)
    if not (cid and sec and did):
        raise PreconditionUnmet(f"createAgent on {label}: no credential triple")
    made.append((label, did))
    t, tref = await _call(rig, label, "getAgentToken", {"client_id": cid, "client_secret": sec})
    jwt = (t.get("access_token") or t.get("agent_jwt")) if isinstance(t, dict) else None
    if tref or not jwt:
        raise PreconditionUnmet(f"getAgentToken refused on {label}: {tref}")
    return {"did": did, "jwt": jwt}


async def _hook(rig, label: str, hooks: List[Tuple[str, str]]) -> str:
    r, refused = await _call(rig, label, "createWebhook", {
        "url": f"https://{_TAG}-{uuid.uuid4().hex[:10]}.invalid/hook",
        "events": ["delegation.received", "delegation.revoked"],
        "description": "federation suite G4: a host that never resolves; the flow reads the dispatcher's record"})
    if refused or not isinstance(r, dict) or not r.get("id"):
        raise PreconditionUnmet(f"createWebhook refused on {label}: {refused or str(r)[:160]}")
    hooks.append((label, r["id"]))
    return r["id"]


async def _told(rig, label: str, hook_id: str, event: str, cred: str) -> Optional[List[Dict[str, Any]]]:
    """Deliveries of `event` naming this credential, or None when the record is unreadable (never silence)."""
    r, refused = await _call(rig, label, "getWebhookDeliveries", {"webhook_id": hook_id, "limit": 100})
    if refused or not isinstance(r, dict) or not isinstance(r.get("deliveries"), list):
        return None
    out = []
    for d in r["deliveries"]:
        if not isinstance(d, dict) or d.get("event_type") != event:
            continue
        p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
        data = p.get("data") if isinstance(p.get("data"), dict) else p
        if str(data.get("credential_id") or "") == cred:
            out.append(data)
    return out


async def _until(fn, budget: float, every: float = 5.0):
    end = time.monotonic() + budget
    while True:
        last = await fn()
        if last or time.monotonic() >= end:
            return last
        await asyncio.sleep(every)


@federation_test(
    name="ironkey_xreg_grant_follows_its_issuer_home",
    category="ironkey_xreg",
    budget_sec=420.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-B", "sandbox-A-admin", "sandbox-B-admin"],
    tags=["ironkey", "xreg", "g4", "g3", "cross_frame", "webhooks"],
)
async def test_xreg_grant_follows_issuer(rig: FederationTestRig) -> AssertionResult:
    """Suspend the issuer at home: the delegate's grant stops conveying within the cache; reinstate, revoke, heard."""
    t0 = time.monotonic()
    planned = ["issued", "conveys_while_the_issuer_stands", "delegates_owner_hears_the_grant",
               "refused_while_the_issuer_is_suspended_at_home", "conveys_again_after_reinstate",
               "refused_after_the_issuers_revoke", "delegates_owner_hears_the_revoke",
               "issuers_owner_hears_neither", "the_flow_removed_what_it_made"]
    legs: Dict[str, bool] = {}
    ev: Dict[str, Any] = {}
    made: List[Tuple[str, str]] = []
    hooks: List[Tuple[str, str]] = []
    st: Dict[str, Any] = {"suspended": False, "issuer": None}

    async def body() -> None:
        b_name = await _registry_name(rig, "sandbox-B-admin")
        target = await _peer_target(rig, "sandbox-A", b_name) if b_name else None
        if not target:
            raise PreconditionUnmet(f"frame B ({b_name!r}) is not an ACTIVE peer of frame A")
        role, perm = _pick_role_and_permission(await _catalog(rig))
        issuer = await _agent(rig, "sandbox-A", "i", made)
        st["issuer"] = issuer
        delegate = await _agent(rig, "sandbox-B", "d", made)
        hook_b = await _hook(rig, "sandbox-B", hooks)
        hook_a = await _hook(rig, "sandbox-A", hooks)
        code, authz = await _set_roles(rig, issuer["did"], [role], delegate=True)
        if code != 200 or perm not in set((authz or {}).get("effective_permissions") or []):
            raise PreconditionUnmet(f"the issuer could not be given {perm!r}: HTTP {code}")

        code, issued = await _rest(rig, "POST", "/api/v1/agents/delegate-cross-registry",
                                   body={"delegate_did": delegate["did"], "delegate_registry_url": target,
                                         "permissions": [perm], "ttl_hours": 1}, jwt=issuer["jwt"])
        cred = issued.get("credential_id") if isinstance(issued, dict) else None
        legs["issued"] = code == 200 and bool(cred) and bool((issued or {}).get("ok"))
        ev["issued"] = {"status": code, "detail": None if legs["issued"] else _detail(issued)[:200]}
        if not legs["issued"]:
            return

        async def act() -> Tuple[int, Any]:
            return await _rest(rig, "POST", "/api/v1/agents/act-token", label="sandbox-B-admin",
                               body={"act_as": f"agent:{issuer['did']}"}, jwt=delegate["jwt"])

        def conveys(res: Tuple[int, Any]) -> bool:
            c, b = res
            return c == 200 and isinstance(b, dict) and perm in set(b.get("effective_permissions") or [])

        def refused(res: Tuple[int, Any], words: str) -> bool:
            c, b = res
            return c == 403 and words.lower() in _detail(b).lower()

        res = await act()
        legs["conveys_while_the_issuer_stands"] = conveys(res)
        ev["conveys_while_the_issuer_stands"] = {"status": res[0]}
        got = await _until(lambda: _told(rig, "sandbox-B", hook_b, "delegation.received", cred), _HEAR_SEC)
        legs["delegates_owner_hears_the_grant"] = bool(got) and all(
            str(d.get("scope") or "") == "cross_registry" for d in got)
        ev["delegates_owner_hears_the_grant"] = {"deliveries": got}

        # The clamp: the issuer suspended at ITS home.
        code, _ = await _rest(rig, "POST", f"/api/v1/admin/enforcement/agents/{issuer['did']}/suspend",
                              body={"reason": _REASON})
        st["suspended"] = code == 200
        if not st["suspended"]:
            raise PreconditionUnmet(f"the admin could not suspend the throwaway issuer on sandbox-A: HTTP {code}")
        t_s = time.monotonic()
        last: Dict[str, Any] = {}

        async def clamped():
            r = await act()
            last["res"] = (r[0], _detail(r[1])[:160])
            return refused(r, "not active")
        ok = await _until(clamped, _CACHE_SEC + 60.0)
        legs["refused_while_the_issuer_is_suspended_at_home"] = bool(ok)
        ev["refused_while_the_issuer_is_suspended_at_home"] = {"after_s": round(time.monotonic() - t_s, 1),
                                                               "last": last.get("res")}

        code, _ = await _rest(rig, "POST", f"/api/v1/admin/enforcement/agents/{issuer['did']}/reinstate",
                              body={"reason": _REASON})
        st["suspended"] = code != 200
        t_r = time.monotonic()
        ok = await _until(lambda: _conveys_async(act, conveys), _CACHE_SEC + 60.0)
        legs["conveys_again_after_reinstate"] = bool(ok) and not st["suspended"]
        ev["conveys_again_after_reinstate"] = {"after_s": round(time.monotonic() - t_r, 1), "reinstate_status": code}

        code, _ = await _rest(rig, "DELETE",
                              f"/api/v1/agents/delegate-cross-registry/{cred}?delegate_registry_url={quote(target)}",
                              jwt=issuer["jwt"])
        res = await _until(lambda: _refused_async(act, refused, "No live delegation grant"), 30.0)
        legs["refused_after_the_issuers_revoke"] = bool(res)
        ev["refused_after_the_issuers_revoke"] = {"revoke_status": code}
        got = await _until(lambda: _told(rig, "sandbox-B", hook_b, "delegation.revoked", cred), _HEAR_SEC)
        legs["delegates_owner_hears_the_revoke"] = bool(got)
        ev["delegates_owner_hears_the_revoke"] = {"deliveries": got}

        rec = await _told(rig, "sandbox-A", hook_a, "delegation.received", cred)
        rev = await _told(rig, "sandbox-A", hook_a, "delegation.revoked", cred)
        legs["issuers_owner_hears_neither"] = rec == [] and rev == []
        ev["issuers_owner_hears_neither"] = {"received": rec, "revoked": rev,
                                             "note": "None = the record was unreadable, never silence"}
    ran = False
    try:
        await body()
        ran = True
    finally:
        if st["suspended"] and st["issuer"]:
            await _rest(rig, "POST", f"/api/v1/admin/enforcement/agents/{st['issuer']['did']}/reinstate",
                        body={"reason": _REASON})
        left: List[str] = []
        for label, hook_id in hooks:
            _, r = await _call(rig, label, "deleteWebhook", {"webhook_id": hook_id})
            if r:
                left.append(f"webhook {hook_id} on {label}: {r[:100]}")
        for label, did in made:
            _, r = await throwaways.retire(rig, label, did)      # V0641: what it holds goes back first
            if r:
                left.append(f"agent {did} on {label}: {r[:100]}")
        if ran:
            legs["the_flow_removed_what_it_made"] = not left
            ev["the_flow_removed_what_it_made"] = {"left": left}
    return _result(planned, legs, ev, t0)


async def _conveys_async(act, conveys) -> bool:
    return conveys(await act())


async def _refused_async(act, refused, words: str) -> bool:
    return refused(await act(), words)


def _result(planned: List[str], legs: Dict[str, bool], ev: Dict[str, Any], t0: float) -> AssertionResult:
    missing = [n for n in planned if n not in legs]
    failed = [n for n, ok in legs.items() if not ok]
    passed = not missing and not failed
    return AssertionResult(
        passed=passed,
        description="a cross-registry grant is clamped to its issuer's standing at home, and its delegate's owner hears it",
        budget_sec=0.0, elapsed_sec=time.monotonic() - t0, polling_attempts=1,
        last_state={"legs": legs, "not_run": missing, "evidence": ev},
        failure_detail=None if passed else json.dumps({"failed": failed, "not_run": missing,
                                                       "evidence": {n: ev.get(n) for n in failed}},
                                                      default=str)[:700])
