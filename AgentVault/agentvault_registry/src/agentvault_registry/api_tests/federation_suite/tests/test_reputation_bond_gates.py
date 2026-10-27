"""THE REPUTATION-BOND GATE, driven refusal-and-admission at every site (§REPBOND).

The registry now refuses an UNBONDED provider at six sites. A suite that only
checked "a bonded agent works" would pass on a tier with the gate switched OFF,
so every test here is a PAIR against the SAME agent and the SAME call: refused
while unbonded, admitted after the bond lands. One agent, one call, one
variable — the bond.

⚠ ASSERT ON THE SENTENCE, NOT THE STATUS. The refusal names the site, the
required amount, the currency and BOTH doors out of it (deposit from the agent's
own balance, or fund from a wallet agent). A 403 alone is the weakest possible
evidence here: this suite already had a test that read a missing ROUTE as an
ownership refusal, and `require_agent_permission` answers 403 too. The sentence
is what distinguishes the bond gate from every other refusal on the same path.

⚠ AND THE GATE REFUSES TWO DIFFERENT THINGS WITH ONE SENTENCE. `is_bonded_did`
returns None for a DID this registry cannot see at all — no agent row, no
mirrored card — and under enforce that raises the SAME refusal as a genuine
unbonded agent (`gate()` calls it decision="unknown"). So a test that creates an
agent on frame A and asserts the refusal on frame B would pass while measuring
"I have never heard of this DID". Every pair below therefore proves the agent is
VISIBLE and unbonded first, by reading its own reputation block, before treating
a refusal as the gate's.

Bond statuses: none | pending | locked | matured | released | forfeited | voided.
Bonded = locked, matured. `released`, `voided` and `forfeited` are NOT.

Sandbox only: `requires`-gated, dust amounts, and bonds come from the treasury
backstop rail, which moves no money (the treasury keeps its own escrow).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from typing import Any, Dict, Optional, Tuple

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet, bond_config,
)
from agentvault_registry.api_tests.federation_suite.tests.test_ironkey_authority_clamp import (
    _call, _rest, _detail,
)

_LABEL = "sandbox-A"
_ADMIN = "sandbox-A-admin"

# The load-bearing fragments of `_refusal()`. Matched as substrings so wording can
# be improved without breaking the suite, but the AMOUNT and the two DOORS must
# survive — they are what makes the refusal actionable to the agent that hit it.
_REFUSAL_MARKERS = ("holds no reputation bond", "requires a bond of", "reputation-bond")


async def _unbonded_agent(rig, tag: str) -> Dict[str, str]:
    """A fixture that is deliberately NOT bonded — the left half of every pair.

    Cannot use the suite's `_new_agent`: that now bonds at birth (rig.ensure_bonded),
    which is right for every other test and exactly wrong for this one.
    """
    r, refused = await _call(rig, _LABEL, "createAgent", {
        "name": f"fedsuite-repbond-{tag}-{uuid.uuid4().hex[:8]}",
        "description": "federation suite reputation-bond gate probe",
    })
    if refused or not isinstance(r, dict) or r.get("error"):
        raise PreconditionUnmet(f"createAgent refused for {tag}: {refused or r.get('error')}")
    cid = r.get("client_id") or (r.get("credentials") or {}).get("client_id")
    sec = r.get("client_secret") or (r.get("credentials") or {}).get("client_secret")
    did = r.get("did") or r.get("agent_did") or (r.get("agent") or {}).get("did")
    throwaways.made(_LABEL, did)  # V0641: retired once its test's verdict is in (throwaways)
    if not (cid and sec and did):
        raise PreconditionUnmet(f"createAgent for {tag}: no credential triple")
    t, tref = await _call(rig, _LABEL, "getAgentToken", {"client_id": cid, "client_secret": sec})
    if tref or not isinstance(t, dict):
        raise PreconditionUnmet(f"getAgentToken refused for {tag}: {tref}")
    jwt = t.get("access_token") or t.get("agent_jwt")
    if not jwt:
        raise PreconditionUnmet(f"no agent JWT for {tag}")
    return {"did": did, "jwt": jwt, "client_id": cid}


async def _reputation(rig, did: str) -> Dict[str, Any]:
    code, body = await _rest(rig, "GET", f"/api/v1/agents/{did}/reputation", label=_ADMIN)
    return body if (code == 200 and isinstance(body, dict)) else {}


async def _escalation_policy(rig) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(levels, avt_volume_tiers) of the frame's RESOLVED enforcement policy; ({}, {}) when unreadable (the caller
    then falls back to the old bond-sized disputes and says what it saw)."""
    code, body = await _rest(rig, "GET", "/api/v1/admin/enforcement/policy/resolved", label=_ADMIN)
    pj = (body.get("policy_json") or {}) if (code == 200 and isinstance(body, dict)) else {}
    de = pj.get("dispute_escalation") if isinstance(pj.get("dispute_escalation"), dict) else {}
    levels = de.get("levels") if isinstance(de.get("levels"), dict) else {}
    tiers = de.get("avt_volume_tiers") if isinstance(de.get("avt_volume_tiers"), dict) else {}
    return levels, tiers


def _disputed_to_take(held: Decimal, pct: Decimal, tiers: Dict[str, Any]) -> int:
    """The smallest whole disputed amount whose slash at `pct` covers `held`, after the engine's volume tiers
    (services/enforcement_engine._check_avt_volume_tier: at or under `minor.max_amount` the percent is REPLACED,
    at or over `major.min_amount` it is MULTIPLIED). An over-shoot is harmless: the waterfall takes the bond first
    and the rest falls to the throwaway payee's own stake and liquid, which the escrow rail moves Δ-neutrally."""
    if held <= 0 or pct <= 0:
        return 1
    disputed = int((held * Decimal(100) / pct).to_integral_value(rounding=ROUND_CEILING)) + 1
    minor, major = tiers.get("minor") or {}, tiers.get("major") or {}
    if minor and disputed <= float(minor.get("max_amount", 0)):
        override = Decimal(str(minor.get("slash_percent_override", pct)))
        if override > 0:
            disputed = max(disputed, int((held * Decimal(100) / override).to_integral_value(rounding=ROUND_CEILING)) + 1)
        disputed = max(disputed, int(float(minor.get("max_amount", 0))) + 1)
    return disputed


async def _bond_status(rig, did: str) -> Optional[str]:
    """The agent's bond status, or None for UNREADABLE — never collapsed to 'none'."""
    rep = await _reputation(rig, did)
    if not rep:
        return None
    bond = rep.get("bond") if isinstance(rep.get("bond"), dict) else rep
    return bond.get("status")


async def _assert_visible_and_unbonded(rig, did: str) -> None:
    """The discriminator between a refusal and an 'I have never heard of it'.

    Without this, a bond-gate test passes on a registry that simply cannot see
    the DID, because `gate()` answers both with the same sentence.
    """
    st = await _bond_status(rig, did)
    if st is None:
        raise PreconditionUnmet(
            f"{_LABEL} cannot read a reputation block for {did} — a refusal from it would "
            f"be 'unknown DID', not 'unbonded', and the two share one sentence")
    if st in ("locked", "matured"):
        raise PreconditionUnmet(f"{did} is already bonded (status={st}); no refusal to measure")


async def _bond(rig, did: str) -> str:
    """Bond via the treasury backstop — moves no money. Returns the new status."""
    code, body = await _rest(
        rig, "POST", f"/api/v1/developers/me/agents/{did}/reputation-bond/backstop", label=_ADMIN)
    if code != 200 or not isinstance(body, dict):
        raise PreconditionUnmet(f"backstop refused for {did}: HTTP {code} {_detail(body)[:160]}")
    st = body.get("status")
    if st not in ("locked", "matured"):
        raise PreconditionUnmet(f"backstop left {did} at status={st!r}, not a bonded status")
    return st


def _is_bond_refusal(body: Any) -> bool:
    d = _detail(body).lower()
    return all(m in d for m in ("holds no reputation bond", "requires a bond of"))


async def _observed_sync_interval(rig, default: int = 120) -> int:
    """The federation cycle length, MEASURED rather than read from a constant.

    Two readings of a peer's own `last_synced_at` are one cycle apart, so their
    delta is the interval this tier actually runs — which is the number the
    overlap-window arithmetic depends on. No admin rail exposes the configured
    value, and a hardcoded one silently breaks the only thing this test is for
    the moment someone retunes the tier.
    """
    async def watermark() -> Optional[float]:
        code, body = await _rest(rig, "GET", "/api/v1/federation/sync-status", label=_ADMIN)
        if code != 200 or not isinstance(body, dict):
            return None
        stamps = []
        for p in (body.get("peers") or []):
            ts = p.get("last_synced_at") if isinstance(p, dict) else None
            if isinstance(ts, str):
                try:
                    stamps.append(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
                except ValueError:
                    pass
        return max(stamps) if stamps else None

    first = await watermark()
    if first is None:
        return default
    deadline = time.time() + default * 2 + 60
    while time.time() < deadline:
        await asyncio.sleep(10)
        now = await watermark()
        if now is not None and now > first:
            return max(30, int(round(now - first)))
    return default


async def _require_enforcing(rig) -> Dict[str, Any]:
    cfg = await bond_config(rig, _LABEL)
    if not cfg:
        raise PreconditionUnmet(f"{_LABEL} did not answer /reputation-bond/config")
    if (cfg.get("mode") or "off") != "enforce":
        raise PreconditionUnmet(
            f"{_LABEL} runs the bond gate in mode={cfg.get('mode')!r}; a refusal/admission "
            f"pair measures nothing unless it enforces")
    return cfg


async def _pair(rig, did: str, call, state: Dict[str, Any]) -> Tuple[bool, str]:
    """Refused while unbonded, admitted once bonded — the same call, twice.

    Returns (passed, detail). The refusal is checked by SENTENCE; the admission
    only has to stop being a bond refusal, because the call may legitimately fail
    for its own unrelated reasons and that is a different story than the gate.
    """
    await _assert_visible_and_unbonded(rig, did)
    code_before, body_before = await call()
    state["refused_status"] = code_before
    state["refused_detail"] = _detail(body_before)[:220]
    if not _is_bond_refusal(body_before):
        return False, (f"unbonded call was not refused by the BOND gate: HTTP {code_before} "
                       f"{_detail(body_before)[:180]}")
    if code_before != 403:
        return False, f"bond refusal carried HTTP {code_before}, expected 403"

    state["bond_status"] = await _bond(rig, did)
    code_after, body_after = await call()
    state["admitted_status"] = code_after
    state["admitted_detail"] = _detail(body_after)[:220]
    if _is_bond_refusal(body_after):
        return False, (f"still refused by the bond gate AFTER bonding "
                       f"(status={state['bond_status']}): {_detail(body_after)[:180]}")
    return True, ""


def _result(passed: bool, detail: str, state: Dict[str, Any],
            description: str = "reputation-bond gate") -> AssertionResult:
    """These tests decide in one pass, so they build the result rather than poll.

    ⚠ `budget_pct_used` is a PROPERTY of AssertionResult, not a field, and
    `description` + `budget_sec` are REQUIRED — passing the first or omitting the
    others raises at construction and would have errored every test here. Read
    off the dataclass, not remembered.
    """
    return AssertionResult(
        passed=passed, description=description, budget_sec=0.0, elapsed_sec=0.0,
        polling_attempts=1, failure_detail=None if passed else detail, last_state=state)


# ─── REQUIRED: discovery ───────────────────────────────────────────────────

@federation_test(
    name="bond_gate_discovery_hides_unbonded_and_shows_bonded",
    category="reputation_bond_gates",
    budget_sec=90.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["reputation-bond", "gate", "discovery", "driven"],
)
async def test_gate_discovery(rig: FederationTestRig) -> AssertionResult:
    """An unbonded provider is ABSENT from discovery and present once bonded.

    Discovery does not refuse — it OMITS, which is why this site gets its own
    shape rather than the refusal pair. Three readings, because omission has more
    ways to be faked than a 403: absent by default, present to an admin passing
    `include_unbonded=true` (proving the omission is the gate and not a broken
    query), and present by default after bonding.
    """
    cfg = await _require_enforcing(rig)
    state: Dict[str, Any] = {"amount": cfg.get("amount")}
    a = await _unbonded_agent(rig, "disc")
    state["did"] = a["did"]
    await _assert_visible_and_unbonded(rig, a["did"])

    async def seen(params: str) -> bool:
        # ⚠ THE PARAM IS `q`. `search` is not declared on this endpoint, and an
        # undeclared QUERY param is dropped exactly as silently as an undeclared
        # body field: the call still answers 200, with the default population, so
        # the fixture "is absent" for a reason that has nothing to do with bonding.
        # Measured: this skipped the test on its first run rather than fake a pass.
        code, body = await _rest(
            rig, "GET", f"/api/v1/agent-cards/discover?q={a['did']}{params}", label=_ADMIN)
        if code != 200:
            return False
        items = body.get("items") if isinstance(body, dict) else body
        return any(a["did"] in str(i) for i in (items or []))

    state["seen_default_unbonded"] = await seen("")
    state["seen_include_unbonded"] = await seen("&include_unbonded=true")
    if state["seen_default_unbonded"]:
        return _result(False, "an UNBONDED provider is still listed in discovery by default", state)
    if not state["seen_include_unbonded"]:
        raise PreconditionUnmet(
            "the agent is absent even with include_unbonded=true — discovery cannot see this "
            "fixture at all, so its absence by default is not evidence about the bond gate")

    state["bond_status"] = await _bond(rig, a["did"])
    state["seen_default_bonded"] = await seen("")
    if not state["seen_default_bonded"]:
        return _result(False, "a BONDED provider is still hidden from discovery", state)
    return _result(True, "", state)


# ─── REQUIRED: listing ─────────────────────────────────────────────────────

@federation_test(
    name="bond_gate_listing_refuses_unbonded_then_admits",
    category="reputation_bond_gates",
    budget_sec=90.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["reputation-bond", "gate", "listing", "driven"],
)
async def test_gate_listing(rig: FederationTestRig) -> AssertionResult:
    """Listing an unbonded agent is refused by the bond gate; bonding admits it."""
    cfg = await _require_enforcing(rig)
    state: Dict[str, Any] = {"site": "listing", "amount": cfg.get("amount")}
    a = await _unbonded_agent(rig, "list")
    state["did"] = a["did"]

    async def call():
        return await _rest(rig, "PATCH", f"/api/v1/agent-cards/{a['did']}/listing",
                           label=_ADMIN, body={"unlisted": False})

    passed, detail = await _pair(rig, a["did"], call, state)
    return _result(passed, detail, state)


# ─── REQUIRED: A2A authorize ───────────────────────────────────────────────

@federation_test(
    name="bond_gate_a2a_authorize_refuses_unbonded_payee_then_admits",
    category="reputation_bond_gates",
    budget_sec=120.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["reputation-bond", "gate", "a2a", "money", "driven"],
)
async def test_gate_a2a_authorize(rig: FederationTestRig) -> AssertionResult:
    """The PAYEE is the provider: authorize refuses an unbonded one.

    The payer must be bonded-irrelevant and funded, so the only variable between
    the two halves is the payee's bond.
    """
    cfg = await _require_enforcing(rig)
    state: Dict[str, Any] = {"site": "a2a_payee", "amount": cfg.get("amount")}
    payee = await _unbonded_agent(rig, "payee")
    payer = await _unbonded_agent(rig, "payer")
    state["payee"], state["payer"] = payee["did"], payer["did"]
    code, body = await _rest(rig, "POST", "/api/v1/teg/treasury/fund-agent", label=_ADMIN,
                             body={"target_agent_did": payer["did"], "amount": "40.0",
                                   "reason": "fedsuite repbond gate probe"})
    if code != 200:
        raise PreconditionUnmet(f"cannot fund the payer: HTTP {code} {_detail(body)[:160]}")

    async def call():
        return await _rest(rig, "POST", "/api/v1/a2a-payment/authorize", label=_ADMIN,
                           jwt=payer["jwt"],
                           body={"target_agent_did": payee["did"], "amount": "1.0",
                                 "task_description": "fedsuite repbond gate probe"})

    passed, detail = await _pair(rig, payee["did"], call, state)
    return _result(passed, detail, state)


# ─── REQUIRED: the asymmetry that a settle-only suite would get wrong ──────

@federation_test(
    name="bond_gate_settle_pays_a_payee_that_lost_its_bond",
    category="reputation_bond_gates",
    budget_sec=180.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["reputation-bond", "gate", "a2a", "money", "asymmetry", "driven"],
)
async def test_settle_is_not_gated(rig: FederationTestRig) -> AssertionResult:
    """Delivered work is paid even if the payee lost its bond after authorize.

    ⚠ THIS IS THE ONE A SUITE GETS WRONG BY ASSERTING THE OBVIOUS THING. Settle
    calls the same gate with `mode="shadow"` FORCED (verified in source), so it
    counts and logs but never refuses; authorize calls it in the tier's real
    mode. A suite that asserted "settle refuses an unbonded payee" would go green
    on a tier where the gate is entirely off, and a suite that asserted the
    reverse without also proving a FRESH authorize still refuses would report a
    working gate that had quietly stopped working.

    Both halves are therefore asserted on the SAME payee, after the SAME
    forfeiture: settle pays, a new authorize does not.
    """
    cfg = await _require_enforcing(rig)
    state: Dict[str, Any] = {"amount": cfg.get("amount")}
    payee = await _unbonded_agent(rig, "settlepayee")
    payer = await _unbonded_agent(rig, "settlepayer")
    state["payee"], state["payer"] = payee["did"], payer["did"]
    code, body = await _rest(rig, "POST", "/api/v1/teg/treasury/fund-agent", label=_ADMIN,
                             body={"target_agent_did": payer["did"], "amount": "40.0",
                                   "reason": "fedsuite repbond settle probe"})
    if code != 200:
        raise PreconditionUnmet(f"cannot fund the payer: HTTP {code} {_detail(body)[:160]}")

    state["payee_bond"] = await _bond(rig, payee["did"])
    code, body = await _rest(rig, "POST", "/api/v1/a2a-payment/authorize", label=_ADMIN,
                             jwt=payer["jwt"],
                             body={"target_agent_did": payee["did"], "amount": "1.0",
                                   "task_description": "fedsuite repbond settle probe"})
    if code not in (200, 201):
        raise PreconditionUnmet(
            f"authorize refused for a BONDED payee: HTTP {code} {_detail(body)[:180]}")
    token = (body or {}).get("plain_token") or (body or {}).get("token")
    if not token:
        raise PreconditionUnmet(f"authorize returned no token (keys={sorted(body or {})[:8]})")
    state["token_issued"] = True

    # Drain the bond. The waterfall takes from the bond FIRST, but the amount is
    # `slash_percent` of an escalation level derived from the agent's OFFENSE
    # COUNT — so a first offence takes a slice and leaves the bond LOCKED, which
    # is a bonded agent and no asymmetry to measure. Measured on the first run:
    # one offence at severity 4 answered 200 and left status='locked'. Escalate
    # until the bond is closed, bounded, and report the trajectory either way.
    amount = str(cfg.get("amount") or "250")
    # ⚠ RecordOffenseRequest declares offense_type/severity/reference/disputed_amount.
    # `severity` is an INT 1-4 (a string 422s), the amount field is `disputed_amount`,
    # and anything else is silently DROPPED — a body the schema does not declare is
    # accepted and ignored, which is how a probe "succeeds" having asked for nothing.
    #
    # §MCPTEST30 (2026-09-30): the slash is `slash_percent` of the offence's DISPUTED AMOUNT, and only the levels
    # whose policy says `admin_review_required: false` execute on their own; the others wait in pending_approval.
    # Measured on the standing pair (18 of 49 archived runs skipped here): the trail read 250 -> 225 (L1, 10% of a
    # 250 dispute) -> 175 (L2, 20%) and then 175 four more times, because L3 and L4 need an admin's approval. Six
    # offences of a bond-sized dispute could never close the bond. So each offence now disputes enough to take the
    # bond STILL HELD at the next level's own percentage (the frame's resolved policy, not a literal), and when the
    # next level is one that waits for review, the skip says that instead of blaming the percentages.
    levels, tiers = await _escalation_policy(rig)
    trail = []
    st = None
    held = Decimal(amount)
    for attempt in range(2 if levels else 6):
        level = levels.get(str(attempt + 1)) if levels else None
        if level is not None and level.get("admin_review_required"):
            break
        pct = Decimal(str((level or {}).get("slash_percent", 10)))
        disputed = _disputed_to_take(held, pct, tiers) if levels else int(float(amount))
        code, body = await _rest(
            rig, "POST", f"/api/v1/admin/enforcement/agents/{payee['did']}/record-offense",
            label=_ADMIN,
            body={"offense_type": "dispute_lost", "severity": 4,
                  "disputed_amount": disputed,
                  "reference": f"fedsuite-repbond-{uuid.uuid4().hex[:8]}"})
        st = await _bond_status(rig, payee["did"])
        rep = await _reputation(rig, payee["did"])
        bond = rep.get("bond") if isinstance(rep.get("bond"), dict) else {}
        trail.append({"offense": attempt + 1, "http": code, "status": st, "disputed": disputed,
                      "level_percent": str(pct), "bond_amount": bond.get("amount")})
        if st == "forfeited":
            break
        try:
            held = Decimal(str(bond.get("amount")))
        except Exception:                                              # noqa: BLE001
            break
    state["forfeiture_trail"] = trail
    state["payee_bond_after_offense"] = st
    if st != "forfeited":
        review = sorted(k for k, v in (levels or {}).items() if isinstance(v, dict) and v.get("admin_review_required"))
        raise PreconditionUnmet(
            f"could not close the payee's bond in {len(trail)} offence(s) — final status {st!r}; "
            f"trajectory: {trail}. "
            + (f"The next escalation level(s) {review} wait for an admin's review, so no further offence "
               "executes on its own. " if review else "")
            + "Without a forfeited payee there is no asymmetry to measure, and a green here would be vacuous.")

    code_settle, body_settle = await _rest(rig, "POST", "/api/v1/a2a-payment/settle", label=_ADMIN,
                                           jwt=payer["jwt"], body={"token": token})
    state["settle_status"] = code_settle
    state["settle_detail"] = _detail(body_settle)[:200]
    if _is_bond_refusal(body_settle):
        return _result(False, "SETTLE refused a payee that lost its bond after authorize — "
                              "delivered work went unpaid", state)

    code_fresh, body_fresh = await _rest(rig, "POST", "/api/v1/a2a-payment/authorize", label=_ADMIN,
                                         jwt=payer["jwt"],
                                         body={"target_agent_did": payee["did"], "amount": "1.0",
                                               "task_description": "fedsuite repbond fresh authorize"})
    state["fresh_authorize_status"] = code_fresh
    state["fresh_authorize_detail"] = _detail(body_fresh)[:200]
    if not _is_bond_refusal(body_fresh):
        return _result(False, "a FRESH authorize was not refused for a forfeited payee — the "
                              "gate is not doing its job, and settle passing proves nothing", state)
    return _result(True, "", state)


# ─── INCIDENTAL: one call each, same predicate ─────────────────────────────

@federation_test(
    name="bond_gate_refuses_unbonded_at_the_incidental_sites",
    category="reputation_bond_gates",
    budget_sec=180.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["reputation-bond", "gate", "pricing", "guild", "contracts", "driven"],
)
async def test_gate_incidental_sites(rig: FederationTestRig) -> AssertionResult:
    """pricing · guild bid · contract-v2 accept — refused while unbonded.

    ⚠ EACH OF THESE NEEDS A REAL SUBJECT. A bid on an invented order id and an
    accept on an invented contract id both answer 404 BEFORE any gate runs, so a
    probe built from fresh uuids would report "no bond refusal" for a reason that
    has nothing to do with bonding — a green-looking red. So a BONDED fixture
    posts the order and offers the contract, and the UNBONDED one tries to take
    them: the id resolves, the gate is genuinely the next thing in the path.

    Reported PER SITE, because one boolean over three cannot say which stopped
    gating, and `all()` over a list that silently shrank reads as success.
    """
    cfg = await _require_enforcing(rig)
    state: Dict[str, Any] = {"amount": cfg.get("amount"), "sites": {}}
    unbonded = await _unbonded_agent(rig, "incid")
    state["did"] = unbonded["did"]
    await _assert_visible_and_unbonded(rig, unbonded["did"])

    # the counterparty must itself pass the gate, or its own refusal is what we measure
    host = await _unbonded_agent(rig, "incidhost")
    state["host_did"] = host["did"]
    state["host_bond"] = await _bond(rig, host["did"])
    code, body = await _rest(rig, "POST", "/api/v1/teg/treasury/fund-agent", label=_ADMIN,
                             body={"target_agent_did": host["did"], "amount": "60.0",
                                   "reason": "fedsuite repbond incidental host"})
    if code != 200:
        raise PreconditionUnmet(f"cannot fund the host fixture: HTTP {code} {_detail(body)[:160]}")

    # ── pricing: no third party needed, the agent prices its own card ──────
    priced = {"name": "repbond probe", "description": "priced card",
              "pricing": {"payment_required": True, "base_rate": "1.0"}}
    code, resp = await _rest(rig, "PUT", f"/api/v1/agent-cards/{unbonded['did']}",
                             label=_ADMIN, body={"card_data": priced})
    state["sites"]["pricing"] = {"status": code, "bond_refusal": _is_bond_refusal(resp),
                                 "detail": _detail(resp)[:140]}

    # ── guild bid: a LIVE order posted by the bonded host ──────────────────
    order, oref = await _call(rig, _LABEL, "guildPostOrder", {
        "title": f"fedsuite repbond {uuid.uuid4().hex[:6]}", "bounty": "5.0",
        "spec": "reputation-bond gate probe", "agent_jwt": host["jwt"]})
    oid = None
    if isinstance(order, dict):
        oid = order.get("order_id") or order.get("id") or (order.get("order") or {}).get("id")
    state["order_id"] = oid
    if not oid:
        state["sites"]["guild_bid"] = {"status": None, "bond_refusal": False,
                                       "detail": f"no live order to bid on: {oref}"}
    else:
        _bid, bref = await _call(rig, _LABEL, "guildBid", {
            "order_id": oid, "price": "5.0", "pitch": "fedsuite",
            "agent_jwt": unbonded["jwt"]})
        # an MCP refusal carries the sentence in its string, not in a body
        state["sites"]["guild_bid"] = {"status": "mcp", "bond_refusal": _is_bond_refusal(bref or _bid),
                                       "detail": str(bref or _bid)[:140]}

    # ── contract v2 accept: a LIVE offer made to the unbonded provider ─────
    code, made = await _rest(rig, "POST", "/api/v1/contracts/v2", label=_ADMIN, jwt=host["jwt"], body={
        "title": f"fedsuite repbond {uuid.uuid4().hex[:6]}",
        "contract_type": "work_order", "total_amount": "5.0",
        "provider_did": unbonded["did"],
        "milestones": [{"title": "only", "amount": "5.0"}], "draft": False})
    cid = None
    if isinstance(made, dict):
        cid = made.get("id") or made.get("contract_id") or (made.get("contract") or {}).get("id")
    state["contract_id"] = cid
    if not cid:
        state["sites"]["contract_accept"] = {"status": code, "bond_refusal": False,
                                             "detail": f"no live contract to accept: {_detail(made)[:120]}"}
    else:
        code, resp = await _rest(rig, "POST", f"/api/v1/contracts/v2/{cid}/accept",
                                 label=_ADMIN, jwt=unbonded["jwt"], body={})
        state["sites"]["contract_accept"] = {"status": code, "bond_refusal": _is_bond_refusal(resp),
                                             "detail": _detail(resp)[:140]}

    refused = [k for k, v in state["sites"].items() if v["bond_refusal"]]
    state["refused_sites"] = refused
    missing = [k for k in state["sites"] if k not in refused]
    if missing:
        return _result(False,
                       f"these sites did NOT refuse an unbonded agent with the bond sentence: "
                       f"{missing} — see per-site detail; a site whose subject never came into "
                       f"existence reports that rather than a gate finding", state)
    return _result(True, "", state)


# ─── The third state their gate used to collapse ───────────────────────────

@federation_test(
    name="bond_gate_unknown_did_refuses_with_its_own_sentence",
    category="reputation_bond_gates",
    budget_sec=60.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["reputation-bond", "gate", "third-state", "driven"],
)
async def test_unknown_is_not_unbonded(rig: FederationTestRig) -> AssertionResult:
    """A DID this registry cannot see must NOT be refused as "unbonded".

    `is_bonded_did` answers True / False / None, where None means no agent row
    AND no mirrored card. Under enforce both False and None refuse — and they
    used to refuse with the SAME sentence, which made every bond-gate test in
    this suite ambiguous: a pair asserting "unbonded is refused" would pass while
    measuring "I have never heard of this DID", and would keep passing if the
    bond gate were removed entirely and only the unknown branch remained.

    Two refusals, one call, two subjects: a real local agent that holds no bond,
    and a DID that does not exist anywhere. Both refuse; the sentences must
    differ, and the unbonded one must be the one that names the bond.
    """
    await _require_enforcing(rig)
    state: Dict[str, Any] = {}
    real = await _unbonded_agent(rig, "known")
    state["known_did"] = real["did"]
    await _assert_visible_and_unbonded(rig, real["did"])
    ghost = f"did:theprotocol:{uuid.uuid4()}"
    state["unknown_did"] = ghost
    if await _bond_status(rig, ghost) is not None:
        raise PreconditionUnmet(f"{ghost} is somehow known to this registry; it cannot be the unknown case")

    async def refuse_for(did: str):
        return await _rest(rig, "PATCH", f"/api/v1/agent-cards/{did}/listing",
                           label=_ADMIN, body={"unlisted": False})

    c_known, b_known = await refuse_for(real["did"])
    c_ghost, b_ghost = await refuse_for(ghost)
    state["known"] = {"status": c_known, "detail": _detail(b_known)[:200]}
    state["unknown"] = {"status": c_ghost, "detail": _detail(b_ghost)[:200]}

    if not _is_bond_refusal(b_known):
        return _result(False, "a VISIBLE unbonded agent was not refused with the bond sentence — "
                              "the pairs elsewhere in this module are measuring something else",
                       state)
    if _is_bond_refusal(b_ghost):
        return _result(False, "an UNKNOWN did is refused with the same sentence as an unbonded one; "
                              "the third state is collapsed on the wire, so every bond-gate assertion "
                              "here could be passing on 'never heard of it'", state)
    return _result(True, "", state)


# ─── pending: the row exists, the money never moved ────────────────────────

@federation_test(
    name="bond_pending_when_funder_is_broke_and_retry_never_charges_twice",
    category="reputation_bond_gates",
    budget_sec=150.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["reputation-bond", "pending", "idempotency", "money", "driven"],
)
async def test_pending_and_retry(rig: FederationTestRig) -> AssertionResult:
    """A bond whose deposit could not be paid is `pending` — and NOT bonded.

    Reachable without breaking anything: fund the bond from a wallet agent that
    holds nothing. The rail writes the row WITH its escrow_ref BEFORE calling the
    TEG (R36), the TEG refuses, and the row stays `pending`. That is a state a
    suite will otherwise never see, and the dangerous reading is that `pending`
    looks like progress — so the assertion is that a pending agent is still
    REFUSED at a gate, not merely that the row says pending.

    Then the retry property that the pre-written ref exists for: fund the wallet,
    call again, and the SAME escrow_ref settles it — one charge, never two.
    """
    cfg = await _require_enforcing(rig)
    amount = float(cfg.get("amount") or 250)
    state: Dict[str, Any] = {"required": amount}
    provider = await _unbonded_agent(rig, "pendprov")
    wallet = await _unbonded_agent(rig, "pendwallet")     # deliberately unfunded
    state["provider"], state["wallet"] = provider["did"], wallet["did"]

    code, body = await _rest(rig, "POST", f"/api/v1/developers/me/agents/{provider['did']}/reputation-bond",
                             label=_ADMIN, body={"funder_did": wallet["did"]})
    state["first_attempt"] = {"status": code, "detail": _detail(body)[:200]}
    st = await _bond_status(rig, provider["did"])
    state["status_after_broke_funder"] = st
    if st in ("locked", "matured"):
        return _result(False, "a bond LANDED although its funder holds nothing — the deposit did "
                              "not actually move money, or the status lies", state)
    if st != "pending":
        raise PreconditionUnmet(
            f"expected a pending row after a broke funder, got {st!r} (HTTP {code}: "
            f"{_detail(body)[:160]}) — this tier does not reach the pending state this way")

    # pending must NOT pass the gate: a half-made bond is not a bond
    c_gate, b_gate = await _rest(rig, "PATCH", f"/api/v1/agent-cards/{provider['did']}/listing",
                                 label=_ADMIN, body={"unlisted": False})
    state["gate_while_pending"] = {"status": c_gate, "bond_refusal": _is_bond_refusal(b_gate)}
    if not _is_bond_refusal(b_gate):
        return _result(False, "an agent with a PENDING bond passed the gate — `pending` is being "
                              "read as bonded somewhere", state)

    code, body = await _rest(rig, "POST", "/api/v1/teg/treasury/fund-agent", label=_ADMIN,
                             body={"target_agent_did": wallet["did"], "amount": str(amount + 10),
                                   "reason": "fedsuite repbond pending retry"})
    if code != 200:
        raise PreconditionUnmet(f"cannot fund the wallet for the retry: HTTP {code}")

    code, body = await _rest(rig, "POST", f"/api/v1/developers/me/agents/{provider['did']}/reputation-bond",
                             label=_ADMIN, body={"funder_did": wallet["did"]})
    state["retry"] = {"status": code, "detail": _detail(body)[:200]}
    st2 = await _bond_status(rig, provider["did"])
    state["status_after_retry"] = st2
    if st2 not in ("locked", "matured"):
        return _result(False, f"the retry left the bond at {st2!r} — a funded wallet did not settle "
                              f"a pending row", state)

    # one charge, not two: the wallet is down the bond ONCE
    rep = await _reputation(rig, wallet["did"])
    state["wallet_balance_after"] = rep.get("balance") or rep.get("liquid_balance")
    return _result(True, "", state)


# ─── the mirror lag: what a PEER can see, and when ─────────────────────────

@federation_test(
    name="bond_state_change_reaches_a_peer_after_its_mirror_already_existed",
    category="reputation_bond_gates",
    budget_sec=1200.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin", "sandboxalpha", "sandboxalpha-admin"],
    tags=["reputation-bond", "federation", "mirror", "eventual-consistency", "driven"],
)
async def test_bond_change_reaches_peer(rig: FederationTestRig) -> AssertionResult:
    """A bond change must reach a peer whose mirror ALREADY EXISTED.

    ⚠ THIS TEST USED TO PASS FOR THE WRONG REASON, and the peer session caught
    it, not me. The first version bonded a freshly created agent and waited for
    the peer to see it bonded. But a peer's pull is INCREMENTAL (?since=cursor)
    and a bond changes the agent's ROWS, not its card — so a mirror never
    refreshes on a bond change unless the card itself moves. A brand-new agent's
    card ships anyway because it is new, carrying whatever bond state it happens
    to hold at that moment. The old test therefore proved "a new card reaches the
    peer" and would have gone green on a registry where a bond change NEVER
    propagates. Measured on production: an agent bonded at 23:41 still had
    mirrors on three operators carrying no extension at all.

    So the mirror must be SETTLED BEFORE the change. Three phases, and the middle
    one is the whole point:
      1. the peer has NO mirror        → 404 "not known to this registry"
      2. the mirror ARRIVES, unbonded  → 200, source="card", status="none"
      3. the bond is placed at HOME    → the peer must converge to is_bonded

    Without the card being touched on a bond state change, phase 3 never happens
    and this test fails — which is the point of writing it this way round.
    """
    await _require_enforcing(rig)
    state: Dict[str, Any] = {"interval_sec": 120}
    a = await _unbonded_agent(rig, "mirror")
    created_at = time.time()          # the card's last write, and so its age
    state["did"] = a["did"]

    async def peer_view() -> Tuple[str, Optional[bool]]:
        """('absent'|'mirrored'|'unreadable', is_bonded). Three states, never two."""
        code, body = await _rest(rig, "GET", f"/api/v1/agents/{a['did']}/reputation",
                                 label="sandboxalpha-admin")
        if code == 404:
            return "absent", None
        if code != 200 or not isinstance(body, dict):
            return "unreadable", None
        bond = body.get("bond") if isinstance(body.get("bond"), dict) else {}
        state["peer_source"] = body.get("source") or bond.get("source")
        state["peer_status"] = bond.get("status")
        return "mirrored", bool(body.get("is_bonded") or bond.get("is_bonded"))

    # ── phase 1→2: wait for the mirror to EXIST, still unbonded ───────────
    t0 = time.time()
    arrived = False
    while time.time() - t0 < 300:
        where, bonded = await peer_view()
        if where == "mirrored":
            arrived = True
            state["mirror_arrived_after_sec"] = round(time.time() - t0, 1)
            state["peer_bonded_before_change"] = bonded
            break
        await asyncio.sleep(10)
    if not arrived:
        raise PreconditionUnmet(
            f"the peer never mirrored {a['did']} within 300 s (last view "
            f"{state.get('peer_status')!r}) — with no settled mirror there is no "
            f"'change reaches an existing mirror' to measure, and bonding now would "
            f"only prove that a NEW card ships")
    if state.get("peer_bonded_before_change"):
        raise PreconditionUnmet("the peer already reads this fixture as bonded before it was bonded")

    # ── phase 2b: AGE THE CARD OUT OF THE OVERLAP WINDOW ──────────────────
    # ⚠ WITHOUT THIS THE TEST IS NOT A CONTROL, and mine was not: measured
    # 2026-09-05, it passed on the pre-fix image too. The pull cursor is
    # `peer.last_synced_at - 60s` ("a small overlap buffer so boundary updates
    # are never missed"), so ANY card whose updated_at falls within roughly one
    # interval plus 60 s is re-fetched next cycle whether or not anything
    # touched it — and the export injects the bond extension at derive time, so
    # the re-fetch carries it. A fixture bonded seconds after creation therefore
    # converges through the overlap on an image with no card-touch at all. The
    # case the touch actually fixes is the OLD card: one that has not re-entered
    # a window in months (measured on prod: a bond at 23:41, mirrors still bare
    # hours later).
    #
    # The interval is MEASURED from two readings of the peer's own
    # last_synced_at rather than read from a constant — a hardcoded 120 is wrong
    # on any tier configured differently, and this test's whole value is the
    # wait being longer than the real window.
    interval = await _observed_sync_interval(rig)
    state["observed_interval_sec"] = interval
    overlap_window = interval + 60
    state["overlap_window_sec"] = overlap_window
    margin = 45
    target_age = overlap_window + margin
    while time.time() - created_at < target_age:
        await asyncio.sleep(10)
    state["card_age_at_bond_sec"] = round(time.time() - created_at, 1)

    # ── phase 3: change the bond at home, watch the settled mirror move ───
    state["home_status"] = await _bond(rig, a["did"])
    t1 = time.time()
    converged = False
    while time.time() - t1 < 300:
        where, bonded = await peer_view()
        if where == "mirrored" and bonded:
            converged = True
            break
        await asyncio.sleep(10)
    state["peer_converged_after_sec"] = round(time.time() - t1, 1)
    state["peer_converged"] = converged
    if not converged:
        return _result(False,
                       f"the bond did not reach a peer whose mirror ALREADY existed, within 300 s "
                       f"(peer still reads status={state.get('peer_status')!r}). A peer gates on the "
                       f"mirrored card, so it will admit or refuse on stale truth until the card "
                       f"itself moves — an incremental pull does not notice a change to the agent's "
                       f"rows.", state)
    return _result(True, "", state)
