"""IRONKEY (L1-L4) — the authority system, measured instead of assumed (§FEDIRONKEY).

IRONKEY is at `enforce` on all 16 core registries and decides what every agent
in the federation may do. Before this file the federation suite had **zero**
tests for it: 139 test files and not one asked whether an agent's authority is
actually clamped. The one property everything else leans on was documented in
prose and verified nowhere.

PART 14 states the clamp:

    effective = own_rbac ∪ (delegated ∩ dev_authority_now ∩ mandate.scope)
                ∩ att_ caveats ∩ mandate.limits          # re-derived EVERY request

and the confused-deputy property that falls out of it: **clamping the ISSUER
instantly empties every token it issued.** `resolve_capability` calls that
intersection "the confused-deputy killer" in its own docstring
(`agent_delegation.py:155`). This file drives it end to end.

THE OBSERVATION POINT. IRONKEY has no MCP tools — `theprotocol_*` wraps none of
`agent_authz_api.py` or `agent_delegation_api.py`. The rig reaches it through
`adminRequest`, whose `developer_jwt` parameter is used verbatim as the Bearer
(`tools_admin.py:167`), so passing an AGENT jwt reaches agent-tier routes. The
name is a misnomer; the behaviour is the lever that makes L4 testable here.

`POST /agents/capabilities/consume` with **amount 0** is the probe: it returns
`effective_permissions` = the already-intersected set, debits nothing, and
moves no AVT. It reads the clamp without spending anything to do it.

⚠ Δ-IRRELEVANT BY CONSTRUCTION. Nothing here touches the TEG. Capability
budgets are counters on the token row; no `TokensTransferred` is emitted and no
balance moves. The supply invariant cannot be disturbed by this file.

⚠ Writes: creates throwaway agents tagged `fedsuite-ironkey-*` per run and
issues short-TTL (1h) capability tokens to them. Agent deletion is a SOFT
delete, so the residue is bounded and identifiable rather than swept. What an
agent holds goes back to its frame's treasury before the delete (`_cleanup`,
V0639): the soft delete keeps a balance, and the suite's money tests fund the
agents this helper makes.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
    ensure_bonded,
)

_TAG = "fedsuite-ironkey"
logger = logging.getLogger(__name__)


# ─── plumbing ──────────────────────────────────────────────────────────────

def _soft(r: Any) -> Optional[str]:
    if isinstance(r, dict) and set(r.keys()) == {"_text"} and isinstance(r["_text"], str):
        return r["_text"]
    if isinstance(r, str):
        return r
    return None


async def _call(rig, label: str, tool: str, args: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    """MCP call → (result, refusal). `refusal` non-None means the call did not land."""
    try:
        r = await rig.mcp(label).call(tool, args, timeout=60)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    if isinstance(r, dict) and isinstance(r.get("status_code"), int) and r["status_code"] >= 400:
        return r, f"wrapped HTTP {r['status_code']}: {json.dumps(r.get('response'))[:180]}"
    return r, _soft(r)


async def _rest(rig, method: str, endpoint: str, *, label: str = "sandbox-A-admin",
                body: Optional[Dict[str, Any]] = None,
                jwt: Optional[str] = None,
                params: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
    """One REST call through adminRequest → (status_code, unwrapped body).

    `jwt` overrides the Bearer, which is how an AGENT-tier route is reached.
    `params` are query parameters (adminRequest's own `params`).
    Returns the status separately so a test can assert on a REFUSAL as easily
    as on a success — a 403 is the subject here at least as often as a 200.
    """
    args: Dict[str, Any] = {"method": method, "endpoint": endpoint}
    if body is not None:
        args["body"] = body
    if params:
        args["params"] = params
    if jwt:
        args["developer_jwt"] = jwt
    try:
        r = await rig.mcp(label).call("adminRequest", args, timeout=60)
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"
    if not isinstance(r, dict):
        return -1, r
    code = r.get("status_code")
    return (code if isinstance(code, int) else -1), r.get("response")


def _detail(payload: Any) -> str:
    if isinstance(payload, dict):
        d = payload.get("detail")
        if isinstance(d, str):
            return d
        return json.dumps(payload)[:200]
    return str(payload)[:200]


async def _new_agent(rig, tag: str, label: str = "sandbox-A") -> Dict[str, str]:
    """A throwaway agent with its own JWT, on `label`'s frame.

    PreconditionUnmet if the tier cannot make one — an absent fixture, not a
    defect in the subject under test. The `label` parameter is what lets the
    cross-registry tests put the issuer on one frame and the delegate on the
    other, which is the only arrangement in which that rail means anything.
    """
    r, refused = await _call(rig, label, "createAgent", {
        "name": f"{_TAG}-{tag}-{uuid.uuid4().hex[:8]}",
        "description": "federation suite IRONKEY authority probe",
    })
    if refused or not isinstance(r, dict):
        raise PreconditionUnmet(f"createAgent refused for {tag}: {refused}")
    if r.get("error"):
        raise PreconditionUnmet(f"createAgent error for {tag}: {r['error']}")
    cid = r.get("client_id") or (r.get("credentials") or {}).get("client_id")
    sec = r.get("client_secret") or (r.get("credentials") or {}).get("client_secret")
    did = r.get("did") or r.get("agent_did") or (r.get("agent") or {}).get("did")
    throwaways.made(label, did)          # V0641: retired once the verdict is in, unless a test retires it first
    if not (cid and sec and did):
        raise PreconditionUnmet(f"createAgent for {tag}: no credential triple (keys={sorted(r)[:8]})")
    t, tref = await _call(rig, label, "getAgentToken",
                          {"client_id": cid, "client_secret": sec})
    if tref or not isinstance(t, dict):
        raise PreconditionUnmet(f"getAgentToken refused for {tag}: {tref}")
    jwt = t.get("access_token") or t.get("agent_jwt")
    if not jwt:
        raise PreconditionUnmet(f"no agent JWT for {tag}")
    # §REPBOND: creation does NOT bond, so on an enforcing tier this fixture
    # is born refused at discovery/listing/pricing/guild/contract/a2a-payee.
    await ensure_bonded(rig, label, did)
    return {"did": did, "jwt": jwt}


async def _catalog(rig, label: str = "sandbox-A-admin") -> Dict[str, Any]:
    code, body = await _rest(rig, "GET", "/api/v1/agents/authz/catalog", label=label)
    if code != 200 or not isinstance(body, dict):
        raise PreconditionUnmet(f"authz catalog unavailable on {label}: HTTP {code} {_detail(body)}")
    return body


def _pick_role_and_permission(cat: Dict[str, Any]) -> Tuple[str, str]:
    """A (role, permission) pair where the permission is NOT a base permission.

    Derived from the served catalog rather than hardcoded, because birth roles
    and role→permission maps differ per node (measured, §MONEY-M1 R38): a
    literal here would test the map I remember instead of the one running.
    The permission must be outside `base_permissions` or clamping the issuer
    would not remove it and the test would pass without proving anything.
    """
    base = set(cat.get("base_permissions") or [])
    roles: Dict[str, List[str]] = cat.get("roles") or {}
    assignable = [r for r in (cat.get("assignable_roles") or []) if r in roles]
    for role in assignable or sorted(roles):
        if role == "legacy-full":       # not self-assignable; skip
            continue
        extra = sorted(set(roles.get(role) or []) - base)
        if extra:
            return role, extra[0]
    raise PreconditionUnmet(
        f"no assignable role grants a non-base permission "
        f"(roles={sorted(roles)[:8]}, base={sorted(base)[:8]})")


async def _effective(rig, did: str) -> List[str]:
    code, body = await _rest(rig, "GET", f"/api/v1/agents/{did}/authz")
    if code != 200 or not isinstance(body, dict):
        return []
    # The field is `effective_permissions`. `effective` reads as [] and prints
    # the opposite finding — the §ORGLIFE trap, one router over.
    return list(body.get("effective_permissions") or [])


async def _set_roles(rig, did: str, roles: List[str],
                     delegate: Optional[bool] = None) -> Tuple[int, Any]:
    body: Dict[str, Any] = {"roles": roles}
    if delegate is not None:
        body["delegate_enabled"] = delegate
    return await _rest(rig, "PUT", f"/api/v1/agents/{did}/authz", body=body)


async def _issue_root(rig, issuer_did: str, holder_did: str, perms: List[str],
                      *, budget: float = 100.0, ttl: int = 3600) -> Tuple[int, Any]:
    return await _rest(
        rig, "POST", f"/api/v1/agents/{issuer_did}/capabilities/issue-as-owner",
        body={"holder_agent_did": holder_did,
              "caveats": {"permissions": perms},
              "budget_total": budget, "ttl_seconds": ttl})


async def _consume(rig, token: str, holder_jwt: str, amount: float = 0.0) -> Tuple[int, Any]:
    """Read a token's clamped authority. amount=0 debits nothing."""
    return await _rest(rig, "POST", "/api/v1/agents/capabilities/consume",
                       body={"token": token, "amount": amount}, jwt=holder_jwt)


async def _return_balance(rig, did: str, label: str) -> Optional[str]:
    """What `did` holds goes back to its frame's treasury before the delete: the suite's one rule, in throwaways
    (V0641; V0639 wrote it here). Returns None when nothing is left behind, else what the cleanup says."""
    return await throwaways.return_balance(rig, did, label)


async def _cleanup(rig, dids: List[str], label: str = "sandbox-A") -> None:
    # §TWOAGENT G1 (2026-09-23): the tool's argument is `agent_did`. This passed `did`, the tool refused every call, and
    # the refusal was never read: 3,506 agents on sandbox-A and 543 on sandbox-B (2026-09-04 → 09-23), none deleted,
    # while the module docstring called the residue bounded. Best-effort still, but a refusal is now said out loud.
    # V0639 (agentvault2-aa, 2026-10-24): the balance goes back first. The delete is a soft delete that keeps what the
    # agent holds: on sbx-alpha 741 deleted fedsuite-ironkey agents held 151,339 (agentvault2-66's census) and 1,071
    # never deleted 167,872 (the money tests fund the agents this helper makes). Never a finding: a balance left behind
    # is said, like a refused delete. V0641: what this retires, the decorator's close leaves alone.
    for did in dids:
        throwaways.retired(did)
        try:
            left = await _return_balance(rig, did, label)
        except Exception as e:                                         # noqa: BLE001 — cleanup is never a finding
            left = f"its balance was not returned ({type(e).__name__})"
        if left:
            logger.warning("[fedsuite-ironkey] cleanup left a balance behind on %s: %s: %s", label, did, left)
        _, refused = await _call(rig, label, "deleteMyAgentByDev", {"agent_did": did})
        if refused:
            logger.warning("[fedsuite-ironkey] cleanup could not delete %s on %s: %s", did, label, refused[:160])


def _done(passed: bool, description: str, state: Any) -> AssertionResult:
    """A settled verdict. These tests are deterministic — there is nothing to
    wait for, so they must not pretend to poll: a budget loop around an already
    known answer only buys a slower way to report it."""
    return AssertionResult(
        passed=passed, description=description, budget_sec=0.0,
        elapsed_sec=0.0, polling_attempts=1, last_state=state,
        failure_detail=None if passed else json.dumps(state)[:400],
    )


# ─── L1/L2 — roles and the served catalog ──────────────────────────────────

@federation_test(
    name="ironkey_catalog_agrees_across_mainframes",
    category="ironkey_authz",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["ironkey", "rbac", "cross_frame"],
)
async def test_catalog_agrees_across_mainframes(rig: FederationTestRig) -> AssertionResult:
    """The role→permission map must be the same on both frames.

    A divergence is not cosmetic: the same agent card federated to two frames
    would carry different authority depending on which frame answered, and
    every cross-frame delegation would be clamped against a different ceiling
    than the issuer believed. This is the federation-shaped half of L1.
    """
    a = await _catalog(rig, "sandbox-A-admin")
    b = await _catalog(rig, "sandbox-B-admin")

    ra: Dict[str, List[str]] = a.get("roles") or {}
    rb: Dict[str, List[str]] = b.get("roles") or {}
    only_a = sorted(set(ra) - set(rb))
    only_b = sorted(set(rb) - set(ra))
    differing = sorted(r for r in (set(ra) & set(rb)) if set(ra[r]) != set(rb[r]))
    base_differs = set(a.get("base_permissions") or []) != set(b.get("base_permissions") or [])
    perms_differ = set(a.get("all_permissions") or []) != set(b.get("all_permissions") or [])

    agreed = not (only_a or only_b or differing or base_differs or perms_differ)
    return _done(agreed, "IRONKEY role→permission catalog identical on both mainframes", {
        "roles_only_on_A": only_a,
        "roles_only_on_B": only_b,
        "roles_with_different_permissions": differing,
        "base_permissions_differ": base_differs,
        "all_permissions_differ": perms_differ,
        "mode_A": a.get("mode"), "mode_B": b.get("mode"),
    })


@federation_test(
    name="ironkey_newborn_agent_holds_base_permissions",
    category="ironkey_authz",
    budget_sec=60.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["ironkey", "rbac"],
)
async def test_newborn_agent_holds_base_permissions(rig: FederationTestRig) -> AssertionResult:
    """A fresh agent's effective set must contain every base permission.

    PART 14's prerequisite note is the reason this is worth a row: mig 0107's
    `legacy-full` backfill is NOT self-healing, and an agent that slips through
    uncovered under `enforce` holds only `BASE_PERMISSIONS` and can do nothing
    economic. Asserting the floor exists is how that failure announces itself
    on a fresh frame instead of being discovered by an agent that cannot pay.
    """
    cat = await _catalog(rig)
    base = set(cat.get("base_permissions") or [])
    if not base:
        raise PreconditionUnmet("catalog served no base_permissions")
    agent = await _new_agent(rig, "newborn")
    try:
        eff = set(await _effective(rig, agent["did"]))
        missing = sorted(base - eff)
        return _done(not missing, "newborn agent holds every base permission", {
            "did": agent["did"], "mode": cat.get("mode"),
            "base_permissions": sorted(base),
            "effective_permissions": sorted(eff)[:40],
            "missing_base_permissions": missing,
        })
    finally:
        await _cleanup(rig, [agent["did"]])


# ─── L4 — the confused-deputy clamp ────────────────────────────────────────

@federation_test(
    name="ironkey_capability_clamped_to_issuer_current_authority",
    category="ironkey_delegation",
    budget_sec=120.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["ironkey", "l4", "confused_deputy"],
)
async def test_capability_clamped_to_issuer_current_authority(
        rig: FederationTestRig) -> AssertionResult:
    """Clamping the ISSUER must empty a token it already issued.

    The whole L4 design rests on this one sentence, and it is the difference
    between a capability token and a bearer credential that outlives the
    authority behind it. If the intersection were snapshotted at issue time,
    revoking a compromised issuer would leave every token it minted live —
    which is precisely the confused-deputy attack the docstring names.

    Measured, not inferred: consume BEFORE the clamp (permission present),
    clamp the issuer's roles to nothing, consume AFTER (permission gone). Both
    reads are amount=0, so the token's budget is untouched and no value moves.
    """
    cat = await _catalog(rig)
    # ⚠ Deliberately NOT gated on AGENT_RBAC_MODE. The first version of this test
    # skipped whenever the mode was not `enforce` — and skipped on every sandbox
    # frame, because all four come up with IRONKEY unset. That was wrong: the
    # clamp is mode-INDEPENDENT by construction. `resolve_capability` calls
    # `issuer_effective`, which calls `resolve_agent_permissions`, and none of
    # the three reads the mode (`agent_authz.py:192`, `agent_delegation.py:98`).
    # The mode gates the GATES, not the resolution — so refusing to measure here
    # declined to test something that was fully testable.
    role, perm = _pick_role_and_permission(cat)

    issuer = await _new_agent(rig, "issuer")
    holder = await _new_agent(rig, "holder")
    state: Dict[str, Any] = {"role": role, "permission": perm,
                             "rbac_mode": cat.get("mode"),
                             "issuer": issuer["did"], "holder": holder["did"]}
    try:
        code, body = await _set_roles(rig, issuer["did"], [role], delegate=True)
        if code != 200:
            raise PreconditionUnmet(f"could not grant role {role!r}: HTTP {code} {_detail(body)}")
        granted = set((body or {}).get("effective_permissions") or [])
        state["issuer_effective_before"] = sorted(granted)[:40]
        if perm not in granted:
            # The served catalog and the resolver disagree — a real defect, and
            # one this test is entitled to report rather than skip past.
            return _done(False, "issuer holds the permission the catalog says its role grants", {
                **state, "why": f"role {role!r} did not confer {perm!r}"})

        code, body = await _issue_root(rig, issuer["did"], holder["did"], [perm])
        if code != 200 or not isinstance(body, dict) or not body.get("token"):
            raise PreconditionUnmet(f"issue-as-owner failed: HTTP {code} {_detail(body)}")
        token = body["token"]
        state["token_id"] = body.get("id")

        code, before = await _consume(rig, token, holder["jwt"])
        if code != 200 or not isinstance(before, dict):
            raise PreconditionUnmet(f"consume(before) failed: HTTP {code} {_detail(before)}")
        eff_before = set(before.get("effective_permissions") or [])
        state["token_effective_before"] = sorted(eff_before)

        # ── the clamp: strip the issuer's roles ──
        code, body = await _set_roles(rig, issuer["did"], [])
        if code != 200:
            raise PreconditionUnmet(f"clamp failed: HTTP {code} {_detail(body)}")
        state["issuer_effective_after"] = sorted((body or {}).get("effective_permissions") or [])[:40]

        code, after = await _consume(rig, token, holder["jwt"])
        # A clamped issuer may legitimately leave the token resolvable with an
        # EMPTY permission set (200) — what must not survive is the permission.
        if code == 200 and isinstance(after, dict):
            eff_after = set(after.get("effective_permissions") or [])
            state["token_effective_after"] = sorted(eff_after)
            state["consume_after_status"] = 200
            passed = perm in eff_before and perm not in eff_after
        elif code == 403:
            # Refusing the whole token is a stricter answer to the same question.
            state["consume_after_status"] = 403
            state["consume_after_detail"] = _detail(after)
            passed = perm in eff_before
        else:
            state["consume_after_status"] = code
            state["consume_after_detail"] = _detail(after)
            passed = False

        return _done(passed,
                     "clamping the issuer removes the permission from a token it issued",
                     state)
    finally:
        await _cleanup(rig, [issuer["did"], holder["did"]])


@federation_test(
    name="ironkey_attenuated_child_cannot_exceed_parent",
    category="ironkey_delegation",
    budget_sec=120.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["ironkey", "l4", "attenuation"],
)
async def test_attenuated_child_cannot_exceed_parent(rig: FederationTestRig) -> AssertionResult:
    """A child token may only ever be weaker than its parent.

    Both directions are driven, because only one of them can fail loudly: a
    widening attempt must be REFUSED (422), and a narrowing one must SUCCEED.
    Asserting only the refusal would pass just as happily against an endpoint
    that refuses everything.
    """
    cat = await _catalog(rig)
    role, perm = _pick_role_and_permission(cat)
    base = sorted(set(cat.get("base_permissions") or []))
    widen = next((p for p in sorted(cat.get("all_permissions") or [])
                  if p != perm and p not in base), None)
    if widen is None:
        raise PreconditionUnmet("catalog offers no second permission to widen with")

    issuer = await _new_agent(rig, "att-issuer")
    holder = await _new_agent(rig, "att-holder")
    state: Dict[str, Any] = {"parent_permission": perm, "widen_with": widen}
    try:
        code, body = await _set_roles(rig, issuer["did"], [role], delegate=True)
        if code != 200 or perm not in set((body or {}).get("effective_permissions") or []):
            raise PreconditionUnmet(f"issuer could not be given {perm!r}: HTTP {code}")
        code, body = await _issue_root(rig, issuer["did"], holder["did"], [perm])
        if code != 200 or not isinstance(body, dict) or not body.get("id"):
            raise PreconditionUnmet(f"issue-as-owner failed: HTTP {code} {_detail(body)}")
        parent_id = body["id"]
        state["parent_token_id"] = parent_id

        # (a) widening must be refused
        code_w, body_w = await _rest(
            rig, "POST", f"/api/v1/agents/capabilities/{parent_id}/attenuate",
            body={"caveats": {"permissions": [perm, widen]}, "ttl_seconds": 600},
            jwt=holder["jwt"])
        state["widen_status"] = code_w
        state["widen_detail"] = _detail(body_w)
        widen_refused = code_w == 422 and "permissions_exceed_parent" in state["widen_detail"]

        # (b) narrowing must be allowed — the control that keeps (a) meaningful
        code_n, body_n = await _rest(
            rig, "POST", f"/api/v1/agents/capabilities/{parent_id}/attenuate",
            body={"caveats": {"permissions": [perm]}, "ttl_seconds": 600},
            jwt=holder["jwt"])
        state["narrow_status"] = code_n
        narrow_ok = code_n == 200 and isinstance(body_n, dict) and bool(body_n.get("token"))
        if isinstance(body_n, dict):
            state["child_depth"] = body_n.get("depth")
        else:
            state["narrow_detail"] = _detail(body_n)

        return _done(widen_refused and narrow_ok,
                     "attenuation refuses a wider child and accepts a narrower one", state)
    finally:
        await _cleanup(rig, [issuer["did"], holder["did"]])


@federation_test(
    name="ironkey_revoking_parent_kills_child_subtree",
    category="ironkey_delegation",
    budget_sec=120.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["ironkey", "l4", "revocation"],
)
async def test_revoking_parent_kills_child_subtree(rig: FederationTestRig) -> AssertionResult:
    """Revoking a token must kill everything derived from it.

    A revocation that stops at the token it names is not a revocation: the
    holder attenuates first, keeps the child, and carries on. The child is
    proven LIVE before the parent dies, so a child that was never usable
    cannot masquerade as a successful cascade.
    """
    cat = await _catalog(rig)
    role, perm = _pick_role_and_permission(cat)

    issuer = await _new_agent(rig, "rev-issuer")
    holder = await _new_agent(rig, "rev-holder")
    state: Dict[str, Any] = {"permission": perm}
    try:
        code, body = await _set_roles(rig, issuer["did"], [role], delegate=True)
        if code != 200 or perm not in set((body or {}).get("effective_permissions") or []):
            raise PreconditionUnmet(f"issuer could not be given {perm!r}: HTTP {code}")
        code, body = await _issue_root(rig, issuer["did"], holder["did"], [perm])
        if code != 200 or not isinstance(body, dict) or not body.get("id"):
            raise PreconditionUnmet(f"issue-as-owner failed: HTTP {code} {_detail(body)}")
        parent_id, parent_token = body["id"], body["token"]

        code, child = await _rest(
            rig, "POST", f"/api/v1/agents/capabilities/{parent_id}/attenuate",
            body={"caveats": {"permissions": [perm]}, "ttl_seconds": 600},
            jwt=holder["jwt"])
        if code != 200 or not isinstance(child, dict) or not child.get("token"):
            raise PreconditionUnmet(f"attenuate failed: HTTP {code} {_detail(child)}")
        child_token = child["token"]
        state["parent_token_id"] = parent_id
        state["child_token_id"] = child.get("id")

        code_live, live = await _consume(rig, child_token, holder["jwt"])
        state["child_before_revoke_status"] = code_live
        child_was_live = code_live == 200
        if not child_was_live:
            state["child_before_revoke_detail"] = _detail(live)

        code_r, rev = await _rest(rig, "DELETE",
                                  f"/api/v1/agents/capabilities/{parent_id}",
                                  jwt=holder["jwt"])
        state["revoke_status"] = code_r
        if isinstance(rev, dict):
            state["revoke_response"] = {k: rev.get(k) for k in ("ok", "revoked", "count")
                                        if k in rev}

        code_p, pbody = await _consume(rig, parent_token, holder["jwt"])
        code_c, cbody = await _consume(rig, child_token, holder["jwt"])
        state["parent_after_revoke_status"] = code_p
        state["child_after_revoke_status"] = code_c
        state["child_after_revoke_detail"] = _detail(cbody)

        passed = (child_was_live and code_r in (200, 204)
                  and code_p == 403 and code_c == 403)
        return _done(passed, "revoking a parent capability kills its child subtree", state)
    finally:
        await _cleanup(rig, [issuer["did"], holder["did"]])


# ─── L3 — act-tokens ───────────────────────────────────────────────────────

@federation_test(
    name="ironkey_act_token_refused_without_grant",
    category="ironkey_delegation",
    budget_sec=60.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["ironkey", "l3", "negative"],
)
async def test_act_token_refused_without_grant(rig: FederationTestRig) -> AssertionResult:
    """You cannot mint authority to act as a principal that never delegated.

    The negative half of L3. An act-token minted without a grant would be a
    self-service escalation: any agent could name any principal and receive a
    token asserting it acts for them.
    """
    agent = await _new_agent(rig, "acttoken-neg")
    stranger = f"agent:did:theprotocol:{uuid.uuid4()}"
    try:
        code, body = await _rest(rig, "POST", "/api/v1/agents/act-token",
                                 body={"act_as": stranger}, jwt=agent["jwt"])
        detail = _detail(body)
        passed = code == 403 and "delegation grant" in detail.lower()
        return _done(passed, "act-token refused for a principal that granted nothing", {
            "did": agent["did"], "act_as": stranger,
            "status": code, "detail": detail[:200],
        })
    finally:
        await _cleanup(rig, [agent["did"]])


@federation_test(
    name="ironkey_delegation_grant_enables_act_token",
    category="ironkey_delegation",
    budget_sec=90.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["ironkey", "l3"],
)
async def test_delegation_grant_enables_act_token(rig: FederationTestRig) -> AssertionResult:
    """A live L3 grant makes the act-token mintable, and it reports
    `effective_permissions`.

    The field name is the trap this asserts on purpose: reading `effective`
    yields [] and prints the opposite finding (§ORGLIFE). A test that accepts
    either name would hide the day the contract changes.
    """
    me, refused = await _call(rig, "sandbox-A-admin", "adminRequest",
                              {"method": "GET", "endpoint": "/api/v1/developers/me"})
    dev_id = None
    if isinstance(me, dict) and isinstance(me.get("response"), dict):
        dev_id = me["response"].get("id")
    if dev_id is None:
        raise PreconditionUnmet(f"could not read own developer id: {refused}")

    cat = await _catalog(rig)
    base = set(cat.get("base_permissions") or [])
    perm = next((p for p in sorted(cat.get("all_permissions") or []) if p not in base), None)
    if perm is None:
        raise PreconditionUnmet("catalog offers no non-base permission to delegate")

    agent = await _new_agent(rig, "acttoken-pos")
    state: Dict[str, Any] = {"principal": f"dev:{dev_id}", "permission": perm}
    try:
        code, body = await _rest(
            rig, "POST", f"/api/v1/agents/{agent['did']}/delegations",
            body={"principal_type": "dev", "principal_ref": str(dev_id),
                  "permissions": [perm], "ttl_hours": 1})
        state["grant_status"] = code
        if code != 200:
            raise PreconditionUnmet(f"could not create delegation grant: HTTP {code} {_detail(body)}")

        code, tok = await _rest(rig, "POST", "/api/v1/agents/act-token",
                                body={"act_as": f"dev:{dev_id}"}, jwt=agent["jwt"])
        state["act_token_status"] = code
        ok_shape = (code == 200 and isinstance(tok, dict)
                    and "effective_permissions" in tok
                    and isinstance(tok.get("effective_permissions"), list))
        if isinstance(tok, dict):
            state["effective_permissions"] = tok.get("effective_permissions")
            state["has_legacy_effective_key"] = "effective" in tok
            state["keys"] = sorted(tok)[:12]
        else:
            state["detail"] = _detail(tok)
        return _done(ok_shape,
                     "a live delegation grant mints an act-token reporting effective_permissions",
                     state)
    finally:
        await _cleanup(rig, [agent["did"]])


# ─── event emission — the half a 200 cannot prove ──────────────────────────

async def _events_for(rig, aggregate_id: str) -> Optional[List[Dict[str, Any]]]:
    """Every EventStore event on one aggregate, or None if the ES is unreadable.

    None is a THIRD state and must never collapse into "checked and fine" —
    an unreachable EventStore and an unemitted event look identical from here
    unless the difference is kept.

    ⚠ Unwrap `response` WHATEVER its type: `/events/aggregate/{id}` answers
    with a LIST, and a dict-only guard falls through to the wrapper, finds no
    events, and reports a missing emission that is really a missing unwrap
    (that mistake cost §FEDSUITE three separate false alarms).
    """
    r, refused = await _call(rig, "sandbox-A-admin", "adminQueryEventStore",
                             {"path": f"/api/v1/events/aggregate/{aggregate_id}"})
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


def _event_types(events: List[Dict[str, Any]]) -> List[str]:
    return [str(e.get("event_type") or e.get("type") or "") for e in events]


def _saw(events: List[Dict[str, Any]], etype: str,
         match: Optional[Dict[str, Any]] = None) -> bool:
    """An event of this type whose payload carries the expected fields.

    Type alone is too weak: the emission under test writes a specific
    token_id/issuer, and an unrelated event of the same type from another run
    would satisfy a type-only check on a shared aggregate.
    """
    for e in events:
        # EXACT type equality, not a substring. A substring match would accept a
        # differently-named successor event (an `...V2`) as proof the original
        # still fires — the same class as a content gate matching a comment
        # instead of the code it describes.
        if str(e.get("event_type") or e.get("type") or "") != etype:
            continue
        if not match:
            return True
        d = e.get("data") or e.get("payload") or {}
        if not isinstance(d, dict):
            continue
        if all(str(d.get(k)) == str(v) for k, v in match.items()):
            return True
    return False


@federation_test(
    name="ironkey_capability_lifecycle_is_evented",
    category="ironkey_delegation",
    budget_sec=150.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["ironkey", "l4", "event_emission"],
)
async def test_capability_lifecycle_is_evented(rig: FederationTestRig) -> AssertionResult:
    """Issue → consume → attenuate must each land in the EventStore.

    A 200 on a delegation rail proves the row was written; it says nothing
    about whether the ledger saw it. All three emissions sit inside
    `except Exception: logger.debug(...)` blocks (`agent_delegation_api.py`),
    so a broken emitter degrades to a debug line and every functional test in
    this file keeps passing — the §VITALS shape exactly: the failure is real,
    handled, and invisible to anything that only reads status codes.

    Delegation events carry no money, so this cannot move Δ; what it protects
    is the AUDIT of who was granted authority, which is the only durable record
    that an agent was ever allowed to act.

    Emission is background work, so this polls rather than reading once, and
    it holds an explicit could-not-check state for an unreadable EventStore.
    """
    cat = await _catalog(rig)
    role, perm = _pick_role_and_permission(cat)

    issuer = await _new_agent(rig, "ev-issuer")
    holder = await _new_agent(rig, "ev-holder")
    state: Dict[str, Any] = {"permission": perm, "holder": holder["did"]}
    try:
        code, body = await _set_roles(rig, issuer["did"], [role], delegate=True)
        if code != 200 or perm not in set((body or {}).get("effective_permissions") or []):
            raise PreconditionUnmet(f"issuer could not be given {perm!r}: HTTP {code}")

        code, issued = await _issue_root(rig, issuer["did"], holder["did"], [perm])
        if code != 200 or not isinstance(issued, dict) or not issued.get("token"):
            raise PreconditionUnmet(f"issue-as-owner failed: HTTP {code} {_detail(issued)}")
        token_id, token = issued["id"], issued["token"]
        state["token_id"] = token_id

        code, consumed = await _consume(rig, token, holder["jwt"], amount=1.0)
        if code != 200:
            raise PreconditionUnmet(f"consume failed: HTTP {code} {_detail(consumed)}")

        code, child = await _rest(
            rig, "POST", f"/api/v1/agents/capabilities/{token_id}/attenuate",
            body={"caveats": {"permissions": [perm]}, "ttl_seconds": 600},
            jwt=holder["jwt"])
        if code != 200 or not isinstance(child, dict):
            raise PreconditionUnmet(f"attenuate failed: HTTP {code} {_detail(child)}")
        state["child_token_id"] = child.get("id")

        # ── everything above is arrange/act; only the emission is awaited ──
        expected = {
            "AgentCapabilityIssued": {"token_id": token_id},
            "AgentCapabilityConsumed": {"token_id": token_id},
            "AgentCapabilityAttenuated": {"parent_token_id": token_id},
        }

        async def predicate() -> bool:
            events = await _events_for(rig, holder["did"])
            if events is None:
                state["eventstore"] = "unreadable"
                return False
            state["eventstore"] = "readable"
            state["events_on_aggregate"] = len(events)
            state["event_types"] = sorted(set(_event_types(events)))[:15]
            seen = {t: _saw(events, t, m) for t, m in expected.items()}
            state["seen"] = seen
            state["missing"] = sorted(t for t, ok in seen.items() if not ok)
            return all(seen.values())

        result = await rig.assert_within(
            budget_sec=60.0, poll_interval_sec=3.0, predicate=predicate,
            description="issue/consume/attenuate each reach the EventStore",
            capture_state=lambda: state,
        )
        # An unreadable EventStore is not evidence of an unemitted event. Report
        # it as its own outcome rather than as a defect in the emitter.
        if not result.passed and state.get("eventstore") == "unreadable":
            raise PreconditionUnmet(
                "EventStore unreadable from sandbox-A-admin — emission not measured")
        return result
    finally:
        await _cleanup(rig, [issuer["did"], holder["did"]])


@federation_test(
    name="ironkey_act_token_mint_is_evented",
    category="ironkey_delegation",
    budget_sec=150.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["ironkey", "l3", "event_emission"],
)
async def test_act_token_mint_is_evented(rig: FederationTestRig) -> AssertionResult:
    """Minting an act-token must be recorded.

    The act-token mint is the privilege-ASSUMPTION moment — a fresh bearer
    credential asserting one identity may act for another. Of everything
    IRONKEY does, this is the event whose absence would matter most after the
    fact, because it is the only record that the assumption ever happened.
    """
    me, refused = await _call(rig, "sandbox-A-admin", "adminRequest",
                              {"method": "GET", "endpoint": "/api/v1/developers/me"})
    dev_id = None
    if isinstance(me, dict) and isinstance(me.get("response"), dict):
        dev_id = me["response"].get("id")
    if dev_id is None:
        raise PreconditionUnmet(f"could not read own developer id: {refused}")

    cat = await _catalog(rig)
    base = set(cat.get("base_permissions") or [])
    perm = next((p for p in sorted(cat.get("all_permissions") or []) if p not in base), None)
    if perm is None:
        raise PreconditionUnmet("catalog offers no non-base permission to delegate")

    agent = await _new_agent(rig, "ev-act")
    principal = f"dev:{dev_id}"
    state: Dict[str, Any] = {"principal": principal, "did": agent["did"]}
    try:
        code, body = await _rest(
            rig, "POST", f"/api/v1/agents/{agent['did']}/delegations",
            body={"principal_type": "dev", "principal_ref": str(dev_id),
                  "permissions": [perm], "ttl_hours": 1})
        if code != 200:
            raise PreconditionUnmet(f"delegation grant failed: HTTP {code} {_detail(body)}")

        code, tok = await _rest(rig, "POST", "/api/v1/agents/act-token",
                                body={"act_as": principal}, jwt=agent["jwt"])
        if code != 200:
            raise PreconditionUnmet(f"act-token mint failed: HTTP {code} {_detail(tok)}")

        async def predicate() -> bool:
            events = await _events_for(rig, agent["did"])
            if events is None:
                state["eventstore"] = "unreadable"
                return False
            state["eventstore"] = "readable"
            state["events_on_aggregate"] = len(events)
            state["event_types"] = sorted(set(_event_types(events)))[:15]
            return _saw(events, "AgentActTokenMinted")

        result = await rig.assert_within(
            budget_sec=60.0, poll_interval_sec=3.0, predicate=predicate,
            description="act-token mint reaches the EventStore",
            capture_state=lambda: state,
        )
        if not result.passed and state.get("eventstore") == "unreadable":
            raise PreconditionUnmet(
                "EventStore unreadable from sandbox-A-admin — emission not measured")
        return result
    finally:
        await _cleanup(rig, [agent["did"]])


@federation_test(
    name="ironkey_suspended_issuer_empties_its_tokens",
    category="ironkey_delegation",
    budget_sec=120.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["ironkey", "l4", "enforcement", "confused_deputy"],
)
async def test_suspended_issuer_empties_its_tokens(rig: FederationTestRig) -> AssertionResult:
    """Suspending an agent must kill the capability tokens it issued.

    This is the clamp's harder half, and it lives in a different place in the
    code. `resolve_agent_permissions` never reads `agents.status` — a suspended
    agent's ROLE ROWS are all still there, so permission resolution alone would
    happily keep answering with full authority. The status check is asserted
    once, in `issuer_effective` (`agent_delegation.py:110`), at the single point
    where issuer authority is minted into a token's effective set.

    That makes it exactly the kind of guard that is easy to lose in a refactor
    and impossible to notice: suspension would keep working everywhere a human
    looks (the agent cannot log in, cannot transact) while every capability
    token it had already handed out kept spending its authority. An enforcement
    action that does not reach outstanding delegations is not an enforcement
    action.

    The token is proven LIVE first, so a token that never worked cannot pass
    this as a successful suspension. The agent is reinstated afterwards, but
    the verdict is read BEFORE the reinstate — the cleanup must not be able to
    change the answer.
    """
    cat = await _catalog(rig)
    role, perm = _pick_role_and_permission(cat)

    issuer = await _new_agent(rig, "susp-issuer")
    holder = await _new_agent(rig, "susp-holder")
    state: Dict[str, Any] = {"permission": perm, "rbac_mode": cat.get("mode"),
                             "issuer": issuer["did"]}
    try:
        code, body = await _set_roles(rig, issuer["did"], [role], delegate=True)
        if code != 200 or perm not in set((body or {}).get("effective_permissions") or []):
            raise PreconditionUnmet(f"issuer could not be given {perm!r}: HTTP {code}")
        code, issued = await _issue_root(rig, issuer["did"], holder["did"], [perm])
        if code != 200 or not isinstance(issued, dict) or not issued.get("token"):
            raise PreconditionUnmet(f"issue-as-owner failed: HTTP {code} {_detail(issued)}")
        token = issued["token"]
        state["token_id"] = issued.get("id")

        code, before = await _consume(rig, token, holder["jwt"])
        if code != 200 or not isinstance(before, dict):
            raise PreconditionUnmet(f"consume(before) failed: HTTP {code} {_detail(before)}")
        eff_before = set(before.get("effective_permissions") or [])
        state["token_effective_before"] = sorted(eff_before)
        if perm not in eff_before:
            raise PreconditionUnmet(
                f"token did not carry {perm!r} before suspension — nothing to clamp")

        code, susp = await _rest(
            rig, "POST", f"/api/v1/admin/enforcement/agents/{issuer['did']}/suspend",
            body={"reason": "fedsuite IRONKEY clamp probe"})
        state["suspend_status"] = code
        if code not in (200, 202):
            raise PreconditionUnmet(f"could not suspend issuer: HTTP {code} {_detail(susp)}")

        code, after = await _consume(rig, token, holder["jwt"])
        state["consume_after_status"] = code
        if code == 200 and isinstance(after, dict):
            eff_after = set(after.get("effective_permissions") or [])
            state["token_effective_after"] = sorted(eff_after)
            passed = not eff_after            # a suspended issuer contributes NOTHING
        elif code == 403:
            state["consume_after_detail"] = _detail(after)
            passed = True                     # refusing the token outright is stricter
        else:
            state["consume_after_detail"] = _detail(after)
            passed = False

        # Reinstate AFTER the verdict is computed — cleanup must never be able
        # to influence what the test reports.
        code_r, _ = await _rest(
            rig, "POST", f"/api/v1/admin/enforcement/agents/{issuer['did']}/reinstate",
            body={"reason": "fedsuite IRONKEY clamp probe complete"})
        state["reinstate_status"] = code_r

        return _done(passed, "suspending an issuer empties the tokens it issued", state)
    finally:
        await _cleanup(rig, [issuer["did"], holder["did"]])
