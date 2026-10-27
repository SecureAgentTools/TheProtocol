"""THE CONTRACT SPINE driven end to end, with the money AND the ledger checked.

Four of the thirty "observed but uncovered" event types belong to this rail —
`ContractOffered`, `ContractAgreed`, `ContractMilestoneSubmitted`,
`ContractMilestoneReleased` — and until now the suite only PINNED them: it
asserted rows of that type exist somewhere, never that performing the act
produces one. A pin cannot tell a live emitter from a dead one that fired
last week.

This drives the real spine — create → accept (ESCROWS the client) → submit →
release (PAYS the provider) — and asserts three things together:

  * the money moved, in the right direction, at the right step;
  * the supply invariant did not move;
  * the EventStore RECORDED each step, keyed on the contract.

The third is not redundant. Δ is computed FROM events: drop an emit and the
credit and the debit vanish together, circulating never moves, and Δ sits at a
contented 0.0 while money genuinely moved in the TEG (§S4 found exactly that
shape live in `TEGBulkProxy._flush`). Money-moved AND Δ=0 is NOT proof the
ledger saw it.

⚠ AGGREGATE KEYS DIFFER BY EVENT TYPE ON THIS RAIL — measured, not assumed:
`ContractOffered` / `ContractAgreed` / `ContractMilestoneSubmitted` /
`ContractMilestoneReleased` are keyed on the CONTRACT id, while `ContractCreated`,
`ContractAccepted` and `ContractWorkSubmitted` (the legacy adapter's names) are
keyed on a DID. Querying the contract aggregate for `ContractCreated` returns
zero and reads exactly like a dead emitter. The four asserted here are the four
that genuinely live on the contract.

Sandbox treasury funding is APPROVED for sandbox mainframes (2026-09-04) and
explicitly NOT for prod; this is `requires`-gated to the sandbox frames and
funds through the canonical admin rail (FLOW 4), never a direct TEG mint.

⚠ Writes: two agents and one contract per run, tagged `fedsuite-ctr-*`. Agent
deletion is a SOFT delete that keeps a balance, so what an agent holds goes back to
the frame's treasury before its delete (throwaways, V0641).
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

_TOTAL = "5.0"           # dust; large enough to see, small enough to be nothing
_HOLD_POLLS = 3          # an absence claim is held, not sampled (see the MOU test)
_HOLD_SEC = 9.0          # > the ~6s money-settle lag measured on the AGORA rail
_FUND = "50.0"

# The four the v2 spine emits on the CONTRACT aggregate, in lifecycle order.
_SPINE_EVENTS = ["ContractOffered", "ContractAgreed",
                 "ContractMilestoneSubmitted", "ContractMilestoneReleased"]


def _soft(r: Any) -> Optional[str]:
    if isinstance(r, dict) and set(r.keys()) == {"_text"} and isinstance(r["_text"], str):
        return r["_text"]
    if isinstance(r, str):
        return r
    return None


async def _call(rig, label: str, tool: str, args: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    """One MCP tool call → (payload, refusal-or-None).

    adminRequest / adminQueryEventStore WRAP the upstream call as
    {status_code, response, ...} and return HTTP 200 for the MCP call itself, so
    a 422 from the wrapped endpoint reads as success unless the wrapper's own
    status is checked here.
    """
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
                headers: Optional[Dict[str, str]] = None) -> Tuple[int, Any]:
    """One REST call through adminRequest → (status_code, unwrapped body).

    `jwt` overrides the Bearer, which is how an AGENT-tier route is reached —
    the contract spine is agent-tier throughout (`contracts.engage`).
    ⚠ Returns a TUPLE. Treating it as a dict is silent: `isinstance(tuple, dict)`
    is False, so a caller falls through to its own not-found branch and blames
    the product.
    """
    args: Dict[str, Any] = {"method": method, "endpoint": endpoint}
    if body is not None:
        args["body"] = body
    if jwt:
        args["developer_jwt"] = jwt
    if headers:
        # `adminRequest` accepts an ALLOWLISTED header dict (idempotency-key,
        # x-capability-token, if-none-match, if-match). Five money rails 400
        # without an Idempotency-Key, so before the allowlist existed no MCP
        # caller could reach them at all.
        args["headers"] = headers
    try:
        r = await rig.mcp(label).call("adminRequest", args, timeout=60)
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"
    if not isinstance(r, dict):
        return -1, r
    code = r.get("status_code")
    return (code if isinstance(code, int) else -1), r.get("response")


def _num(v: Any) -> float:
    """Balances come back in SCIENTIFIC NOTATION ('1E+3') — int() RAISES on those."""
    if v is None:
        return 0.0
    try:
        return float(str(v))
    except Exception:
        return 0.0


async def _delta(rig) -> Optional[float]:
    """Supply invariant via the EventStore. The REGISTRY does not serve
    /projections/supply-audit. None means UNREADABLE, which is its own state."""
    r, refused = await _call(rig, "sandbox-A-admin", "adminQueryEventStore",
                             {"path": "/api/v1/projections/supply-audit"})
    if refused or not isinstance(r, dict):
        return None
    body = r.get("response") if isinstance(r.get("response"), dict) else r
    d = body.get("delta")
    return None if d is None else _num(d)


async def _new_agent(rig, tag: str) -> Dict[str, str]:
    r, refused = await _call(rig, "sandbox-A", "createAgent", {
        "name": f"fedsuite-ctr-{tag}-{uuid.uuid4().hex[:8]}",
        "description": "federation suite contract spine probe",
    })
    if refused or not isinstance(r, dict):
        raise PreconditionUnmet(f"createAgent refused for {tag}: {refused}")
    # createAgent reports its own failures as {"error": ...} with HTTP 200.
    if r.get("error"):
        raise PreconditionUnmet(f"createAgent error for {tag}: {r['error']}")
    cid = r.get("client_id") or (r.get("credentials") or {}).get("client_id")
    sec = r.get("client_secret") or (r.get("credentials") or {}).get("client_secret")
    did = r.get("did") or r.get("agent_did") or (r.get("agent") or {}).get("did")
    throwaways.made("sandbox-A", did)  # V0641: retired once its test's verdict is in (throwaways)
    if not (cid and sec and did):
        raise PreconditionUnmet(
            f"createAgent for {tag} returned no usable credential triple (keys={sorted(r)[:8]})")
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
    return {"did": did, "jwt": jwt, "client_id": cid}


async def _balance(rig, jwt: str) -> float:
    r, refused = await _call(rig, "sandbox-A", "getMyBalance", {"agent_jwt": jwt})
    if refused or not isinstance(r, dict):
        return 0.0
    for k in ("balance", "liquid_balance", "token_balance", "available"):
        if r.get(k) is not None:
            return _num(r[k])
    return 0.0


async def _contract_event_types(rig, cid: str) -> Optional[List[str]]:
    """Every event type the ES holds for this contract's aggregate.

    Returns None when the ES is unreadable — "could not check" must never read
    as "checked and nothing there". A zero here is a claim about the QUERY until
    the query has returned non-zero for something.
    """
    if not cid:
        return None
    r, refused = await _call(rig, "sandbox-A-admin", "adminQueryEventStore",
                             {"path": f"/api/v1/events/aggregate/{cid}"})
    if refused:
        return None
    # ⚠ /events/aggregate/{id} answers with a LIST. Unwrapping only a dict makes
    # the guard fall through to the wrapper, find no "events" key, and report an
    # empty ledger — alarming, plausible, and entirely the probe's fault.
    body = r.get("response", r) if isinstance(r, dict) and "response" in r else r
    if isinstance(body, list):
        events = body
    elif isinstance(body, dict):
        events = body.get("events") or body.get("items") or []
    else:
        return None
    out: List[str] = []
    for e in events:
        if isinstance(e, dict):
            t = str(e.get("event_type") or e.get("type") or "")
            if t:
                out.append(t)
    return out


async def _fund(rig, did: str, amount: str) -> Optional[str]:
    _st, resp = await _rest(rig, "POST", "/api/v1/teg/treasury/fund-agent",
                            body={"target_agent_did": did, "amount": amount,
                                  "reason": "federation suite contract spine probe"})
    # FLOW 4's field is target_agent_did — `agent_did` 422s with
    # "Field required: body -> target_agent_did".
    if _st != 200:
        return f"fund-agent HTTP {_st}: {json.dumps(resp, default=str)[:180]}"
    return None


@federation_test(
    name="contract_spine_milestone_release_moves_money_and_is_evented",
    category="contract_spine",
    budget_sec=150.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["contracts", "economic", "money", "delta", "event_emission"],
)
async def test_contract_spine_economic(rig: FederationTestRig) -> AssertionResult:
    """create → accept (escrow) → submit → release (pay), money + Δ + events.

    Each step can answer 200 while nothing settles and nothing is recorded;
    that is precisely the failure a read-only or pin-only suite cannot see.
    """
    state: Dict[str, Any] = {}

    # ── arrange (OUTSIDE the poller: assert_within swallows raises) ────────
    d0 = await _delta(rig)
    state["delta_before"] = d0
    if d0 is None:
        raise PreconditionUnmet("supply audit unreadable — cannot guard Δ, refusing to move money")
    if abs(d0) > 1e-9:
        raise PreconditionUnmet(f"Δ is already {d0}, not 0 — refusing to run an economic test")

    client = await _new_agent(rig, "client")
    provider = await _new_agent(rig, "provider")
    state["client"], state["provider"] = client["did"], provider["did"]

    fref = await _fund(rig, client["did"], _FUND)
    if fref:
        raise PreconditionUnmet(f"treasury funding refused: {fref}")

    c0 = await _balance(rig, client["jwt"])
    p0 = await _balance(rig, provider["jwt"])
    state["client_before"], state["provider_before"] = c0, p0
    if c0 <= 0:
        raise PreconditionUnmet(f"client funded but balance reads {c0} — nothing to escrow")

    # ── act ───────────────────────────────────────────────────────────────
    st, made = await _rest(rig, "POST", "/api/v1/contracts/v2", jwt=client["jwt"], body={
        "title": f"fedsuite spine {uuid.uuid4().hex[:6]}",
        "contract_type": "work_order",
        "total_amount": _TOTAL,
        "provider_did": provider["did"],      # private offer; NULL would be open
        "milestones": [{"title": "only", "amount": _TOTAL}],
        "draft": False,
    })
    state["create_status"] = st
    if st != 200 or not isinstance(made, dict):
        raise PreconditionUnmet(
            f"contract create HTTP {st}: {json.dumps(made, default=str)[:220]}")
    cid = made.get("id") or made.get("contract_id") or (made.get("contract") or {}).get("id")
    state["contract_id"] = cid
    if not cid:
        raise PreconditionUnmet(f"create returned no contract id (keys={sorted(made)[:10]})")

    acc_st, acc = await _rest(rig, "POST", f"/api/v1/contracts/v2/{cid}/accept",
                              jwt=provider["jwt"], body={})
    state["accept_status"] = acc_st
    if acc_st != 200:
        raise PreconditionUnmet(
            f"accept HTTP {acc_st}: {json.dumps(acc, default=str)[:220]}")

    # The escrow debit happens AT ACCEPT, not at release — measure it here so a
    # release-time-only check cannot mistake "never escrowed" for "already paid".
    c_escrowed = await _balance(rig, client["jwt"])
    state["client_after_escrow"] = c_escrowed
    state["escrow_debit"] = round(c0 - c_escrowed, 6)

    sub_st, sub = await _rest(rig, "POST", f"/api/v1/contracts/v2/{cid}/milestones/1/submit",
                              jwt=provider["jwt"], body={"deliverable": {"note": "fedsuite"}})
    state["submit_status"] = sub_st

    rel_st, rel = await _rest(rig, "POST", f"/api/v1/contracts/v2/{cid}/milestones/1/release",
                              jwt=client["jwt"], body={"stars": 5})
    state["release_status"] = rel_st
    if rel_st != 200:
        state["release_body"] = json.dumps(rel, default=str)[:220]

    # ── assert: the MONEY, Δ, and the LEDGER ──────────────────────────────
    total = _num(_TOTAL)

    async def predicate():
        c1 = await _balance(rig, client["jwt"])
        p1 = await _balance(rig, provider["jwt"])
        d1 = await _delta(rig)
        types = await _contract_event_types(rig, cid)
        state["client_after"], state["provider_after"], state["delta_after"] = c1, p1, d1
        state["provider_gain"] = round(p1 - p0, 6)
        state["client_spend"] = round(c0 - c1, 6)
        # The client is debited the full total at ESCROW and stays debited; the
        # provider gains the milestone net of any fee, so bound the gain by the
        # total rather than demanding an equality a fee would break.
        escrowed = (c0 - c_escrowed) > 0
        gained = 0 < (p1 - p0) <= total + 1e-9
        delta_ok = d1 is not None and abs(d1) < 1e-9
        if types is None:
            seen, missing = None, None
            evented = None                      # unreadable ≠ absent
        else:
            seen = sorted(set(types))
            missing = [e for e in _SPINE_EVENTS if e not in types]
            evented = not missing
        state["verdict"] = {"escrowed_at_accept": escrowed, "provider_gained": gained,
                            "delta_zero": delta_ok, "events_seen": seen,
                            "events_missing": missing, "evented": evented}
        return bool(escrowed and gained and delta_ok and evented is True)

    return await rig.assert_within(
        budget_sec=90.0, predicate=predicate, poll_interval_sec=3.0,
        description="contract escrows at accept, pays at release, Δ stays 0, "
                    "and all four spine events are recorded",
        capture_state=lambda: state,
    )


@federation_test(
    name="contract_spine_agreement_only_escrows_nothing",
    category="contract_spine",
    budget_sec=90.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["contracts", "economic", "money", "control"],
)
async def test_agreement_only_contract(rig: FederationTestRig) -> AssertionResult:
    """`total_amount == 0` is the MOU/NDA form: same lifecycle, NO escrow.

    This is the money test's control. The spine test above proves the escrow
    leg fires; without this one, a build that escrowed on EVERY contract —
    including the agreement-only form that must never touch money — would pass
    it just as happily. The pair distinguishes "escrow works" from "escrow is
    unconditional".

    ⚠ AN ABSENCE CLAIM MUST BE HELD, NOT SAMPLED ONCE. "The balance never
    moved" is true at t=0 on every build, including one that escrows
    asynchronously a few seconds later — and `assert_within` returns on the
    FIRST true predicate, so a single sample would return before a late debit
    ever landed. Measured on the neighbouring AGORA rail: money settles ~6s
    after the call that moves it, five seconds behind the status flip. So this
    requires the property to hold across `_HOLD_POLLS` consecutive reads
    spanning at least `_HOLD_SEC`, chosen above that observed lag.

    Found by applying the lesson from the AGORA control to my own test rather
    than assuming the new file was exempt.
    """
    state: Dict[str, Any] = {}

    d0 = await _delta(rig)
    state["delta_before"] = d0
    if d0 is None:
        raise PreconditionUnmet("supply audit unreadable — cannot guard Δ")

    client = await _new_agent(rig, "mou-client")
    provider = await _new_agent(rig, "mou-provider")
    state["client"], state["provider"] = client["did"], provider["did"]

    # Fund it anyway: an unfunded client cannot distinguish "did not escrow"
    # from "could not escrow", and the second proves nothing about the rule.
    fref = await _fund(rig, client["did"], _FUND)
    if fref:
        raise PreconditionUnmet(f"treasury funding refused: {fref}")
    c0 = await _balance(rig, client["jwt"])
    state["client_before"] = c0
    if c0 <= 0:
        raise PreconditionUnmet(f"client funded but balance reads {c0}")

    st, made = await _rest(rig, "POST", "/api/v1/contracts/v2", jwt=client["jwt"], body={
        "title": f"fedsuite mou {uuid.uuid4().hex[:6]}",
        "contract_type": "custom",
        "total_amount": "0",
        "provider_did": provider["did"],
        "draft": False,
    })
    state["create_status"] = st
    if st != 200 or not isinstance(made, dict):
        raise PreconditionUnmet(
            f"agreement-only create HTTP {st}: {json.dumps(made, default=str)[:220]}")
    cid = made.get("id") or made.get("contract_id") or (made.get("contract") or {}).get("id")
    state["contract_id"] = cid
    if not cid:
        raise PreconditionUnmet(f"create returned no contract id (keys={sorted(made)[:10]})")

    acc_st, acc = await _rest(rig, "POST", f"/api/v1/contracts/v2/{cid}/accept",
                              jwt=provider["jwt"], body={})
    state["accept_status"] = acc_st
    if acc_st != 200:
        raise PreconditionUnmet(
            f"agreement-only accept HTTP {acc_st}: {json.dumps(acc, default=str)[:220]}")

    held: Dict[str, Any] = {"n": 0, "since": None}

    async def predicate():
        import time
        c1 = await _balance(rig, client["jwt"])
        d1 = await _delta(rig)
        types = await _contract_event_types(rig, cid)
        state["client_after"], state["delta_after"] = c1, d1
        state["client_moved"] = round(c0 - c1, 6)
        unmoved = abs(c1 - c0) < 1e-9
        delta_ok = d1 is not None and abs(d1) < 1e-9
        # It is still a real agreement: the lifecycle events must be there even
        # though no money is. "No escrow" must not quietly mean "no contract".
        agreed = None if types is None else ("ContractAgreed" in types)
        ok_now = bool(unmoved and delta_ok and agreed is True)
        # Hold it: one true sample cannot distinguish "never escrowed" from
        # "has not escrowed YET". A single false read resets the streak, so a
        # late debit fails the test instead of arriving after it returned.
        if ok_now:
            if held["since"] is None:
                held["since"] = time.monotonic()
            held["n"] += 1
        else:
            held["n"], held["since"] = 0, None
        elapsed = 0.0 if held["since"] is None else time.monotonic() - held["since"]
        state["verdict"] = {"client_balance_unmoved": unmoved, "delta_zero": delta_ok,
                            "agreed_evented": agreed,
                            "held_polls": held["n"], "held_sec": round(elapsed, 1),
                            "events_seen": None if types is None else sorted(set(types))}
        return bool(ok_now and held["n"] >= _HOLD_POLLS and elapsed >= _HOLD_SEC)

    return await rig.assert_within(
        budget_sec=60.0, predicate=predicate, poll_interval_sec=3.0,
        description="an agreement-only contract is agreed and evented without "
                    "moving a single token, and STAYS unmoved across a window "
                    "longer than the observed money-settle lag",
        capture_state=lambda: state,
    )
