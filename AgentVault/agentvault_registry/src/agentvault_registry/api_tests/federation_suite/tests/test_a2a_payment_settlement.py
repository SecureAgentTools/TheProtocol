"""A2A payment driven to SETTLEMENT — the leg that moves the money.

Eight A2A tests already exist in this suite. Every one of them checks routing,
shape or auth-gating; not one calls `/settle`, which is the only step where
value changes hands. So the rail with the most expensive possible failure —
service rendered, money never moved — had no driven coverage at all.

⚠ THIS IS A REGRESSION GUARD FOR A DEFECT THAT SHIPPED. §BUYSERVICE
(2026-08-24): `/a2a-payment/settle` demanded `a2a.collect` and then refused
anyone but the payer. `a2a.collect` belongs to `service-provider`; a payer is a
`client` holding `a2a.pay`. Under AGENT_RBAC_MODE=enforce those sets are
DISJOINT, so the required pair was reachable only by a legacy-full agent. Every
agent born after IRONKEY went to enforce hit it: the buyer paid, the agent
DELIVERED, and settle answered 403. The gate now names what the caller does.

The guard is in the fixture, not in an assertion: both agents are created with
NOTHING but the frame's default roles, which on this sandbox read
`trader,client,staker` — the exact fleet-default set named in the incident. If
that gate ever regresses to a permission a default agent lacks, this test goes
red on a 403 instead of shipping a rail nobody can use. A test that granted the
provider `service-provider` to "make it work" would have passed straight
through the original bug.

Also pins BOTH halves of the token lifecycle contract, and the distinction
between them is one I got wrong first and measured second:

  * **CONSUMED is not SETTLED.** P25-001 says a repeat verify on a CONSUMED
    token returns valid=True — verify is what consumes it, and a provider that
    retries must not be told the token is dead and re-do paid work for free.
  * **After SETTLE, verify returns valid=False** (measured: 200 with
    `valid: false`). A spent token must not re-verify, or a provider could be
    paid twice for one authorization.

My first version verified once, settled, then verified again and asserted True —
testing the SETTLED transition against the CONSUMED contract. It failed, and the
failure was mine, not the product's. The two verifies that matter are both
BEFORE settlement; the third, after, pins the other end.

⚠ Writes: two agents per run, tagged `fedsuite-a2a-*`, and one settled dust
payment. What an agent holds goes back to its frame's treasury before its delete (throwaways, V0641):
the soft delete keeps a balance, so the suite returns it first.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
    ensure_bonded,
)

_AMOUNT = "2.0"
_FUND = "50.0"


def _soft(r: Any) -> Optional[str]:
    if isinstance(r, dict) and set(r.keys()) == {"_text"} and isinstance(r["_text"], str):
        return r["_text"]
    if isinstance(r, str):
        return r
    return None


async def _call(rig, label: str, tool: str, args: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    try:
        r = await rig.mcp(label).call(tool, args, timeout=60)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    if isinstance(r, dict) and isinstance(r.get("status_code"), int) and r["status_code"] >= 400:
        return r, f"wrapped HTTP {r['status_code']}: {json.dumps(r.get('response'))[:180]}"
    return r, _soft(r)


async def _rest(rig, method: str, endpoint: str, *, label: str = "sandbox-A-admin",
                body: Optional[Dict[str, Any]] = None,
                jwt: Optional[str] = None) -> Tuple[int, Any]:
    """One REST call through adminRequest → (status_code, unwrapped body).

    The status is returned SEPARATELY on purpose: a 403 is the subject of this
    file at least as much as a 200, and a helper that raised on refusal could
    not tell the §BUYSERVICE story at all.
    """
    args: Dict[str, Any] = {"method": method, "endpoint": endpoint}
    if body is not None:
        args["body"] = body
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


def _num(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(str(v))
    except Exception:
        return 0.0


async def _delta(rig) -> Optional[float]:
    r, refused = await _call(rig, "sandbox-A-admin", "adminQueryEventStore",
                             {"path": "/api/v1/projections/supply-audit"})
    if refused or not isinstance(r, dict):
        return None
    body = r.get("response") if isinstance(r.get("response"), dict) else r
    d = body.get("delta")
    return None if d is None else _num(d)


async def _new_agent(rig, tag: str) -> Dict[str, str]:
    """A plain agent with the frame's DEFAULT roles — no grants, deliberately."""
    r, refused = await _call(rig, "sandbox-A", "createAgent", {
        "name": f"fedsuite-a2a-{tag}-{uuid.uuid4().hex[:8]}",
        "description": "federation suite A2A settlement probe",
    })
    if refused or not isinstance(r, dict):
        raise PreconditionUnmet(f"createAgent refused for {tag}: {refused}")
    if r.get("error"):
        raise PreconditionUnmet(f"createAgent error for {tag}: {r['error']}")
    cid = r.get("client_id") or (r.get("credentials") or {}).get("client_id")
    sec = r.get("client_secret") or (r.get("credentials") or {}).get("client_secret")
    did = r.get("did") or r.get("agent_did") or (r.get("agent") or {}).get("did")
    throwaways.made("sandbox-A", did)  # V0641: retired once its test's verdict is in (throwaways)
    if not (cid and sec and did):
        raise PreconditionUnmet(f"createAgent for {tag} returned no credential triple")
    t, tref = await _call(rig, "sandbox-A", "getAgentToken",
                          {"client_id": cid, "client_secret": sec})
    if tref or not isinstance(t, dict):
        raise PreconditionUnmet(f"getAgentToken refused for {tag}: {tref}")
    jwt = t.get("access_token") or t.get("agent_jwt")
    if not jwt:
        raise PreconditionUnmet(f"no agent JWT for {tag}")
    # §REPBOND: creation does NOT bond, so on an enforcing tier this fixture
    # is born refused at discovery/listing/pricing/guild/contract/a2a-payee.
    await ensure_bonded(rig, "sandbox-A", did)
    return {"did": did, "jwt": jwt}


async def _roles_of(rig, did: str) -> Optional[List[str]]:
    st, body = await _rest(rig, "GET", f"/api/v1/agents/{did}/authz")
    if st != 200 or not isinstance(body, dict):
        return None
    roles = body.get("roles")
    return [str(r) for r in roles] if isinstance(roles, list) else None


async def _balance(rig, jwt: str) -> float:
    r, refused = await _call(rig, "sandbox-A", "getMyBalance", {"agent_jwt": jwt})
    if refused or not isinstance(r, dict):
        return 0.0
    for k in ("balance", "liquid_balance", "token_balance", "available"):
        if r.get(k) is not None:
            return _num(r[k])
    return 0.0


async def _authorized_evented(rig, payer_did: str, token_id: str) -> Optional[bool]:
    """Is THIS authorization in the ledger, keyed on the PAYER?

    `A2APaymentAuthorized` is aggregated on `caller_did` — the payer — and names
    the token in `data.token_id`. Querying the target's DID returns zero and
    reads like a dead emitter. None means the ES could not be read.
    """
    if not (payer_did and token_id):
        return None
    r, refused = await _call(rig, "sandbox-A-admin", "adminQueryEventStore",
                             {"path": f"/api/v1/events/aggregate/{payer_did}"})
    if refused:
        return None
    body = r.get("response", r) if isinstance(r, dict) and "response" in r else r
    if isinstance(body, list):
        events = body
    elif isinstance(body, dict):
        events = body.get("events") or body.get("items") or []
    else:
        return None
    for e in events:
        if not isinstance(e, dict):
            continue
        if "A2APaymentAuthorized" not in str(e.get("event_type") or e.get("type") or ""):
            continue
        d = e.get("data") or e.get("payload") or {}
        if isinstance(d, dict) and str(d.get("token_id")) == str(token_id):
            return True
    return False


@federation_test(
    name="a2a_payment_settles_for_a_default_role_agent",
    category="a2a_economic",
    budget_sec=120.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["a2a", "economic", "money", "delta", "rbac", "regression"],
)
async def test_a2a_settlement(rig: FederationTestRig) -> AssertionResult:
    """authorize → verify → settle, with default roles and the money checked."""
    state: Dict[str, Any] = {}

    d0 = await _delta(rig)
    state["delta_before"] = d0
    if d0 is None:
        raise PreconditionUnmet("supply audit unreadable — cannot guard Δ, refusing to move money")
    if abs(d0) > 1e-9:
        raise PreconditionUnmet(f"Δ is already {d0}, not 0 — refusing to run an economic test")

    payer = await _new_agent(rig, "payer")
    provider = await _new_agent(rig, "provider")
    state["payer"], state["provider"] = payer["did"], provider["did"]

    # Record the roles rather than assume them: the whole point is that these are
    # the DEFAULTS, and a frame whose defaults changed should say so in the record.
    state["payer_roles"] = await _roles_of(rig, payer["did"])
    state["provider_roles"] = await _roles_of(rig, provider["did"])

    fst, fbody = await _rest(rig, "POST", "/api/v1/teg/treasury/fund-agent",
                             body={"target_agent_did": payer["did"], "amount": _FUND,
                                   "reason": "federation suite A2A settlement probe"})
    if fst != 200:
        raise PreconditionUnmet(f"treasury funding HTTP {fst}: {json.dumps(fbody, default=str)[:180]}")

    p0 = await _balance(rig, payer["jwt"])
    r0 = await _balance(rig, provider["jwt"])
    state["payer_before"], state["provider_before"] = p0, r0
    if p0 <= 0:
        raise PreconditionUnmet(f"payer funded but balance reads {p0}")

    # ── authorize (payer) ─────────────────────────────────────────────────
    ast_, auth = await _rest(rig, "POST", "/api/v1/a2a-payment/authorize", jwt=payer["jwt"],
                             body={"target_agent_did": provider["did"], "amount": _AMOUNT})
    state["authorize_status"] = ast_
    if ast_ != 200 or not isinstance(auth, dict):
        raise PreconditionUnmet(
            f"authorize HTTP {ast_}: {json.dumps(auth, default=str)[:220]}")
    token = auth.get("payment_token") or auth.get("token")
    token_id = auth.get("token_id") or auth.get("id")
    state["token_id"] = token_id
    if not token:
        raise PreconditionUnmet(f"authorize returned no token (keys={sorted(auth)[:10]})")

    # ── verify TWICE before settle (P25-001) ──────────────────────────────
    # The first verify CONSUMES the token; the second is the idempotency
    # contract a retrying service agent depends on.
    vst, ver = await _rest(rig, "POST", "/api/v1/a2a-payment/verify", jwt=provider["jwt"],
                           body={"token": token, "target_agent_did": provider["did"]})
    state["verify_status"] = vst
    state["verify_valid"] = (ver or {}).get("valid") if isinstance(ver, dict) else None

    v2st, ver2 = await _rest(rig, "POST", "/api/v1/a2a-payment/verify", jwt=provider["jwt"],
                             body={"token": token, "target_agent_did": provider["did"]})
    state["verify_repeat_status"] = v2st
    state["verify_repeat_valid"] = (ver2 or {}).get("valid") if isinstance(ver2, dict) else None

    # ── settle (payer) — the §BUYSERVICE step ─────────────────────────────
    sst, settled = await _rest(rig, "POST", "/api/v1/a2a-payment/settle", jwt=payer["jwt"],
                               body={"token": token, "success": True,
                                     "task_id": f"fedsuite-{uuid.uuid4().hex[:8]}"})
    state["settle_status"] = sst
    state["settle_body"] = json.dumps(settled, default=str)[:220]
    if sst == 403:
        # Name it, because this exact refusal is the shipped defect this guards.
        state["regression"] = ("settle refused 403 for an agent holding the frame's DEFAULT "
                               "roles — the §BUYSERVICE unsatisfiable-gate shape")
    if sst != 200:
        raise PreconditionUnmet(f"settle HTTP {sst}: {state['settle_body']}")
    state["settlement_tx"] = (settled or {}).get("settlement_tx_id") if isinstance(settled, dict) else None

    # ── verify after SETTLE: a spent token must NOT re-verify ─────────────
    v3st, ver3 = await _rest(rig, "POST", "/api/v1/a2a-payment/verify", jwt=provider["jwt"],
                             body={"token": token, "target_agent_did": provider["did"]})
    state["verify_after_settle_status"] = v3st
    state["verify_after_settle_valid"] = (ver3 or {}).get("valid") if isinstance(ver3, dict) else None

    amount = _num(_AMOUNT)

    async def predicate():
        p1 = await _balance(rig, payer["jwt"])
        r1 = await _balance(rig, provider["jwt"])
        d1 = await _delta(rig)
        evented = await _authorized_evented(rig, payer["did"], token_id)
        state["payer_after"], state["provider_after"] = p1, r1
        state["payer_spend"] = round(p0 - p1, 8)
        state["provider_gain"] = round(r1 - r0, 8)
        # The payer is debited the amount plus the fee, so bound rather than
        # equate; the provider receives the amount net of fee.
        paid = (p0 - p1) >= amount - 1e-9
        received = 0 < (r1 - r0) <= amount + 1e-9
        delta_ok = d1 is not None and abs(d1) < 1e-9
        # P25-001: a CONSUMED token still verifies true on a repeat call …
        idem_ok = (state["verify_valid"] is True
                   and state["verify_repeat_valid"] is True)
        # … and a SETTLED one does not, or a provider could be paid twice.
        spent_ok = state["verify_after_settle_valid"] is False
        state["verdict"] = {"payer_debited": paid, "provider_credited": received,
                            "delta_zero": delta_ok,
                            "consumed_token_reverifies": idem_ok,
                            "settled_token_is_spent": spent_ok,
                            "authorize_evented": evented}
        return bool(paid and received and delta_ok and idem_ok
                    and spent_ok and evented is True)

    return await rig.assert_within(
        budget_sec=75.0, predicate=predicate, poll_interval_sec=3.0,
        description="an agent with only the frame's default roles can authorize, "
                    "verify and SETTLE an A2A payment; the money moves both ways, "
                    "Δ holds, a consumed token re-verifies while a settled one "
                    "does not, and the authorization is in the ledger",
        capture_state=lambda: state,
    )
