"""AN FX ROUTE'S LEDGER CLAIM MUST MATCH WHAT HAPPENED TO THE MONEY.

§FXSTRAND / findings row 86. `_fx_route_origin` used to treat ANY non-settled
reply from its gateway as "the gateway compensated pre-conversion" and emit
`FxRouteRefunded` saying so. That was true only when the gateway failed INSIDE
the FX core; every raise above that point refunded nothing and wrote no
dead-letter, so the keeper never saw it either. Measured on production before
the fix: **6,222 events carried that claim, 964 had a real reversing transfer,
5,258 did not — 55,295.35 AVT moved and not returned**, with Δ = 0.0 the whole
time because both legs are within-frame and file under `transit_net`.

agentvault2-27 fixed it at both ends (AgentVault `624b23e`): the gateway now
compensates the commonest pre-conversion failure, and the origin reads an
`(origin refunded)` marker to choose between `FxRouteRefunded` — money came back
— and a new `FxRouteStranded` for when it did not.

THIS TEST IS WHY THAT FIX STAYS FIXED. It is the one-off production query I ran
by hand, made permanent and pointed at this tier:

    FxRouteRefunded  ⇒ a reversing TokensTransferred for that route EXISTS
    FxRouteStranded  ⇒ it does NOT

Both directions, because either alone can be satisfied by a rail that emits only
one of the two. Nothing is driven and no money moves — it reads what the ledger
already says, which is also why it can run on any tier.

⚠ A FLAGGED ROUTE MEANS THE RECORD IS UNBACKED, NOT NECESSARILY THAT THE MONEY IS
GONE. agentvault2-27 measured the difference on EU: two claims there have no
route-keyed leg and the funds WERE returned — by hand, at the time, through the
admin rail, whose memo is not `fxroute:<id>:refund`. Failing on it is still right,
because the claim stays uncorroborated for every later auditor unless something
writes a correcting entry — so a reconciler must write the reversing leg or a
correcting event, never just move the money.

⚠ IT ASSERTS ONLY OVER ROUTES ITS TRANSFER WINDOW CAN SEE. `TokensTransferred`
is the highest-volume type on the store, so a fixed page of it reaches back only
so far; a route older than that page would look unreversed because the evidence
is out of frame, not because it is missing. The window is checked against the
oldest route event considered, and a route outside it is dropped from the
population with a count — never scored. A control that cannot see the evidence
must say so rather than convict.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
)
from agentvault_registry.api_tests.federation_suite.tests.test_event_emission_matrix import (
    _events_of_type,
)
from agentvault_registry.api_tests.federation_suite.tests.test_ironkey_authority_clamp import _call, _rest

_ADMIN = "sandbox-A-admin"
# Every leg of a route stamps its transfer `fxroute:<uuid>:<leg>`. TWO legs put
# money back, and they are NOT interchangeable:
#   `refund`             the gateway's own compensation, at the time of the
#                        failure — this is exactly what `FxRouteRefunded` claims
#                        (`routers/teg_integration.py:7126`)
#   `dead-letter-refund` the keeper draining a parked row LATER
#                        (`background_tasks/fx_router_keeper.py:318`)
# The two directions therefore use DIFFERENT sets, and the asymmetry is the point:
#   refunded ⇒ EITHER leg. The claim is about the money, and money returned by the
#              keeper is returned. Production's 5,258 bad routes had NEITHER leg and
#              no dead-letter row at all — nothing to drain, nothing came back.
#   stranded ⇒ only `refund` contradicts it. A stranded route the keeper later
#              drains is the recovery working exactly as designed; scoring that as
#              a contradiction convicts a correct rail with its own safety net.
_MEMO_LEG = re.compile(r"fxroute:([0-9a-fA-F-]{8,}):([a-z][a-z-]*)")
_OWN_REFUND_LEG = "refund"
_KEEPER_REFUND_LEG = "dead-letter-refund"
_TRANSFER_PAGE = 400
# §MCPTEST30 (2026-09-30): the newest page alone skipped this test in 22 of 49 archived runs ("every route
# event is older than the transfer page reaches"): on a tier whose FX routes failed days ago the evidence is
# never on the newest page. So the transfers AROUND each route event are read through the store's own cursor
# (`/api/v1/events/export?since=`, ascending, at most 1000 a call), a window per cluster of route events, and a
# route is judged only when a window starts before it and reaches far enough past it (or ran out of events).
_WINDOW_BEFORE_S = 300
# both claims are judged by the gateway's OWN `:refund` leg (the keeper's later leg only ever ADDS a reversal to a
# refunded claim), and that leg lands around the route event itself, so two minutes past it is enough
_WINDOW_AFTER_S = 120
_WINDOW_LIMIT = 1000
_WINDOW_BUDGET = 8
# The fix this test exists to keep fixed (AgentVault 624b23ec, §FXSTRAND) landed at this instant. A claim written
# before it came from the old rail, which claimed a refund for EVERY non-settled reply: measured on sbx-alpha
# 2026-09-30, all 31 pre-fix FxRouteRefunded claims have no refund leg in either store, while every post-fix route
# is consistent (8 refunded: 7 own `:refund` + 1 keeper leg; 8 stranded: none contradicted). Once the window
# could see them, those 31 would have made the nightly red for ever about history no rail can change, burying the
# regression this test is for. They are counted and named in the state (`pre_fix_unbacked`); only the routes the
# fixed rail wrote are judged. A correcting ledger entry for the old ones is a reconciler's job, not this test's.
_FIX_LANDED = "2026-09-07T00:53:01+00:00"


def _data(e: Dict[str, Any]) -> Dict[str, Any]:
    d = e.get("data")
    return d if isinstance(d, dict) else {}


def _ts(e: Dict[str, Any]) -> str:
    return str(e.get("timestamp") or _data(e).get("timestamp") or "")


def _when(stamp: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except Exception:                                              # noqa: BLE001
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _transfer_window(rig, since: datetime) -> Optional[Tuple[List[Dict[str, Any]], bool]]:
    """TokensTransferred after `since`, oldest first, and whether the store ran out before the limit (the window
    then reaches the present). None when the store could not be read (a third state, never "no transfers")."""
    iso = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    r, refused = await _call(rig, _ADMIN, "adminQueryEventStore", {
        "path": f"/api/v1/events/export?since={quote(iso)}&event_type=TokensTransferred&limit={_WINDOW_LIMIT}"})
    if refused:
        return None
    body = r.get("response", r) if isinstance(r, dict) and "response" in r else r
    if not isinstance(body, list):
        return None
    rows = [e for e in body if isinstance(e, dict)]
    return rows, len(rows) < _WINDOW_LIMIT


@federation_test(
    name="fx_route_refund_claim_matches_the_money",
    category="fx_route_settlement",
    budget_sec=90.0,
    severity="critical",
    requires=["sandbox-A-admin"],
    tags=["fx", "money", "ledger", "emission", "no-money-moved"],
)
async def test_fx_refund_claim_matches_the_money(rig: FederationTestRig) -> AssertionResult:
    """`FxRouteRefunded` ⇒ the money came back. `FxRouteStranded` ⇒ it did not."""
    state: Dict[str, Any] = {}
    windows: List[Tuple[datetime, datetime, bool]] = []     # (start, last seen, exhausted), kept across attempts
    window_rows: Dict[str, Dict[str, Any]] = {}

    async def predicate():
        refunded = await _events_of_type(rig, "FxRouteRefunded", limit=100, label=_ADMIN)
        stranded = await _events_of_type(rig, "FxRouteStranded", limit=100, label=_ADMIN)
        xfers = await _events_of_type(rig, "TokensTransferred", limit=_TRANSFER_PAGE, label=_ADMIN)
        # None is the store being unreadable — a third state that must not read
        # as "no events" (`_events_of_type`'s own contract).
        if refunded is None or stranded is None or xfers is None:
            raise PreconditionUnmet(
                "the EventStore was unreadable for at least one of "
                "FxRouteRefunded / FxRouteStranded / TokensTransferred — an "
                "unreachable store and an unemitted event look identical unless "
                "the difference is kept")
        state["refunded_seen"], state["stranded_seen"] = len(refunded), len(stranded)
        state["transfers_scanned"] = len(xfers)
        if not refunded and not stranded:
            raise PreconditionUnmet(
                "no FxRouteRefunded or FxRouteStranded on this store — the rail "
                "has not failed here, so there is no claim to check (drive an FX "
                "route to a receiver whose card has not propagated to produce one)")

        # The evidence window: the oldest transfer this page reaches.
        stamps = sorted(t for t in (_ts(x) for x in xfers) if t)
        oldest_transfer = stamps[0] if stamps else ""
        state["transfer_window_oldest"] = oldest_transfer
        page_start = _when(oldest_transfer)

        def _covered(t: datetime) -> bool:
            if page_start is not None and t >= page_start:
                return True               # the newest page reaches the present
            return any(a <= t - timedelta(seconds=60) and (done or b >= t + timedelta(seconds=_WINDOW_AFTER_S))
                       for a, b, done in windows)

        fetched = 0
        _fix = _when(_FIX_LANDED)

        def _pre_fix(e) -> bool:
            t0 = _when(_ts(e))
            return bool(t0 is not None and _fix is not None and t0 < _fix)

        # the routes this test SCORES get the window budget first; the old ones only what is left
        for e in sorted(refunded + stranded, key=lambda e: (_pre_fix(e), _ts(e))):
            t = _when(_ts(e))
            if t is None or _covered(t) or fetched >= _WINDOW_BUDGET:
                continue
            got = await _transfer_window(rig, t - timedelta(seconds=_WINDOW_BEFORE_S))
            fetched += 1
            if got is None:
                break
            rows, exhausted = got
            last = max((w for w in (_when(_ts(x)) for x in rows) if w is not None), default=t)
            windows.append((t - timedelta(seconds=_WINDOW_BEFORE_S), last, exhausted))
            for x in rows:
                window_rows[str(x.get("id") or id(x))] = x
        state["route_windows_read"] = len(windows)
        state["route_window_transfers"] = len(window_rows)

        own_refunds, keeper_refunds = set(), set()
        for x in list(xfers) + list(window_rows.values()):
            d = _data(x)
            memo = str(d.get("memo") or d.get("message") or "")
            m = _MEMO_LEG.search(memo)
            if not m:
                continue
            rid, leg = m.group(1), m.group(2)
            if leg == _OWN_REFUND_LEG:
                own_refunds.add(rid)
            elif leg == _KEEPER_REFUND_LEG:
                keeper_refunds.add(rid)
        state["own_refund_legs_found"] = len(own_refunds)
        state["keeper_refund_legs_found"] = len(keeper_refunds)

        bad_refund: List[str] = []
        bad_strand: List[str] = []
        pre_fix_unbacked: List[str] = []
        pre_fix_seen = 0
        out_of_window = 0
        fixed_at = _when(_FIX_LANDED)
        for ev, claims_money_back in ((refunded, True), (stranded, False)):
            for e in ev:
                rid = str(_data(e).get("route_id") or "")
                if not rid:
                    continue
                t_ev = _when(_ts(e))
                if t_ev is not None and fixed_at is not None and t_ev < fixed_at:
                    # written by the rail the fix replaced: reported, never scored
                    pre_fix_seen += 1
                    if claims_money_back and _covered(t_ev) and rid not in (own_refunds | keeper_refunds):
                        pre_fix_unbacked.append(rid)
                    continue
                # Only judge a route whose evidence a window could hold.
                t = _when(_ts(e))
                if t is None or not _covered(t):
                    out_of_window += 1
                    continue
                if claims_money_back and rid not in (own_refunds | keeper_refunds):
                    bad_refund.append(rid)
                elif (not claims_money_back) and rid in own_refunds:
                    # Only the gateway's OWN refund contradicts "stranded".
                    # A `dead-letter-refund` here means the keeper drained the
                    # park afterwards, which is the designed recovery.
                    bad_strand.append(rid)
        state["out_of_window_skipped"] = out_of_window
        state["pre_fix_routes_not_scored"] = pre_fix_seen
        state["pre_fix_unbacked"] = len(pre_fix_unbacked)
        state["pre_fix_unbacked_sample"] = pre_fix_unbacked[:3]
        state["refunded_without_a_reversal"] = bad_refund[:6]
        state["stranded_with_a_reversal"] = bad_strand[:6]
        state["judged"] = (len(refunded) + len(stranded)) - out_of_window - pre_fix_seen
        if state["judged"] <= 0:
            raise PreconditionUnmet(
                f"no route event ({len(refunded)} refunded, {len(stranded)} stranded) has its evidence in "
                f"frame: the newest transfer page reaches {oldest_transfer} and {len(windows)} window(s) of "
                f"the store's own cursor were read (budget {_WINDOW_BUDGET}) — nothing here can be judged "
                f"either way")
        if bad_refund:
            state["why"] = ("FxRouteRefunded claims the money came back and NO "
                            "route-keyed reversal exists — neither a gateway `:refund` "
                            "leg nor a keeper `:dead-letter-refund`. Either nobody "
                            "performed the compensation (findings row 86: 5,258 such "
                            "events on production) or someone returned the funds BY "
                            "HAND, whose admin-rail memo is not keyed to the route. "
                            "The ledger cannot tell those apart, which is itself the "
                            "finding: repairing the money does not repair the record")
        if bad_strand:
            state["why"] = ("FxRouteStranded says the money did NOT come back, but the "
                            "gateway's OWN `:refund` leg exists for that route — the "
                            "ledger understates a compensation that did happen (a later "
                            "`:dead-letter-refund` would NOT be a contradiction)")
        return not bad_refund and not bad_strand

    return await rig.assert_within(
        budget_sec=90.0, predicate=predicate,
        description="every FxRouteRefunded has a reversing transfer and every "
                    "FxRouteStranded has none — the ledger's claim matches the money",
        capture_state=lambda: state,
    )


@federation_test(
    name="fx_route_parked_funds_have_a_resolver",
    category="fx_route_settlement",
    budget_sec=60.0,
    severity="critical",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["fx", "money", "worker", "no-money-moved"],
)
async def test_fx_route_parked_funds_have_a_resolver(rig: FederationTestRig) -> AssertionResult:
    """A frame that can PARK funds must run the worker that unparks them.

    §FXSTRAND / findings row 109. When an op→op route fails past the point of no
    return, the gateway parks the money at its `@fx_router` and writes a row to
    `fx_route_dead_letters` with the log line *"keeper will refund <origin>"*.
    That sentence is written unconditionally — and `fx_router_keeper` is opt-in
    (`FX_ROUTER_KEEPER_ENABLED`, default false) AND needs its own DB toggle.
    Both were off on this tier, so the promise had nobody to keep it: measured
    2026-09-07, one row `pending / retries 0 / last_error null` for 14 minutes,
    1.99 SBXA parked, sender 48 of 50, and NO way to tell from the row that
    nothing would ever come for it. Worse, a worker that exits at its env gate
    never registers, so `/admin/workers/status` did not list `fx_router_keeper`
    at all — absent reads exactly like a worker that does not exist.

    The authoritative signal is the rail's own `dead_letter_drain_active`
    (agentvault2-27, `7d32aec`): `active` means the LIQUIDITY manager is on, and
    since `c715069` a frame drains parked funds with `active` false — EU is
    exactly that frame. Asserting on `active` would fail the nodes that fix
    repaired. An older image without the field falls back to the two switches
    that were the whole gate before it; a `null` is the instrument saying it
    could not tell, which is a third state, not a verdict.

    So this does not wait for a failure to happen: it asserts the CAPABILITY,
    which is checkable on a quiet tier and would have caught the gap the day the
    route was switched on without its keeper. A frame is a gateway iff it holds
    an `@fx_router` (`router_did`); every gateway must have `active` true — the
    rail's own word for "env gate AND config toggle" — and the dead-letter half
    enabled. A queue that happens to be empty proves nothing: the funds park
    first and the resolver is looked for afterwards.

    Read-only: one admin GET per frame, no money moves.
    """
    state: Dict[str, Any] = {}

    async def predicate():
        frames: Dict[str, Dict[str, Any]] = {}
        unreadable: Dict[str, Any] = {}
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            code, body = await _rest(rig, "GET", "/api/v1/teg/fx/router-keeper", label=label)
            if code != 200 or not isinstance(body, dict):
                unreadable[label] = f"HTTP {code}: {str(body)[:120]}"
                continue
            frames[label] = body
        state["unreadable"] = unreadable
        if not frames:
            raise PreconditionUnmet(
                "the FX router-keeper rail answered on neither frame "
                f"({unreadable}) — an unreachable rail and a missing keeper look "
                "identical unless the difference is kept")

        gateways, verdicts, offenders, undecidable = [], {}, [], []
        for label, body in frames.items():
            cfg = body.get("config") if isinstance(body.get("config"), dict) else {}
            router_did = body.get("router_did")
            # `dead_letter_drain_active` is the rail's OWN word for "a parked row
            # will get drained" (agentvault2-27, AgentVault `7d32aec`), computed by
            # calling the worker's `_should_run()` rather than re-deriving its rule.
            # Prefer it. `active` is the LIQUIDITY verdict (env gate AND config
            # toggle) and since `c715069` a frame can drain with `active` false —
            # asserting on it would convict exactly the frames that fix repaired.
            # `None` means the instrument itself raised: not a claim either way.
            drain = body.get("dead_letter_drain_active", "__absent__")
            row = {
                "router_did": bool(router_did),
                "dead_letter_drain_active": drain,
                "active": bool(body.get("active")),
                "env_gate_enabled": bool(body.get("env_gate_enabled")),
                "config_enabled": bool(cfg.get("enabled")),
                "dead_letter_refund_enabled": bool(cfg.get("dead_letter_refund_enabled")),
                "dead_letters_pending": body.get("dead_letters_pending"),
            }
            verdicts[label] = row
            if not router_did:
                continue  # holds no @fx_router: it cannot park, so it owes no keeper
            gateways.append(label)
            if drain is None:
                undecidable.append(label)      # the rail could not tell; neither can we
            elif drain == "__absent__":
                # An older image with no such field: fall back to the pair of
                # switches that WAS the whole gate before `c715069`.
                if not (row["active"] and row["dead_letter_refund_enabled"]):
                    offenders.append(label)
            elif not drain:
                offenders.append(label)
        state["frames"] = verdicts
        state["gateways"] = gateways
        state["without_a_resolver"] = offenders
        state["rail_could_not_tell"] = undecidable
        if undecidable and not offenders:
            raise PreconditionUnmet(
                f"the keeper status rail answered `dead_letter_drain_active: null` "
                f"on {undecidable} — its own instrumentation raised, which is a "
                f"third state and not evidence that the drain is off")
        if not gateways:
            raise PreconditionUnmet(
                "neither frame holds an @fx_router, so neither can park FX funds "
                "and neither owes a resolver (FX_ROUTER_DID unset on both)")
        if offenders:
            state["why"] = (
                "this frame can park funds mid-route but nothing will ever return "
                "them: the dead-letter record says 'keeper will refund', and the "
                "keeper is inactive (env gate AND config toggle must both be on) "
                "or its dead-letter half is off. A parked row then sits pending "
                "with retries 0 forever, which reads like a fresh row, not a leak")
        return not offenders

    return await rig.assert_within(
        budget_sec=60.0, predicate=predicate,
        description="every frame that can park FX funds runs the keeper that refunds them",
        capture_state=lambda: state,
    )
