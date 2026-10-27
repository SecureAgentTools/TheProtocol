"""Skip taxonomy (U2) — turning free text into something a gate can read.

WHY. This suite carried 23 skips that nobody had read. Two of them were live
defects wearing a skip: a money rail that answers 200 and never credits the
receiver, and an FX capability absent from every cloud operator. They surfaced
only because someone sat down and read eleven paragraphs of prose by hand.

A pass FLOOR cannot see a test that vanishes into "skipped" — that rule is
already doctrine here, and this suite was not obeying it. So: every skip must
name a KNOWN reason. An `unclassified` skip is a gate failure, not because the
skip is wrong but because nobody has read it yet, which is exactly the state the
23 were in.

The codes below were derived from the skip reasons the suite actually emitted on
2026-09-05 (`runs/fedsuite4_final_94d6273f4cca.json`), not from imagination.
Adding a code is a deliberate act: it says a human read this class and decided
the environment, not the product, is what cannot supply the condition.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# code → (compiled pattern, one-line meaning). Order matters: first match wins.
_PATTERNS: List[Tuple[str, "re.Pattern[str]", str]] = [
    (
        "transport_lost",
        re.compile(r"^transport lost: |were lost in transit during this test", re.I),
        "an answer was lost in transit during the test (the exec came back rc 0 with no HTTP status marker, which curl "
        "never produces itself): the test measured the transport, not the product. Capped per run, so a transport "
        "that fails more than now and then fails the run instead of hiding in skips",
    ),
    (
        # §MCPTEST30 (V0549): the decorator's own verdict on a PASS whose every leg was silent (an error text or an
        # empty answer, which 111 predicates accept): the row measured no answer. Ratcheted below.
        "unanswered",
        re.compile(r"^unanswered: every leg answered an error or nothing", re.I),
        "every leg of the row answered an error or nothing, which its test accepts as a pass (a surface that may be "
        "off on a node): the row measured no answer. The census may only shrink as rows learn to measure",
    ),
    (
        # §MCPTEST30 (V0550): the target switched the row's subject off and says so in its registry-config
        "switched_off",
        re.compile(r"^switched_off: ", re.I),
        "the target switched the row's subject off (its registry-config says so: staking, rewards, AGORA "
        "distributions): nothing can be produced there to measure, so the row is NOT MEASURED, never a pass",
    ),
    (
        # §MCPTEST30 (V0550): governance weighs membership on the target and the suite's developer is not a member
        "not_a_member",
        re.compile(r"^not_a_member: |\bnot_a_member:", re.I),
        "governance weighs membership on the target (GOVERNANCE_WEIGHT_MODE=member) and the suite's developer is not a "
        "member: its fixtures are bonded from the treasury backstop, which never makes one, so the row can neither "
        "propose nor vote. A member fixture of its own is the fix",
    ),
    (
        # §MCPTEST30 (V0550): one member's vote cannot carry the quorum the policy cycle needs
        "member_quorum_unreachable",
        re.compile(r"^member_quorum_unreachable: ", re.I),
        "governance weighs membership on the target and one member's vote cannot reach the quorum the policy cycle "
        "needs (one vote per member; the suite votes with one): driving several members is the fix",
    ),
    (
        "canary_unprovisioned",
        re.compile(r"NO canary paths configured|total_paths=0", re.I),
        "the tier deliberately runs no canary paths (they dispatch real currency)",
    ),
    (
        "canary_no_firings",
        re.compile(r"no canary firings in the .* window|pass RATE has no denominator", re.I),
        "canary fleet stopped: a rate with no denominator is not measurable",
    ),
    (
        # §SBXFXROUTE 2026-09-06 — the route RAN and did not complete, which is a
        # different fact from "no booth is configured" and deserves its own name.
        # Its commonest cause is benign and self-clearing: the receiver was created
        # seconds earlier and its card has not reached the GATEWAY (the sender's
        # parent frame), which is the node that must resolve the DID to deliver the
        # egress. `_drive` now retries this 3 times with a nudge; reaching this code
        # means it did not clear, and the parent frame's [FX-ROUTE] log lines are the
        # only place propagation and a broken leg separate.
        "operator_fx_route_unsettled",
        re.compile(r"FX route did not settle", re.I),
        "the operator's cross-currency route ran and did not complete in the retries "
        "(commonest cause: the receiver's card had not reached the gateway frame yet); "
        "each attempt's ingress is parked at the gateway's @fx_router",
    ),
    (
        # §CANARYSCOPE 2026-09-07 — the judge's 24h summary is PROMETHEUS-sourced
        # and therefore FLEET-wide, while `per_path`/`active_paths` are this
        # frame's. On a frame that runs no canary paths the rate belongs to
        # production (measured: 1418 cycles, 59.3 % here, with this frame's
        # `canary_test_results` table holding 0 rows, ever). Judging it would
        # report another node's health as this one's, so the test refuses — and
        # the refusal needs a NAME or it lands in `unclassified`, which is the
        # census saying "I do not know" about something we know exactly.
        "canary_judge_not_this_frames_paths",
        re.compile(r"runs NO canary paths of its own", re.I),
        "the frame runs no canary paths, so the judge's 24h pass rate here is the "
        "FLEET's (Prometheus-sourced) rather than this frame's — not measurable "
        "locally, and not a defect. Run it where the paths live",
    ),
    (
        # §FXREFUND 2026-09-06 — THE THIRD SHAPE, and the only clean one. This rail
        # produces three outcomes and the suite could name two: it settles; it runs
        # and does not settle (above); or the INGRESS itself is refused before any
        # value moves. The third arrived as `unclassified`, which says nothing —
        # about the outcome that says the most. "No funds moved" is the fact that
        # distinguishes it: there is no residue at the gateway's @fx_router and no
        # phantom FxRouteRefunded in the ledger, so this failure costs nothing and
        # needs no sweep. It trades with `operator_fx_route_unsettled` the way
        # `operator_fx_disabled` trades with `operator_treasury_unfundable`: which
        # one a direction produces depends on whether the sender was funded and on
        # whether the receiver's card had reached the gateway, so the pair's SUM is
        # the stable quantity and each ceiling is 2 (the two directions).
        "operator_fx_route_ingress_refused",
        re.compile(r"ingress was refused before any funds moved|"
                   r"FX route ingress failed \(no funds moved\)", re.I),
        "the operator's cross-currency ingress leg was refused BEFORE any funds "
        "moved, so nothing is parked at the gateway's @fx_router. The leg's own "
        "status is the reason: 402 = the sender holds no balance; a 4xx from the "
        "target TEG = a posture on the GATEWAY's TEG (bond, allowlist, suspension), "
        "readable in that TEG's log and nowhere else",
    ),
    (
        # §FXROUTEWAIT 2026-09-06 — THE WAIT'S OWN OUTCOME, and the cheapest of
        # the four. The drive no longer discovers a missing card by SPENDING: it
        # asks the delivering frame (the sender's PARENT — an operator holds no
        # reserves and ingresses to its parent's @fx_router) whether it has the
        # receiver's card, through one bounded index-feed cursor read, BEFORE any
        # money moves. Reaching this code means the card never arrived inside the
        # wait, and nothing was spent finding that out.
        #
        # MEASURED on this tier 2026-09-06: an operator-homed card becomes
        # resolvable on one peer frame after 58 s and on the other after 166 s —
        # same code, same pair, ~3x apart. So a run that lands here is asking a
        # federation-sync question (how long is a cycle, and what phase is it
        # in), never a money one. The predecessor of this code was four money
        # attempts that reported "did not settle" and left the sender SHORT BY
        # 8.0 per direction.
        "operator_fx_route_card_not_propagated",
        re.compile(r"never reached its delivering frame", re.I),
        "the receiver's card had not reached the frame that must DELIVER it "
        "before the wait ran out, so the cross-currency route was never "
        "attempted and NO FUNDS MOVED. Nothing is parked; this is a "
        "federation-sync timing question (measured 58 s one direction and 166 s "
        "the other on this tier), and the fix is a longer wait or a faster sync, "
        "never more money attempts",
    ),
    (
        "operator_fx_disabled",
        re.compile(r"FX_ENABLED=false|no FX booth configured|FX swap booth", re.I),
        # §SBXFXROUTE 2026-09-06 — the old meaning ("cloud operators ship FX_ENABLED
        # unset") named a true fact and the wrong mechanism, so it read as a dead end
        # when it was a configuration gap. An operator holds no reserves and is never
        # meant to: it ROUTES, ingressing 1:1 to its parent frame's @fx_router and
        # letting the parent convert (`FX_ROUTE_ENABLED` + `FX_ROUTE_GATEWAY_*`).
        # Enabling it on this tier took four things, each measured: the parent needs an
        # @fx_router agent and FX_ROUTER_DID; the operator's gateway must name its OWN
        # parent (the provisioner handed every non-cluster frame's operators PRODUCTION
        # Frame A's identity); the parent's federation vhost must serve
        # /api/v1/teg/fx/route-hop (the frame TEMPLATE never had that location, so the
        # delegated hop died on nginx's own 404); and the peer entry must carry
        # `registry_id`, `router_did` and the peer's mTLS address, or the egress leg
        # dials a plain URL where no SVID is presented and reads 401.
        "cross-currency from an operator needs its PARENT's FX route: the parent's "
        "@fx_router + FX_ROUTER_DID, a gateway naming that parent, route-hop served on "
        "the parent's federation vhost, and a peer entry with registry_id/router_did/"
        "mTLS url (proven on this tier 2026-09-06: 3 SBXA -> 2.951249 SBXB, delta 0 both)",
    ),
    (
        "topology_missing",
        re.compile(r"not in topology map", re.I),
        "a registry this test needs is absent from the topology map",
    ),
    (
        # §EVTYPES4 2026-09-06 — READ, then classified. Two rows skipped with
        # "cannot seed the sender on sandboxalpha: HTTP 400 Treasury transfer
        # failed: {"status":"exhausted", ... "funded_amount":"0"}". A cloud
        # §EVTYPES8 2026-09-06 — THE CODE STAYS, ITS CAUSE CHANGED, AND THE OLD
        # MEANING WOULD NOW SEND A READER TO THE WRONG PLACE. This used to say
        # the treasury "CANNOT be seeded" because cross-TEG funding refused any
        # frame whose SPIFFE id was not /service/registry-* or /service/teg-*
        # (backlog B8). That coupling is FIXED: R51 widened
        # is_internal_service_identity to accept '<name>-registry', and both
        # sandbox operators were seeded through that exact rail on his word —
        # first call, HTTP 200, Δ=0 on both stores. The prediction the old note
        # made came true in the same run: this code went 3 → 0.
        #
        # It is kept because the STATE it names recurs: the seed is spent by the
        # sweeps (measured ~27,250 per run against a 100,000 seed), so a tier
        # left alone for a few days is back at 0. What changed is that the cause
        # is now "nobody has topped it up lately", not "the rail refuses us" —
        # and the remedy is one call, named in the meaning so the next reader
        # does not re-derive it.
        "operator_treasury_unfundable",
        re.compile(r'"status"\s*:\s*"exhausted"|cannot seed the sender', re.I),
        "a cloud-op treasury is 0, so money-dependent fixtures cannot be created "
        "there. Seedable in one call: POST /api/v1/teg/treasury/cross-teg-fund on "
        "the PARENT with {target_registry: <op slug>, amount, reason: "
        "'liquidity_provision'} — the sweeps spend roughly 27,250 a run, so this "
        "recurs and is a top-up, not a blocker",
    ),
    (
        "fixture_absent",
        re.compile(r"fixture .* (absent|missing)|no such (agent|developer|container)", re.I),
        "a named fixture this test reads does not exist on the tier",
    ),
]

# What the run is allowed to carry, and how many of each, before the gate speaks.
# Set from the 2026-09-05 baseline: 8 + 1 + 2 = 11.
BASELINE_SKIPS: Dict[str, int] = {
    "transport_lost": 3,          # §MCPSWEEP 2026-09-28: at most 3 in a run seen so far (V0478, after five recreates)
    # §MCPTEST30 (V0549): rows that passed on silence alone. Measured on sbx-alpha (V0547) 2026-10-02 by running the 112
    # tests that accept a silent leg: 2 (operator_portal_self_status_per_cloudop and operator_lifecycle_per_cloudop_self_view,
    # 503 and 404 on both operators: the tools serve an operator's applicant on its PARENT); a third,
    # cloud_op_self_logs_per_cloudop, read the operator's real path in V0549 instead
    "unanswered": 2,
    # §MCPTEST30 (V0550): structural caps, by the rows that can produce each on a member-mode sandbox with staking off:
    # events_tokens_staked_is_evented (staking off); the governance event row and the two policy-cycle rows (not a
    # member, or one member's vote short of the quorum; the two policy rows share one cycle, so they skip together)
    "switched_off": 1,
    "not_a_member": 3,
    "member_quorum_unreachable": 2,
    "canary_unprovisioned": 8,
    "canary_no_firings": 1,
    # §EVTYPES4/7 2026-09-06: measured 2, then 1, then 0 across three runs while
    # `operator_treasury_unfundable` rose 1 -> 2 -> 3. They trade (see the note
    # on that code); the sum held at 3. A SHRINK is never a complaint, so a
    # ceiling above the current count costs nothing.
    # Two rows can reach it (the two cross-cloud-op directions). A ceiling of 2
    # is the honest cap: a third would mean a row nobody has accounted for.
    "operator_fx_route_unsettled": 2,
    # §FXREFUND 2026-09-06 — see the note on the code. Two rows can reach it (the
    # two cross-cloud-op directions) and it trades with the line above, so 2 is the
    # honest cap: a third would mean a row nobody has accounted for.
    # §CANARYSCOPE — ONE test can produce it, so a second would mean a row nobody
    # has accounted for.
    "canary_judge_not_this_frames_paths": 1,
    "operator_fx_route_ingress_refused": 2,
    # §FXROUTEWAIT 2026-09-06 — the wait's own outcome. Two rows can reach it
    # (the two cross-cloud-op directions) and it TRADES with the two codes above:
    # which of the three a direction produces depends on whether the card
    # arrived, whether the sender was funded, and what the gateway's TEG said. So
    # the stable quantity is the SUM across the three, and 2 each is the honest
    # cap — a third would mean a row nobody has accounted for.
    "operator_fx_route_card_not_propagated": 2,
    "operator_fx_disabled": 3,
    "topology_missing": 0,
    "fixture_absent": 0,
    # This code and `operator_fx_disabled` TRADE: a cross-currency test skips as
    # "no FX booth" when it gets that far and as "cannot seed the sender" when the
    # seeding is attempted first, so which one fires depends on ordering. Measured
    # across three runs an hour apart: fx 2 + treasury 1, fx 1 + treasury 2, fx 0 +
    # treasury 3 — the SUM held at 3 every time, so the ceiling is really on the
    # sum and is expressed as a ceiling on each.
    #
    # §EVTYPES8 2026-09-06, AFTER THE OPERATORS WERE FUNDED: fx 2 + treasury 0, and
    # the sum DROPPED to 2 — one of the three became a PASS (546 → 548 across the
    # afternoon). The ceilings stay at 3 deliberately: a shrink is never a
    # complaint, the pair still trades, and the treasury code returns whenever the
    # seed is spent. Tightening to today's 0 would buy a red run the first time a
    # sweep drains the operator, which is how a gate earns the right to be ignored.
    "operator_treasury_unfundable": 3,
}

# ─── Codes that TRADE, and the ceiling that actually binds them ─────────────
#
# Several codes describe DIFFERENT OUTCOMES OF THE SAME ROWS. Which one a row
# produces depends on timing and fixture state, so a per-code ceiling is not the
# gate it looks like: three FX-route codes at 2 each would let a run carry SIX
# skips out of TWO rows and still pass. The binding quantity is the sum over the
# group, and both groups' comments have said so for a while without the gate
# enforcing it — a gate that cannot fail on the thing its own note describes is
# the class this project keeps re-learning.
#
# `max_total` is the number of ROWS that can reach the group, not a budget.
_TRADING_GROUPS: List[Tuple[str, List[str], int]] = [
    ("the two cross-cloud-op directions (§FXROUTEWAIT: the route settles, runs "
     "and does not settle, is refused at ingress, or the card never arrived)",
     ["operator_fx_route_unsettled",
      "operator_fx_route_ingress_refused",
      "operator_fx_route_card_not_propagated"], 2),
    ("the cross-currency seeding pair (which one fires depends on ordering)",
     ["operator_fx_disabled", "operator_treasury_unfundable"], 3),
]


UNCLASSIFIED = "unclassified"


def classify_skip(reason: str) -> str:
    """Map a skip reason onto a known code, or UNCLASSIFIED."""
    text = reason or ""
    for code, pat, _meaning in _PATTERNS:
        if pat.search(text):
            return code
    return UNCLASSIFIED


def code_meanings() -> Dict[str, str]:
    return {code: meaning for code, _pat, meaning in _PATTERNS}


def skip_verdict(census: Dict[str, int]) -> Tuple[bool, List[str]]:
    """Judge a run's skip census against the baseline.

    Returns (ok, complaints). A skip that grew, or one nobody has classified, is
    a complaint. A skip that SHRANK is never a complaint — that is the suite
    reaching further than it did, which is the point.
    """
    complaints: List[str] = []
    n_unclassified = census.get(UNCLASSIFIED, 0)
    if n_unclassified:
        complaints.append(
            f"{n_unclassified} skip(s) match no known reason — read them and either "
            f"fix the test or add a code in skip_codes.py; an unread skip is how "
            f"two live defects hid for a week"
        )
    for label, codes, max_total in _TRADING_GROUPS:
        got = sum(census.get(c, 0) for c in codes)
        if got > max_total:
            complaints.append(
                f"{got} skips across {codes} exceeds {max_total} — these codes are "
                f"different OUTCOMES of {label}, so only {max_total} row(s) can "
                f"produce them; a higher total means a row nobody has accounted for"
            )
    for code, n in sorted(census.items()):
        if code == UNCLASSIFIED:
            continue
        allowed = BASELINE_SKIPS.get(code)
        if allowed is None:
            complaints.append(f"skip code {code!r} is not in BASELINE_SKIPS ({n} test(s))")
        elif n > allowed:
            complaints.append(
                f"skip code {code!r}: {n} > baseline {allowed} — tests stopped "
                f"running that used to run"
            )
    return (not complaints), complaints
