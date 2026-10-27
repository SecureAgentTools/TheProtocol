"""THE FEDERATION MECHANISMS, DRIVEN ACROSS THE PAIR (§FEDPROOF, moved into the tester on his rule 2026-09-13).

His rule: the production battery stays read-only; every row that leaves a trace lives HERE, where the
tester drives the sandbox on a schedule and its history sits in the console. These are the write rows of
the §FEDPROOF battery (scratchpad/fedproof, 2026-09-13) that no existing suite test drove:

  * a suspension on the home frame reaches the peer's MIRROR within one sync, and lifts (§ENFPROP);
  * an unlisting on the home frame reaches the peer's mirror as a tombstone, and relists (§LISTPROP);
  * one cross-frame settlement moves the private peer-trust counters on BOTH sides (§TRUSTPOLICY);
  * a governance policy change applies at home, moves the card's hash, and the peer READS it as drift;
  * an elevated proposal is decided by registry ballots and passes the registry floor (§MEMBERSHIP D2), two-phase
    across runs because a member-mode registry's ballot is its members' result from an hour-long vote.

Already covered elsewhere and NOT repeated here: the six bond-gate sites (test_reputation_bond_gates),
attenuation (test_ironkey_authority_clamp), the cross-currency crossing with both ledgers
(test_cross_frame_transfer_economic), operator<->frame money (test_operator_money_rails).

Writes, all on the sandbox pair: one or two agents per test per run, tagged `fedsuite-mech-*`; one
suspension and one unlisting that the same test lifts; one dust crossing; one proposal per run (the
governance cycle is shared by its two tests through a lock, so the pair is driven once). The policy row
is restored to what it was and the stake is unstaked. What an agent holds goes back to its frame's treasury
before its delete (throwaways, V0641), except the ballot member's, kept on purpose (_member_voter).

The peer's sync is kicked through POST /federation/sync/trigger, rate-limited to one per 30 s and
(§FEDPROOF finding) carrying no auth dependency; this file calls it through the peer's OWN adminRequest
so the rows do not depend on that gap staying open.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet, ensure_bonded, member_mode, target_switches,
)
from agentvault_registry.api_tests.federation_suite.tests.test_ironkey_authority_clamp import (
    _call, _rest, _detail,
)
from agentvault_registry.api_tests.federation_suite.tests.test_contract_spine_economic import (
    _fund, _num,
)
from agentvault_registry.api_tests.federation_suite.tests.test_cross_frame_transfer_economic import (
    _balance_on, _resolves,
)

_A, _AA, _B, _BA = "sandbox-A", "sandbox-A-admin", "sandbox-B", "sandbox-B-admin"
_REQ = [_A, _AA, _B, _BA]
_CAT = "federation_mechanisms"
_SYNC_GAP = 31.0            # POST /federation/sync/trigger answers 429 inside 30 s of the last one
_SYNC_LAST: Dict[str, float] = {}
_CARD_NAME: Dict[str, str] = {}


# ─── helpers ──────────────────────────────────────────────────────────────────

def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


async def _mint_agent(rig, label: str, tag: str) -> Dict[str, str]:
    """A fresh agent on a NAMED frame, bonded at birth, WITH its secret kept (a role change is
    followed by a re-minted token; the suite's shared `_new_agent` drops the secret)."""
    r, refused = await _call(rig, label, "createAgent", {
        "name": f"fedsuite-mech-{tag}-{uuid.uuid4().hex[:6]}",
        "description": "federation suite: driven mechanism probe (§FEDPROOF)",
    })
    if refused or not isinstance(r, dict):
        raise PreconditionUnmet(f"createAgent on {label} refused for {tag}: {refused}")
    if r.get("error"):
        raise PreconditionUnmet(f"createAgent on {label} error for {tag}: {r['error']}")
    cid = r.get("client_id") or (r.get("credentials") or {}).get("client_id")
    sec = r.get("client_secret") or (r.get("credentials") or {}).get("client_secret")
    did = r.get("did") or r.get("agent_did") or (r.get("agent") or {}).get("did")
    throwaways.made(label, did)  # V0641: retired once its test's verdict is in (throwaways)
    if not (cid and sec and did):
        raise PreconditionUnmet(f"createAgent on {label} returned no credential triple (keys={sorted(r)[:8]})")
    jwt = await _agent_jwt(rig, label, cid, sec, tag)
    await ensure_bonded(rig, label, did)
    return {"did": did, "jwt": jwt, "client_id": cid, "client_secret": sec}


async def _agent_jwt(rig, label: str, cid: str, sec: str, tag: str) -> str:
    t, tref = await _call(rig, label, "getAgentToken", {"client_id": cid, "client_secret": sec})
    if tref or not isinstance(t, dict):
        raise PreconditionUnmet(f"getAgentToken on {label} refused for {tag}: {tref}")
    jwt = t.get("access_token") or t.get("agent_jwt")
    if not jwt:
        raise PreconditionUnmet(f"no agent JWT on {label} for {tag}")
    return jwt


async def _card(rig, admin_label: str) -> Dict[str, Any]:
    st, body = await _rest(rig, "GET", "/.well-known/registry-card.json", label=admin_label)
    return body if (st == 200 and isinstance(body, dict)) else {}


async def _card_name(rig, admin_label: str) -> str:
    """The registry's OWN name, from its signed card (never a container label)."""
    if admin_label not in _CARD_NAME:
        c = await _card(rig, admin_label)
        _CARD_NAME[admin_label] = str((c.get("identity") or {}).get("registry_name") or "")
    return _CARD_NAME[admin_label]


async def _card_hash(rig, admin_label: str) -> str:
    c = await _card(rig, admin_label)
    return str((c.get("federation") or {}).get("policy_hash") or "").replace("sha256:", "")[:16]


async def _sync(rig, admin_label: str, notes: Dict[str, Any]) -> None:
    """Kick the peer's agent-card sync, honouring its one-per-30-s limit."""
    gap = time.time() - _SYNC_LAST.get(admin_label, 0.0)
    if gap < _SYNC_GAP:
        await asyncio.sleep(_SYNC_GAP - gap)
    st, _ = await _rest(rig, "POST", "/api/v1/federation/sync/trigger", label=admin_label,
                        body={"cascade": False})
    _SYNC_LAST[admin_label] = time.time()
    notes["sync_triggers"] = notes.get("sync_triggers", 0) + 1
    notes["last_sync_status"] = st


async def _mirror(rig, admin_label: str, did: str) -> Tuple[int, Any]:
    return await _rest(rig, "GET", f"/api/v1/agent-cards/{did}", label=admin_label)


async def _wait_mirror(rig, admin_label: str, did: str, notes: Dict[str, Any], tries: int = 5) -> bool:
    """The peer learns a fresh native through its sync; trigger it and poll for the mirror."""
    for _ in range(tries):
        await _sync(rig, admin_label, notes)
        st, body = await _mirror(rig, admin_label, did)
        if st == 200 and isinstance(body, dict):
            notes["mirror_present_after_triggers"] = notes.get("sync_triggers")
            return True
        await asyncio.sleep(5)
    return False


async def _enforcement(rig, admin_label: str, did: str) -> Tuple[int, Any, Any, Any]:
    st, body = await _rest(rig, "GET", f"/api/v1/agents/{did}/reputation", label=admin_label)
    e = (body.get("enforcement") or {}) if isinstance(body, dict) else {}
    return st, e.get("status"), e.get("is_enforced"), e.get("source")


async def _peer_trust_rows(rig, admin_label: str) -> Dict[str, Tuple[Any, Any, Any]]:
    st, body = await _rest(rig, "GET", "/api/v1/admin/federation/peer-trust", label=admin_label)
    rows = (body.get("peers") if isinstance(body, dict) else body) or []
    return {str(p.get("name")): (p.get("total_interactions"), p.get("bayesian_discount"),
                                 p.get("verdict") or p.get("state"))
            for p in rows if isinstance(p, dict)}


def _find_row(rows: Dict[str, Any], name: str):
    n = _norm(name)
    for k, v in rows.items():
        if n and (n in _norm(k) or _norm(k) in n):
            return k, v
    return None, None


def _done(passed: bool, description: str, budget: float, t0: float, attempts: int,
          notes: Dict[str, Any], detail: Optional[str]) -> AssertionResult:
    return AssertionResult(passed=passed, description=description, budget_sec=budget,
                           elapsed_sec=time.time() - t0, polling_attempts=attempts,
                           last_state=notes, failure_detail=None if passed else detail)


# ─── 1. enforcement reaches the peer's mirror, and lifts ──────────────────────

@federation_test(
    name="enforcement_state_reaches_the_peer_mirror_within_one_sync_and_lifts",
    category=_CAT, budget_sec=480.0, severity="high", requires=_REQ,
    tags=["federation", "enforcement", "propagation", "peer-mirror", "driven"],
)
async def test_enforcement_propagates(rig: FederationTestRig) -> AssertionResult:
    """§ENFPROP: a bulk suspension touches the CARD, so the peer's next pull carries `is_enforced`;
    the reinstatement lifts it the same way. The single-agent enforcement rail does NOT touch the card
    (measured 2026-09-13), which is why the bulk rail is the one driven here."""
    t0, tag = time.time(), uuid.uuid4().hex[:8]
    notes: Dict[str, Any] = {"tag": tag}
    a = await _mint_agent(rig, _A, f"enf-{tag}")
    notes["did"] = a["did"]
    if not await _wait_mirror(rig, _BA, a["did"], notes):
        raise PreconditionUnmet(
            f"{a['did']} never appeared on sandbox-B after {notes.get('sync_triggers')} sync triggers: "
            f"the propagation leg could not start (the mirror is the peer's, the trigger is honoured)")
    r, refused = await _call(rig, _AA, "bulkSuspendAgents", {
        "agent_dids": [a["did"]],
        "reason": "federation suite: enforcement propagation probe, lifted by the same test"})
    notes["suspend"] = refused or ({k: r.get(k) for k in ("succeeded", "failed") if k in r}
                                   if isinstance(r, dict) else str(r)[:120])
    if refused:
        return _done(False, "the home's bulk suspension was refused", 480.0, t0, 0, notes,
                     f"bulkSuspendAgents: {refused}")
    notes["home_after_suspend"] = await _enforcement(rig, _AA, a["did"])

    async def _peer_enforced() -> bool:
        await _sync(rig, _BA, notes)
        notes["peer_after_suspend"] = await _enforcement(rig, _BA, a["did"])
        return notes["peer_after_suspend"][2] is True

    r1 = await rig.assert_within(budget_sec=170.0, predicate=_peer_enforced,
                                 description="the peer's mirror reads is_enforced after the home's suspension",
                                 poll_interval_sec=_SYNC_GAP, capture_state=lambda: notes)
    r2v, refused2 = await _call(rig, _AA, "bulkReinstateAgents", {
        "agent_dids": [a["did"]], "reason": "federation suite: lift the propagation probe"})
    notes["reinstate"] = refused2 or ({k: r2v.get(k) for k in ("succeeded", "failed") if k in r2v}
                                      if isinstance(r2v, dict) else str(r2v)[:120])

    async def _peer_lifted() -> bool:
        await _sync(rig, _BA, notes)
        notes["peer_after_reinstate"] = await _enforcement(rig, _BA, a["did"])
        st, _s, enforced, _src = notes["peer_after_reinstate"]
        return st == 200 and enforced in (False, None)

    r2 = await rig.assert_within(budget_sec=170.0, predicate=_peer_lifted,
                                 description="the peer's mirror reads not enforced after the home's reinstatement",
                                 poll_interval_sec=_SYNC_GAP, capture_state=lambda: notes)
    legs = []
    if not r1.passed:
        legs.append(f"the peer never read the suspension within {r1.elapsed_sec:.0f}s: {notes.get('peer_after_suspend')}")
    if refused2:
        legs.append(f"bulkReinstateAgents refused: {refused2}")
    if not r2.passed:
        legs.append(f"the peer never lifted within {r2.elapsed_sec:.0f}s: {notes.get('peer_after_reinstate')}")
    return _done(not legs, "a suspension on the home reaches the peer's mirror within one sync, and lifts",
                 480.0, t0, r1.polling_attempts + r2.polling_attempts, notes, "; ".join(legs) or None)


# ─── 2. unlisting reaches the peer's mirror as a tombstone, and relists ───────

@federation_test(
    name="unlisting_reaches_the_peer_mirror_within_one_sync_and_relists",
    category=_CAT, budget_sec=480.0, severity="high", requires=_REQ,
    tags=["federation", "listing", "tombstone", "propagation", "peer-mirror", "driven"],
)
async def test_unlisting_propagates(rig: FederationTestRig) -> AssertionResult:
    """§LISTPROP: the owner's PATCH /agent-cards/{did}/listing {unlisted: true} travels as a tombstone
    the peer applies to its mirror; relisting travels the same way."""
    t0, tag = time.time(), uuid.uuid4().hex[:8]
    notes: Dict[str, Any] = {"tag": tag}
    a = await _mint_agent(rig, _A, f"list-{tag}")
    notes["did"] = a["did"]
    if not await _wait_mirror(rig, _BA, a["did"], notes):
        raise PreconditionUnmet(
            f"{a['did']} never appeared on sandbox-B after {notes.get('sync_triggers')} sync triggers: "
            f"the propagation leg could not start")
    st_u, r_u = await _rest(rig, "PATCH", f"/api/v1/agent-cards/{a['did']}/listing", label=_AA,
                            body={"unlisted": True})
    notes["unlist"] = (st_u, _detail(r_u) if st_u != 200 else "ok")
    if st_u != 200:
        return _done(False, "the home refused the unlisting", 480.0, t0, 0, notes,
                     f"PATCH listing unlisted=true: HTTP {st_u} {_detail(r_u)}")

    async def _peer_unlisted() -> bool:
        await _sync(rig, _BA, notes)
        st, c = await _mirror(rig, _BA, a["did"])
        notes["peer_after_unlist"] = (st, c.get("unlisted") if isinstance(c, dict) else None)
        return notes["peer_after_unlist"][1] is True

    r1 = await rig.assert_within(budget_sec=170.0, predicate=_peer_unlisted,
                                 description="the peer's mirror reads unlisted after the home's unlisting",
                                 poll_interval_sec=_SYNC_GAP, capture_state=lambda: notes)
    st_r, r_r = await _rest(rig, "PATCH", f"/api/v1/agent-cards/{a['did']}/listing", label=_AA,
                            body={"unlisted": False})
    notes["relist"] = (st_r, _detail(r_r) if st_r != 200 else "ok")

    async def _peer_relisted() -> bool:
        await _sync(rig, _BA, notes)
        st, c = await _mirror(rig, _BA, a["did"])
        notes["peer_after_relist"] = (st, c.get("unlisted") if isinstance(c, dict) else None)
        return notes["peer_after_relist"][1] is False

    r2 = await rig.assert_within(budget_sec=170.0, predicate=_peer_relisted,
                                 description="the peer's mirror reads listed again after the home's relisting",
                                 poll_interval_sec=_SYNC_GAP, capture_state=lambda: notes)
    legs = []
    if not r1.passed:
        legs.append(f"the peer never read the tombstone within {r1.elapsed_sec:.0f}s: {notes.get('peer_after_unlist')}")
    if st_r != 200:
        legs.append(f"relist refused: HTTP {st_r} {_detail(r_r)}")
    if not r2.passed:
        legs.append(f"the peer never relisted within {r2.elapsed_sec:.0f}s: {notes.get('peer_after_relist')}")
    return _done(not legs, "an unlisting on the home reaches the peer's mirror within one sync, and relists",
                 480.0, t0, r1.polling_attempts + r2.polling_attempts, notes, "; ".join(legs) or None)


# ─── 3. one settlement moves the peer-trust counters on BOTH sides ────────────

@federation_test(
    name="peer_trust_counters_move_on_both_sides_after_one_settlement",
    category=_CAT, budget_sec=420.0, severity="high", requires=_REQ,
    tags=["federation", "peer-trust", "money", "driven"],
)
async def test_peer_trust_both_sides(rig: FederationTestRig) -> AssertionResult:
    """§TRUSTPOLICY promises every crossing is reported on both frames. Measured 2026-09-13 with the
    §FEDPROOF battery: on the sandbox pair a cross-currency settlement moved ONE side's
    `total_interactions`; on EU/ASIA it moved NEITHER (dust run, his word). The money assertion beside it
    keeps the row honest about whether the crossing itself happened.

    §SUITES1018 (2026-10-18): the row asks whether THIS settlement was counted on each side
    (`GET /admin/federation/peer-trust?settlement_id=`), not whether the counter moved. Every nightly had
    passed it because the AGORA sim's own beta -> alpha settlements moved sbx-beta's counter for Sandbox
    Alpha inside the budget; with the sim stopped it read red, which was the product's real state (the
    receiving frame filed its side of an inbound FX settlement as a third party's: §FEDPROOF F2, fixed in
    V0624 by one name key)."""
    t0, tag = time.time(), uuid.uuid4().hex[:8]
    notes: Dict[str, Any] = {"tag": tag}
    name_a, name_b = await _card_name(rig, _AA), await _card_name(rig, _BA)
    rows_a0, rows_b0 = await _peer_trust_rows(rig, _AA), await _peer_trust_rows(rig, _BA)
    k_a, v_a0 = _find_row(rows_a0, name_b)
    k_b, v_b0 = _find_row(rows_b0, name_a)
    notes.update({"home_row": k_a, "home_before": v_a0, "peer_row": k_b, "peer_before": v_b0})
    if v_a0 is None or v_b0 is None:
        raise PreconditionUnmet(
            f"peer-trust rows are not present on both sides (A holds {sorted(rows_a0)[:6]} and looked for "
            f"{name_b!r}; B holds {sorted(rows_b0)[:6]} and looked for {name_a!r})")
    receiver = await _mint_agent(rig, _B, f"pt-rx-{tag}")          # first: A needs a cycle to learn it
    sender = await _mint_agent(rig, _A, f"pt-tx-{tag}")
    notes["receiver_did"], notes["sender_did"] = receiver["did"], sender["did"]
    if (fref := await _fund(rig, sender["did"], "5.0")):
        raise PreconditionUnmet(f"seed funding refused: {fref}")
    resolved = await rig.assert_within(
        budget_sec=150.0, predicate=lambda: _resolves(rig, receiver["did"]),
        description="frame A resolves the freshly-created frame-B receiver DID", capture_state=lambda: notes)
    if not resolved.passed:
        raise PreconditionUnmet(
            f"frame A could not resolve {receiver['did']} within 150s: a propagation window, not the rail")
    r_before = await _balance_on(rig, _B, receiver["jwt"])
    st, resp = await _rest(rig, "POST", "/api/v1/teg/cross-registry-transfer",
                           body={"receiver_did": receiver["did"], "amount": "1.0",
                                 "message": f"fedsuite peer-trust {tag}"},
                           jwt=sender["jwt"])
    notes["transfer_http"], notes["transfer_response"] = st, json.dumps(resp, default=str)[:240]
    body = json.dumps(resp, default=str)
    if st == 503 and "FX pool: reserve read failed" in body and "404" in body:
        raise PreconditionUnmet("cross-frame FX pool mode needs the peer frame's nginx-teg sidecar, which this "
                                "tier does not provision (absent topology, not a broken rail): " + body[:160])
    if st != 200:
        return _done(False, "the crossing to observe was refused", 420.0, t0, 0, notes,
                     f"cross-registry-transfer HTTP {st}: {body[:220]}")

    sid = str((resp or {}).get("transfer_id") or "") if isinstance(resp, dict) else ""
    notes["settlement_id"] = sid
    if not sid:
        return _done(False, "the crossing named no settlement id to attribute", 420.0, t0, 0, notes,
                     f"cross-registry-transfer answered 200 without a transfer_id: {body[:220]}")

    async def _counted_for(admin_label: str, row: Optional[str]) -> Optional[bool]:
        """True/False: whether this frame's recorder counted THIS settlement for `row`; None: it cannot say."""
        st, b = await _rest(rig, "GET", "/api/v1/admin/federation/peer-trust", label=admin_label,
                            params={"settlement_id": sid})
        s_ = (b or {}).get("settlement") if isinstance(b, dict) else None
        if st != 200 or not isinstance(s_, dict):
            raise PreconditionUnmet(
                f"{admin_label} does not report per-settlement observations (HTTP {st}, no 'settlement' block): "
                f"a counter alone cannot attribute its movement to this settlement")
        if not s_.get("readable"):
            return None
        return row in (s_.get("counted_for") or [])

    async def _both_moved() -> bool:
        notes["receiver_after"] = await _balance_on(rig, _B, receiver["jwt"])
        v_a1 = _find_row(await _peer_trust_rows(rig, _AA), name_b)[1]
        v_b1 = _find_row(await _peer_trust_rows(rig, _BA), name_a)[1]
        notes["home_after"], notes["peer_after"] = v_a1, v_b1
        credited = (notes["receiver_after"] or 0.0) - r_before > 0
        moved_a = bool(v_a1) and _num(v_a1[0]) > _num(v_a0[0])
        moved_b = bool(v_b1) and _num(v_b1[0]) > _num(v_b0[0])
        counted_a, counted_b = await _counted_for(_AA, k_a), await _counted_for(_BA, k_b)
        notes["credited"], notes["home_moved"], notes["peer_moved"] = credited, moved_a, moved_b
        notes["home_counted_this_settlement"], notes["peer_counted_this_settlement"] = counted_a, counted_b
        return credited and moved_a and moved_b and counted_a is True and counted_b is True

    return await rig.assert_within(
        budget_sec=150.0, predicate=_both_moved, poll_interval_sec=10.0,
        description=(f"one A->B settlement credits the receiver AND is counted (this settlement, by id) on "
                     f"{k_a!r} (A's row for B) AND on {k_b!r} (B's row for A)"),
        capture_state=lambda: notes)


# ─── 4 + 5. a governance policy change, the peer's read of it, the elevation floor ──

_GOV_LOCK = asyncio.Lock()
_GOV_CACHE: Dict[str, Any] = {}
_GOV_TTL = 600.0            # both tests of one run share one driven cycle; the next run drives again


async def _policy_cycle(rig) -> Dict[str, Any]:
    async with _GOV_LOCK:
        c = _GOV_CACHE.get("cycle")
        if c and time.time() - c["at"] < _GOV_TTL:
            return c
        c = {"at": time.time(), "notes": {}}
        try:
            await _drive_policy_cycle(rig, c["notes"])
        except PreconditionUnmet as e:
            c["precondition"] = str(e)
        except Exception as e:                                        # noqa: BLE001
            c["error"] = f"{type(e).__name__}: {e}"
        _GOV_CACHE["cycle"] = c
        return c


async def _policy_doc(rig, admin_label: str) -> Dict[str, Any]:
    """The RESOLVED document lives under `policy_json` (the envelope taken for the document read the
    quorum as 0 once: one instrument, two wrong numbers)."""
    st, body = await _rest(rig, "GET", "/api/v1/admin/enforcement/policy/resolved", label=admin_label)
    return (body.get("policy_json") or {}) if (st == 200 and isinstance(body, dict)) else {}


async def _peer_row_for_home(rig, home_admin: str, peer_admin: str) -> Optional[Any]:
    st, ov = await _rest(rig, "GET", "/api/v1/admin/federation/compliance/overview", label=peer_admin)
    name_home = await _card_name(rig, home_admin)
    for p in (ov.get("peers", []) if isinstance(ov, dict) else []):
        if p.get("peer_registry_id") and _find_row({str(p.get("peer_name")): 1}, name_home)[0]:
            return p["peer_registry_id"]
    return None


async def _peer_poll_now(rig, peer_admin: str, pid: Any) -> Tuple[int, Any, Any]:
    st, pn = await _rest(rig, "POST", f"/api/v1/admin/federation/compliance/peers/{pid}/poll-now",
                         label=peer_admin, body={"dry_run_only": True})
    return st, (pn.get("drift_detected") if isinstance(pn, dict) else None), (pn.get("baseline_recorded") if isinstance(pn, dict) else None)


async def _ve_power(rig, admin_label: str) -> float:
    st, s = await _rest(rig, "GET", "/api/v1/governance/stats", label=admin_label)
    return _num((s or {}).get("networkVePower")) if isinstance(s, dict) else 0.0


async def _drive_policy_cycle(rig, n: Dict[str, Any]) -> None:
    # the HOME is the frame whose network ve power one flexible stake (150) can quorum at 20 %; the other is the
    # peer that reads the change. A fixed home skipped both tests on 2026-09-13 (sandbox-A at 730 ve, B within reach).
    powers = {_A: await _ve_power(rig, _AA), _B: await _ve_power(rig, _BA)}
    n["network_ve_power"] = powers
    home = min(powers, key=powers.get)
    # §MCPTEST30 (V0550): where governance weighs membership (GOVERNANCE_WEIGHT_MODE=member, §MEMBERSHIP) the power is
    # the members' points and the proposer's weight its developer's membership, read once the agent exists (below).
    # §MCPTEST30 (V0637): the home is a frame where that developer's own points reach 20 % of the members' points: on
    # 2026-10-24 a sixth member on sandbox-B (607 points) put the lowest-power frame out of one vote's reach (105), and
    # both cycles skipped every night. The points are the developer's that mints the proposer (the frame's own label,
    # getMyMembership); a frame where they reach the quorum wins, the lower power first.
    modes = {f: member_mode(await target_switches(rig, f)) for f in (_A, _B)}
    if any(modes.values()):
        mine: Dict[str, float] = {}
        for f in (_A, _B):
            if modes[f]:
                m, _ref = await _call(rig, f, "getMyMembership", {})
                mine[f] = _num(m.get("points")) if isinstance(m, dict) and m.get("is_member") else 0.0
        n["member_points_by_frame"] = mine
        reach = [f for f in mine if powers[f] * 0.2 <= mine[f]]
        if reach:
            home = min(reach, key=powers.get)
    member = modes[home]
    n["governance_weight_mode"] = "member" if member else "lock"
    if not member and powers[home] * 0.2 > 150.0:
        raise PreconditionUnmet(f"no sandbox frame has a network ve power one flexible stake can quorum "
                                f"({powers}); staking tens of thousands for a probe is a decision")
    HP, HA = (home, home + "-admin")
    PA = (_B if home == _A else _A) + "-admin"
    n.update({"home": home, "peer": PA})
    a = await _mint_agent(rig, HP, "gov")
    n["proposer_did"] = a["did"]
    if (await _balance_on(rig, HP, a["jwt"])) < 160.0:
        st_f, resp_f = await _rest(rig, "POST", "/api/v1/teg/treasury/fund-agent", label=HA,
                                   body={"target_agent_did": a["did"], "amount": "200",
                                         "reason": "federation suite: governance probe proposer"})
        if st_f != 200:
            raise PreconditionUnmet(f"funding the proposer refused: HTTP {st_f} {_detail(resp_f)[:120]}")
    if member:
        st_vp, vp = await _rest(rig, "GET", "/api/v1/governance/voting-power", label=HA, jwt=a["jwt"])
        pts = _num((vp or {}).get("votingPower")) if isinstance(vp, dict) else 0.0
        n["member_points"] = pts
        if not (isinstance(vp, dict) and vp.get("canVote")):
            missing = ((vp or {}).get("membership") or {}).get("missing") if isinstance(vp, dict) else st_vp
            raise PreconditionUnmet(f"not_a_member: governance weighs membership on {HP} and the suite's developer is "
                                    f"not a member (missing {missing}); its agents are bonded from the treasury "
                                    f"backstop, which never makes one")
        if powers[home] * 0.2 > pts:
            raise PreconditionUnmet(f"member_quorum_unreachable: on {HP} one member's vote ({pts:g} points) cannot "
                                    f"reach 20 % of the members' {powers[home]:g} points; the cycle votes once "
                                    f"(the suite developer's points by frame: {n.get('member_points_by_frame')}, the "
                                    f"members' points: {powers})")
        st_s = "member mode: no stake (membership weighs the vote)"
    else:
        st_s, _ = await _rest(rig, "POST", "/api/v1/staking/stake", label=HA, body={"amount": "150", "lock_period": 0}, jwt=a["jwt"])
    st_g, r_g = await _rest(rig, "PUT", f"/api/v1/agents/{a['did']}/authz", label=HA,
                            body={"roles": ["trader", "client", "staker", "governor"]})
    n["stake"], n["governor"] = st_s, (st_g, r_g.get("roles") if isinstance(r_g, dict) else _detail(r_g))
    a["jwt"] = await _agent_jwt(rig, HP, a["client_id"], a["client_secret"], "gov")
    st_r0, row = await _rest(rig, "GET", "/api/v1/admin/enforcement/policy", label=HA)
    row0 = (row.get("policy_json") if isinstance(row, dict) else None) or {}
    doc0 = await _policy_doc(rig, HA)
    cur = _num(((doc0.get("governance") or {}).get("standard_quorum_percent")) or 10)
    new = cur + 1 if cur < 40 else cur - 1
    h0 = await _card_hash(rig, HA)
    n.update({"quorum_before": cur, "quorum_proposed": new, "hash_before": h0})
    # §TESTBED (2026-09-19): the peer's drift reading needs a baseline to drift FROM. On the network's tier the
    # 6-hourly compliance poller has always recorded one; a fresh frame's first poll only records it (measured in a
    # kit sandbox after the change: (200, False, True) = no drift, baseline recorded). Prime it before the change.
    prow0 = await _peer_row_for_home(rig, HA, PA)
    if prow0:
        n["peer_poll_before_change"] = await _peer_poll_now(rig, PA, prow0)
    st_c, prop = await _rest(rig, "POST", "/api/v1/governance/proposals", label=HA, jwt=a["jwt"], body={
        "title": f"federation suite: standard quorum {cur:g} to {new:g} (probe, restored after)",
        "description": "federation suite driven mechanism test: a bounded governance.* policy change, applied "
                       "at home so the peer can read the new hash; the row is restored by the same test.",
        "duration_seconds": 75, "proposal_type": "policy_change",
        "policy_diff": {"governance": {"standard_quorum_percent": new}}})
    if st_c not in (200, 201) or not isinstance(prop, dict):
        n["propose"] = (st_c, _detail(prop))
        return
    pid = prop.get("id")
    n["proposal_id"] = pid
    st_v, vote = await _rest(rig, "POST", f"/api/v1/governance/proposals/{pid}/vote", label=HA, jwt=a["jwt"],
                             body={"vote_in_favor": True, "reason": "federation suite"})
    n["vote"] = (st_v, vote.get("voting_power") if isinstance(vote, dict) else _detail(vote))
    status, tallied = None, False
    t_wait = time.time()
    while time.time() - t_wait < 200:
        await asyncio.sleep(10)
        st_p, pr = await _rest(rig, "GET", f"/api/v1/governance/proposals/{pid}", label=HA)
        status = pr.get("status") if isinstance(pr, dict) else None
        if status and status != "VOTING":
            break
        if time.time() - t_wait > 90 and not tallied:
            st_t, tr = await _rest(rig, "POST", f"/api/v1/governance/proposals/{pid}/tally", label=HA, jwt=a["jwt"], body={})
            n["manual_tally"], tallied = (st_t, _detail(tr)[:100]), True
    n["local_status"] = status
    doc1 = await _policy_doc(rig, HA)
    q1 = _num((doc1.get("governance") or {}).get("standard_quorum_percent"))
    h1 = await _card_hash(rig, HA)
    n.update({"quorum_after": q1, "hash_after": h1})
    n["local_ok"] = (status == "PASSED" and q1 == new and h1 != h0)
    # the peer reads the new hash: poll-now (dry run) on B's row for A
    prow = await _peer_row_for_home(rig, HA, PA)
    n["peer_row_id"] = prow
    n["peer_poll_after_change"] = await _peer_poll_now(rig, PA, prow) if prow else None
    # §MCPTEST30 (V0555): the elevation left this shared cycle for its own two-phase test below. A federation proposal
    # decided by registry ballots is tallied ONCE (the tally is final), so a cycle that elevated and tallied here every
    # run would record FAILED before a peer could cast; the elevation test elevates this run's PASSED local proposal
    # (n["proposal_id"]) only when no ballot cycle is pending.
    # restore the row as it was, and prove the peer reads the baseline again
    st_x, _ = await _rest(rig, "PUT", "/api/v1/admin/enforcement/policy", label=HA,
                          body={"policy_json": row0 or doc0,
                                "reason": "federation suite: restore the policy row after the governance probe"})
    h2 = await _card_hash(rig, HA)
    n["restore"] = (st_x, h2, h2 == h0)
    n["peer_poll_after_restore"] = await _peer_poll_now(rig, PA, prow) if prow else None
    await _rest(rig, "POST", "/api/v1/staking/unstake", label=HA, body={"amount": "150"}, jwt=a["jwt"])


def _cycle_or_skip(c: Dict[str, Any]) -> Optional[AssertionResult]:
    if c.get("precondition"):
        raise PreconditionUnmet(c["precondition"])
    return None


@federation_test(
    name="governance_policy_change_applies_at_home_and_the_peer_reads_the_new_hash",
    category=_CAT, budget_sec=480.0, severity="high", requires=_REQ,
    tags=["federation", "governance", "policy", "compliance", "driven"],
)
async def test_policy_change_and_peer_read(rig: FederationTestRig) -> AssertionResult:
    """§FRAMEPOLICY end to end: a governor stakes, proposes a bounded `governance.*` change, votes, the
    auto-tally applies it, the resolved document and the card's hash move, and the PEER's dry-run poll
    reads the change as drift; the row is then restored and the peer reads the baseline again."""
    t0 = time.time()
    c = await _policy_cycle(rig)
    _cycle_or_skip(c)
    n = c["notes"]
    if c.get("error"):
        return _done(False, "the governance cycle could not be driven", 480.0, t0, 0, n, c["error"])
    peer_drift = (n.get("peer_poll_after_change") or (None, None, None))[1] is True
    restored = bool(n.get("restore")) and n["restore"][2] is True
    legs = []
    if not n.get("local_ok"):
        legs.append(f"local cycle: status {n.get('local_status')}, quorum {n.get('quorum_before')}->{n.get('quorum_after')} "
                    f"(proposed {n.get('quorum_proposed')}), hash {n.get('hash_before')}->{n.get('hash_after')}, propose={n.get('propose')}")
    if not peer_drift:
        legs.append(f"the peer's dry-run poll did not read the change as drift: {n.get('peer_poll_after_change')}")
    if not restored:
        legs.append(f"the policy row was not restored to its hash: {n.get('restore')}")
    return _done(not legs, "a policy change applies at home, moves the card's hash, the peer reads it, and the row is restored",
                 480.0, t0, 0, n, "; ".join(legs) or None)


# ─── 5. the cross-frame half: an elevated proposal decided by registry ballots ────────
#
# §MCPTEST30 (V0555, 2026-10-03; his word: "check if you can fix cross frame governance now that we already worked on
# the voting. it was broken"). §FEDPROOF F7 measured the gap: an elevated proposal lived in the HOME's store, the peer
# tallied its own store (400 "Federation proposal not found"), so the two-registry floor was unreachable by
# construction. §MEMBERSHIP D2 (agentvault2-33) closes it: where FEDERATION_BALLOT_MODE=on a federation proposal is
# decided by REGISTRIES, one signed ballot each, delivered over the federation mTLS lane to the host, which alone writes
# it. A member-mode registry's ballot is its members' result from a local vote of at least an hour (product timing, not
# shortened for a test), so the row is TWO-PHASE and keeps no state of its own: the host's list of open ballot proposals
# is the record (agentvault2-33's spec, 2026-10-03):
#   FINISH, every run, first: the oldest open "federation suite:" proposal at the home that the peer has not cast in.
#     The peer casts (its members decide), the home casts (its operator's choice: it has no members), the home tallies
#     ONCE. GREEN when it PASSED with at least the registry floor of ballots, the peer's decided by its members' vote.
#   START, when no cycle is pending: this run's PASSED local proposal is elevated for two days (a daily nightly finishes
#     it), the peer opens its members' vote (one hour) and one member votes in it. The row reads NOT MEASURED until a
#     later run finishes the cycle.
# The tally is never asked before both ballots are in, nothing is vetoed (a veto rewrites the status), and a PASSED
# proposal is applied by auto-tally after its 7-day veto window: one FederationPolicyUpdated on the sandbox, whose only
# consumer re-polls compliance (no registry's policy changes).
_TITLE = "federation suite:"
_BALLOT_SECONDS = 172800        # the route allows 3600..2592000; two days lets the next daily run finish the cycle
_LOCAL_VOTE_SECONDS = 3600      # the members' vote's floor (LocalVoteIn: ge=3600)


def _suite_proposals(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The suite's open ballot proposals at one host, oldest first."""
    ps = [p for p in (entry.get("proposals") or []) if isinstance(p, dict)
          and str(p.get("title") or "").startswith(_TITLE)]
    return sorted(ps, key=lambda p: str(p.get("end_timestamp") or ""))


async def _ballot_view(rig, admin_label: str) -> Tuple[int, Dict[str, Any]]:
    st, doc = await _rest(rig, "GET", "/api/v1/governance/federation-ballots", label=admin_label)
    return st, (doc if isinstance(doc, dict) else {})


async def _home_entry(rig, peer_admin: str, home_admin: str, n: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The home's entry in the PEER's view of open ballot proposals, which names the host as the peer's row does."""
    st, doc = await _ballot_view(rig, peer_admin)
    n["peer_view"] = st
    name_home = await _card_name(rig, home_admin)
    for h in doc.get("hosts") or []:
        if isinstance(h, dict) and h.get("host") != "self" and _find_row({str(h.get("name")): 1}, name_home)[0]:
            n["peer_names_home"] = h.get("host")
            if h.get("error"):
                n["peer_view_error"] = h.get("error")
            return h
    return None


async def _member_voter(rig, peer: str, n: Dict[str, Any]) -> Dict[str, str]:
    """An agent of the suite's developer on the PEER that votes as a member. Membership is the developer's (one member,
    one vote): a fresh agent speaks for a developer that already is a member; otherwise this agent is funded and bonds
    from its OWN wallet (a treasury backstop bond never makes a member; on the sandbox a bond counts at once). So the
    first run bonds once and every later run bonds nothing (each bond locks 250)."""
    pa = peer + "-admin"
    r, refused = await _call(rig, peer, "createAgent", {
        "name": f"fedsuite-mech-ballot-{uuid.uuid4().hex[:6]}",
        "description": "federation suite: a member's voice in a federal ballot (§MEMBERSHIP D2)",
    })
    if refused or not isinstance(r, dict) or r.get("error"):
        raise PreconditionUnmet(f"createAgent on {peer} refused for the ballot voter: {refused or r}")
    cid = r.get("client_id") or (r.get("credentials") or {}).get("client_id")
    sec = r.get("client_secret") or (r.get("credentials") or {}).get("client_secret")
    did = r.get("did") or r.get("agent_did") or (r.get("agent") or {}).get("did")
    if not (cid and sec and did):
        raise PreconditionUnmet(f"createAgent on {peer} returned no credential triple for the ballot voter")
    # gov.vote lives in the governor role under IRONKEY enforce; the one-role rail (V0551+) adds it and touches no other
    # grant (a PUT of the whole list would write today's birth roles into the test; agentvault2-33's review)
    st_g, r_g = await _rest(rig, "POST", f"/api/v1/agents/{did}/authz/roles", label=pa, body={"role": "governor"})
    n["voter"] = {"did": did, "governor": (st_g, r_g.get("roles") if isinstance(r_g, dict) else _detail(r_g))}
    jwt = await _agent_jwt(rig, peer, cid, sec, "ballot")          # re-minted after the role change
    st_vp, vp = await _rest(rig, "GET", "/api/v1/governance/voting-power", label=pa, jwt=jwt)
    if not (isinstance(vp, dict) and vp.get("canVote")):
        st_f, rf = await _rest(rig, "POST", "/api/v1/teg/treasury/fund-agent", label=pa, body={
            "target_agent_did": did, "amount": "300", "reason": "federation suite: the ballot member's own bond"})
        st_b, rb = await _rest(rig, "POST", f"/api/v1/developers/me/agents/{did}/reputation-bond", label=pa,
                               body={"funder_did": did})
        n["voter"]["self_bond"] = (st_f, st_b, rb.get("status") if isinstance(rb, dict) else _detail(rb))
        st_vp, vp = await _rest(rig, "GET", "/api/v1/governance/voting-power", label=pa, jwt=jwt)
    if not (isinstance(vp, dict) and vp.get("canVote")):
        missing = ((vp or {}).get("membership") or {}).get("missing") if isinstance(vp, dict) else st_vp
        raise PreconditionUnmet(f"not_a_member: the suite's developer on {peer} is not a member after a self-funded "
                                f"bond (missing {missing}); its members' vote would have no voice")
    n["voter"]["points"] = vp.get("votingPower")
    return {"did": did, "jwt": jwt}


async def _open_members_vote(rig, host_name: str, fid: str, peer: str, n: Dict[str, Any],
                             key: str = "members_vote") -> str:
    """At `peer` (the peer, or the home with host "self"): open the members' vote that decides that registry's ballot
    on `fid`, and one member votes for."""
    pa = peer + "-admin"
    st_l, lv = await _rest(rig, "POST", "/api/v1/admin/federation/ballots/local-vote", label=pa,
                           body={"host": host_name, "proposal_id": fid, "duration_seconds": _LOCAL_VOTE_SECONDS})
    if st_l != 201 or not isinstance(lv, dict) or not lv.get("local_proposal_id"):
        err = lv.get("error") if isinstance(lv, dict) else None
        return f"{fid}: the members' vote at {peer} was not opened (HTTP {st_l} {err or _detail(lv)[:120]})"
    lid, ends = lv["local_proposal_id"], lv.get("ends_at")
    voter = await _member_voter(rig, peer, n)
    st_v, v = await _rest(rig, "POST", f"/api/v1/governance/proposals/{lid}/vote", label=pa, jwt=voter["jwt"],
                          body={"vote_in_favor": True, "reason": "federation suite: a member's vote in a federal ballot"})
    n[key] = {"local_proposal_id": lid, "ends_at": ends,
              "vote": (st_v, v.get("voting_power") if isinstance(v, dict) else _detail(v)[:120])}
    return f"{fid} at the home; the members' vote {lid} at {peer} closes {ends} (a member voted: HTTP {st_v})"


async def _start_cycle(rig, cn: Dict[str, Any], home_admin: str, peer: str, host_name: str,
                       peer_member: bool, n: Dict[str, Any], home: str = "", home_member: bool = False) -> str:
    """Elevate this run's PASSED local proposal as a ballot proposal and, at each registry that counts members (the
    peer, and the home too), open their vote: a registry with members casts its members' result, never its operator's
    choice (409 members_must_vote; the home was red on that 2026-10-06, sandbox-B counting members)."""
    pid = cn.get("proposal_id")
    if cn.get("local_status") != "PASSED" or not pid:
        return f"not started: this run's local proposal {pid} is {cn.get('local_status')}, not PASSED"
    st_e, fed = await _rest(rig, "POST", "/api/v1/governance/federation/propose", label=home_admin,
                            body={"local_proposal_id": pid, "duration_seconds": _BALLOT_SECONDS})
    fid = (fed.get("id") or fed.get("proposal_id")) if isinstance(fed, dict) else None
    n["elevate"] = (st_e, fid or _detail(fed)[:120], fed.get("ballot_mode") if isinstance(fed, dict) else None)
    if st_e not in (200, 201) or not fid:
        return f"not started: the elevation answered HTTP {st_e} {_detail(fed)[:120]}"
    if not fed.get("ballot_mode"):
        return f"not started: {fid} was elevated as an agents' proposal (no ballot mode at the home)"
    said = []
    if home_member:
        said.append("the home's members' vote: "
                    + await _open_members_vote(rig, "self", str(fid), home, n, key="home_members_vote"))
    if not peer_member:
        said.append(f"{fid} at the home; {peer} has no members, so its operator casts in the next run")
    else:
        said.append(await _open_members_vote(rig, host_name, str(fid), peer, n))
    return "; ".join(said)


@federation_test(
    name="federation_elevation_reaches_the_peer_floor",
    category=_CAT, budget_sec=900.0, severity="medium", requires=_REQ,
    tags=["federation", "governance", "elevation", "ballots", "structural", "driven"],
)
async def test_elevation_reaches_the_peer_floor(rig: FederationTestRig) -> AssertionResult:
    """The cross-frame half of governance, by registry ballots (§MEMBERSHIP D2). Red from 2026-09-13 to V0555 as
    §FEDPROOF F7 (FINDINGS_2026-09-13_FEDPROOF.md): the elevated proposal lived in the home's store and the peer tallied
    its own. Two-phase across runs (the comment above the helpers): a run FINISHES the oldest cycle the peer has not
    cast in, then STARTS one when none is pending."""
    t0 = time.time()
    c = await _policy_cycle(rig)
    _cycle_or_skip(c)
    cn = c["notes"]
    if c.get("error"):
        return _done(False, "the governance cycle could not be driven", 900.0, t0, 0, dict(cn), c["error"])
    home, pa = cn.get("home"), cn.get("peer")
    if not home or not pa:
        raise PreconditionUnmet("the governance cycle named no home and peer")
    ha, peer = home + "-admin", pa[:-len("-admin")]
    n: Dict[str, Any] = {"home": home, "peer": peer, "local_proposal": (cn.get("proposal_id"), cn.get("local_status"))}
    modes = {"home": (await _ballot_view(rig, ha))[1].get("ballot_mode"),
             "peer": (await _ballot_view(rig, pa))[1].get("ballot_mode")}
    n["ballot_mode"] = modes
    if modes["home"] is not True or modes["peer"] is not True:
        raise PreconditionUnmet(f"switched_off: federal ballots (FEDERATION_BALLOT_MODE) are not on at both frames "
                                f"({modes}); without them a peer cannot vote on a proposal elevated elsewhere "
                                f"(§FEDPROOF F7, FINDINGS_2026-09-13_FEDPROOF.md)")
    peer_member = member_mode(await target_switches(rig, peer))
    n["peer_member_mode"] = peer_member
    home_member = member_mode(await target_switches(rig, home))
    n["home_member_mode"] = home_member
    entry = await _home_entry(rig, pa, ha, n)
    if entry is None:
        return _done(False, "the peer lists the home's open ballot proposals", 900.0, t0, 0, n,
                     f"{peer}'s view of open ballot proposals (HTTP {n.get('peer_view')}) names no entry for the home")
    open_ = _suite_proposals(entry)
    pending = [p for p in open_ if p.get("cast_here") is False]
    n["open_suite_proposals"] = [(str(p.get("id")), p.get("cast_here"), p.get("end_timestamp")) for p in open_][:6]
    verdict: Optional[bool] = None
    detail: Optional[str] = None
    if pending:
        fid = str(pending[0].get("id"))
        f: Dict[str, Any] = {"proposal_id": fid}
        n["finish"] = f
        body = {"host": entry.get("host"), "proposal_id": fid}
        if not peer_member:
            body["choice"] = "for"              # a registry without members: its operator's choice is the ballot
        st_c, cast = await _rest(rig, "POST", "/api/v1/admin/federation/ballots", label=pa, body=body)
        err = cast.get("error") if isinstance(cast, dict) else None
        f["peer_cast"] = (st_c, err or (cast.get("choice") if isinstance(cast, dict) else _detail(cast)[:120]))
        if st_c == 409 and err == "local_vote_open":
            raise PreconditionUnmet(f"cycle_pending: the members' vote at {peer} on {fid} closes at "
                                    f"{cast.get('ends_at')}; a run after that casts both ballots and tallies")
        if st_c == 409 and err == "members_must_vote":
            started = await _open_members_vote(rig, str(entry.get("host")), fid, peer, n)
            raise PreconditionUnmet(f"cycle_pending: no members' vote was open for {fid}, now: {started}")
        if st_c != 201 or not (isinstance(cast, dict) and cast.get("recorded")):
            return _done(False, "the peer registry casts its ballot", 900.0, t0, 0, n,
                         f"the peer's ballot on {fid} was refused: HTTP {st_c} {json.dumps(cast, default=str)[:240]}")
        basis = cast.get("basis") if isinstance(cast.get("basis"), dict) else {}
        f["peer_basis"] = basis
        home_body = {"host": "self", "proposal_id": fid}
        if not home_member:
            home_body["choice"] = "for"         # a home without members: its operator's choice is its ballot
        st_h, own = await _rest(rig, "POST", "/api/v1/admin/federation/ballots", label=ha, body=home_body)
        herr = own.get("error") if isinstance(own, dict) else None
        f["home_cast"] = (st_h, (herr or own.get("choice")) if isinstance(own, dict) else _detail(own)[:120])
        if home_member and st_h == 409 and herr in ("members_must_vote", "local_vote_open"):
            # a cycle begun before the home's members voted (or whose vote is still open) cannot be finished here:
            # not a refusal of the product; a fresh cycle (both members' votes) is started below
            f["home_pending"] = herr
    if pending and (n.get("finish") or {}).get("home_pending"):
        verdict = None
    elif pending:
        st_t, tally = await _rest(rig, "POST", f"/api/v1/governance/federation/proposals/{fid}/tally", label=ha, body={})
        row = ({k: tally.get(k) for k in ("ballot_mode", "status", "cast", "eligible", "for", "against", "abstain",
                                          "quorum_met", "participation_met", "multi_registry_met", "two_thirds_met",
                                          "not_counted")}
               if isinstance(tally, dict) else {"answer": _detail(tally)[:160]})
        f["tally"] = (st_t, row)
        by_members = (basis.get("mode") == "members" and int(basis.get("voters") or 0) >= 1) if peer_member else True
        home_basis = own.get("basis") if isinstance(own, dict) and isinstance(own.get("basis"), dict) else {}
        home_by_members = home_basis.get("mode") == "members" if home_member else True
        verdict = (st_t == 200 and row.get("ballot_mode") is True and row.get("status") == "PASSED"
                   and row.get("multi_registry_met") is True and int(row.get("cast") or 0) >= 2 and by_members
                   and home_by_members)
        if not verdict:
            detail = (f"proposal {fid}: the peer's ballot {f['peer_cast']} on basis {basis}, the home's {f['home_cast']}, "
                      f"the tally {f['tally']}" + ("" if by_members else "; the peer's ballot was not its members' result")
                      + ("" if home_by_members else "; the home's ballot was not its members' result"))
    if len(pending) <= 1:                       # the oldest was finished just now, or none was pending
        n["start"] = await _start_cycle(rig, cn, ha, peer, str(entry.get("host")), peer_member, n,
                                        home=home, home_member=home_member)
    if verdict is None:
        hp = (n.get("finish") or {}).get("home_pending")
        if hp:
            raise PreconditionUnmet(f"cycle_pending: the home counts members and {n['finish']['proposal_id']} has no "
                                    f"closed members' vote there ({hp}; a cycle begun before the home's members voted); "
                                    f"{n.get('start')}")
        raise PreconditionUnmet(f"cycle_started: {n.get('start')}; a later run casts the two ballots and tallies")
    return _done(verdict, "an elevated proposal is decided by registry ballots: the peer's (its members' result) and "
                          "the home's are counted and it passes the registry floor", 900.0, t0, 0, n, detail)
