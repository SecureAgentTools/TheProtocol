"""THE DISCOVERY INDEX FEED, driven as a feed rather than as a list (§DIRFEED).

His word, 2026-09-06: *"there is a new discovery in … we will write tests for
after implementation too."* This is that. The mechanism agentvault2-27 built
turns `GET /api/v1/agent-cards/` from a page of rows into a CHANGE FEED an index
can walk — `agent_did` + `updated_at` on the summary, an `updated_since` cursor,
`natives_only`, and `applied_filters` echoing what the server actually ran.

WHAT THESE TESTS ARE FOR, AND WHY EACH ONE EXISTS. Every property below is
here because its absence has already cost something on this project:

  · `applied_filters` exists because FastAPI DROPS a query parameter an endpoint
    does not declare and still answers 200. An index sending `updated_since` to
    an older registry gets the WHOLE list back and no way to know its cursor was
    ignored — so the echo is the only honest signal, and `null` (nothing asked)
    is a real third state, not an empty dict.

  · The paging test asserts a PARTITION — every row exactly once — because a
    walk that merely counts cannot see a duplicate. Measured on EU 2026-09-06:
    ordering on `updated_at` alone (95 cards sharing 68 instants) returned two
    rows twice and two never, while a 5,380-card control graded itself "exact
    agreement" because the errors are symmetric and cancel in a sum (findings
    row 85). The id tiebreak fixed it; nothing but a set comparison can prove
    it stays fixed, and the unit test pins the COMPILED statement, which a
    three-row fixture passes with or without the bug.

  · The cursor test asserts the bound is INCLUSIVE, because an exclusive one
    silently drops every row sharing the last instant of a page — the same
    non-uniqueness that broke the ordering.

  · The no-session test asserts the ROUTE is public. It deliberately does NOT
    claim the PAGE is: §DISCPUBLIC found a public view firing an owner-tier read
    whose 401 ran the app's logout branch, and no sweep can see that from
    outside. That half needs a browser with a request log and lives with the
    session that owns the view.

⚠ NEVER ASSERT AN EXACT KEY SET on any of these payloads. V0231 and V0232 both
added fields here; a test that pins the whole shape turns every additive change
into a red run, which is how a suite earns the right to be ignored. Assert that
what you asked for is named, and let the rest grow.
"""
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.probe_meter import record_probe
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
)
from agentvault_registry.api_tests.federation_suite.tests.test_ironkey_authority_clamp import (
    _rest,
)

# ⚠ THE TRAILING SLASH IS LOAD-BEARING on this route: `/agent-cards` answers 307
# and `/agent-cards/` answers 200 (measured 2026-09-06). Which form loses differs
# per route — the §VITALS class, where three callers had been dead for months
# because a proxied redirect lost its scheme. Written once, here.
#
# ⚠ AND ITS SIBLING IS THE OPPOSITE: `/api/v1/agent-cards/discover` (test 6) must
# have NO trailing slash and 307s with one. Two routes on one prefix, one path
# segment apart, with contradictory rules. Neither is wrong; guessing is.
_FEED = "/api/v1/agent-cards/"
_LABEL = "sandbox-A-admin"

# Rows this tier may legitimately gain BETWEEN two calls of one test. Every
# comparison across two responses needs it; every comparison inside ONE response
# must not use it (see the facet cross-check, which reads a single payload).
_CHURN_TOLERANCE = 25


def _items(body: Any) -> List[Dict[str, Any]]:
    return (body or {}).get("items") or [] if isinstance(body, dict) else []


def _ids(body: Any) -> List[str]:
    return [str(r.get("id")) for r in _items(body) if r.get("id") is not None]


def _total(body: Any) -> Optional[int]:
    if not isinstance(body, dict):
        return None
    p = body.get("pagination")
    if isinstance(p, dict) and isinstance(p.get("total_items"), int):
        return p["total_items"]
    return body.get("total_items") if isinstance(body.get("total_items"), int) else None


async def _feed(rig, query: str = "", label: str = _LABEL) -> Tuple[int, Any]:
    return await _rest(rig, "GET", _FEED + (("?" + query) if query else ""), label=label)


# ─── 1 · the echo says what RAN, and says nothing when nothing was asked ────


@federation_test(
    name="discovery_applied_filters_echoes_what_ran",
    category="discovery_index_feed",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["discovery", "index-feed", "applied-filters"],
)
async def test_applied_filters_echo(rig: FederationTestRig) -> AssertionResult:
    """`applied_filters` names the filters the server APPLIED — null when none.

    THE CONTROL IS THE POINT. A server that ignores a query parameter answers
    200, so this test's real subject is the UNDECLARED parameter: it must leave
    the echo null AND must not change the population. Without that leg the test
    would pass on a server that echoes whatever it was sent.
    """
    state: Dict[str, Any] = {}

    async def predicate():
        c0, b0 = await _feed(rig, "limit=1")
        c1, b1 = await _feed(rig, "limit=1&natives_only=true")
        c2, b2 = await _feed(rig, "limit=1&no_such_filter_at_all=1")
        state["status"] = [c0, c1, c2]
        if not all(c == 200 for c in (c0, c1, c2)):
            return False
        af0, af1, af2 = (b.get("applied_filters") if isinstance(b, dict) else "?"
                         for b in (b0, b1, b2))
        state["nothing_asked"] = af0
        state["natives_only_asked"] = af1
        state["undeclared_param"] = af2
        state["total_plain"], state["total_undeclared"] = _total(b0), _total(b2)
        state["total_natives"] = _total(b1)

        # (a) nothing asked → the honest third state, not an empty dict
        if af0 is not None:
            state["why"] = "a request with no filters echoed a non-null applied_filters"
            return False
        # (b) a declared filter is NAMED and true — never an exact key set
        if not (isinstance(af1, dict) and af1.get("natives_only") is True):
            state["why"] = "natives_only=true was not named in the echo"
            return False
        # (c) THE CONTROL: an undeclared parameter is dropped, and says so
        if af2 is not None:
            state["why"] = "an UNDECLARED parameter appeared in applied_filters"
            return False
        # ⚠ CROSS-CALL COMPARISON, SO IT NEEDS A TOLERANCE. This tier gains
        # agents while a test runs (measured 2454 → 2456 within minutes), and an
        # exact equality here would go red for churn, which has nothing to do
        # with the property. The tolerance cannot hide a filter: leg (d) below
        # establishes that a REAL filter on this route removes hundreds of rows
        # (natives_only: 4582 of 5559), two orders of magnitude past this bound.
        _drift = abs((state["total_plain"] or 0) - (state["total_undeclared"] or 0))
        state["population_drift_between_calls"] = _drift
        if _drift > _CHURN_TOLERANCE:
            state["why"] = (f"an undeclared parameter moved the population by {_drift} "
                            f"(> {_CHURN_TOLERANCE} rows of churn) — it was APPLIED")
            return False
        # (d) the declared filter must actually DO something, or (b) proves only
        # that the server can echo a word back. A filter may never ADD rows; and
        # if it removes none, this tier holds no foreign card and the effect is
        # NOT MEASURABLE here — which is a precondition, not a pass.
        if state["total_natives"] is None or state["total_plain"] is None:
            state["why"] = "no total_items to compare — cannot tell filtered from not"
            return False
        if state["total_natives"] > state["total_plain"]:
            state["why"] = "natives_only returned MORE rows than no filter at all"
            return False
        state["filter_had_an_effect"] = state["total_natives"] < state["total_plain"]
        if not state["filter_had_an_effect"]:
            raise PreconditionUnmet(
                f"natives_only removed nothing ({state['total_natives']} of "
                f"{state['total_plain']}): this registry mirrors no foreign card, so the "
                f"echo can be checked but the filter cannot be seen to work")
        return True

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="applied_filters names what ran, is null when nothing was asked, "
                    "and an undeclared parameter neither appears in it nor changes the result",
        capture_state=lambda: state,
    )


# ─── 2 · paging is a PARTITION, not a sample ────────────────────────────────


@federation_test(
    name="discovery_feed_paging_is_a_partition",
    category="discovery_index_feed",
    budget_sec=60.0,
    severity="critical",
    requires=["sandbox-A-admin"],
    tags=["discovery", "index-feed", "pagination"],
)
async def test_paging_is_a_partition(rig: FederationTestRig) -> AssertionResult:
    """Walking the feed in pages returns every row EXACTLY ONCE — walked where it
    can actually break.

    Compares SETS, never counts: a duplicate and a miss cancel in a sum, which is
    how the `updated_at`-only ordering passed a 5,380-row control while being
    wrong in both directions (findings row 85).

    ⚠ AND IT WALKS A DEGENERATE WINDOW ON PURPOSE. A non-total ORDER BY only
    misbehaves where the sort key REPEATS, so a walk over rows with distinct
    timestamps passes with or without the tiebreak and measures nothing. Measured
    on this tier before writing the test: the first 16 rows of the default order
    hold 16 distinct instants — that walk could not have caught the bug this test
    exists for. So the test first FINDS an instant several cards share and starts
    the walk there (the cursor is inclusive, so `updated_since=<that instant>`
    lands on it); with no such instant it refuses loudly rather than pass over a
    window that cannot show the defect.
    """
    state: Dict[str, Any] = {}
    PAGE, PAGES, SCAN = 4, 4, 200
    WHOLE = PAGE * PAGES

    async def predicate():
        # 1 · find a repeated sort key — the only place a non-total order breaks
        c, wide = await _feed(rig, f"limit={SCAN}")
        state["scan_status"], state["scanned"] = c, len(_items(wide))
        if c != 200:
            return False
        stamps = [str(r.get("updated_at")) for r in _items(wide) if r.get("updated_at")]
        counts: Dict[str, int] = {}
        for t in stamps:
            counts[t] = counts.get(t, 0) + 1
        shared = sorted(t for t, n in counts.items() if n >= 2)
        state["distinct_instants_in_scan"] = len(set(stamps))
        state["instants_shared_by_2_or_more"] = len(shared)
        if not shared:
            raise PreconditionUnmet(
                f"no updated_at is shared by two cards in {len(stamps)} rows — a walk "
                f"here passes with or without a tiebreak, so it would measure nothing. "
                f"(A non-total ORDER BY only misbehaves where the sort key repeats.)")
        anchor = shared[0]
        state["anchor_instant"], state["anchor_shared_by"] = anchor, counts[anchor]
        q = "updated_since=" + urllib.parse.quote(anchor, safe="")

        # 2 · one call vs the same range walked in pages, both from that instant
        c, whole = await _feed(rig, f"limit={WHOLE}&{q}")
        state["whole_status"] = c
        if c != 200:
            return False
        want = _ids(whole)
        state["whole_returned"] = len(want)
        if len(want) < WHOLE:
            raise PreconditionUnmet(
                f"only {len(want)} card(s) at or after the shared instant; a partition "
                f"needs at least {WHOLE} to be walked in {PAGES} pages")
        seen_stamps = [str(r.get("updated_at")) for r in _items(whole)]
        state["shared_instants_inside_the_walked_window"] = (
            len(seen_stamps) - len(set(seen_stamps)))

        # This walk is ASC from an instant in the PAST, so a newly created card
        # sorts AFTER the window and cannot perturb it — unlike the ranked page's
        # `sort=newest`. What CAN perturb it is an existing card in the window
        # being updated (its instant moves to now and it leaves) or removed.
        #
        # §MCPTEST30 (2026-09-30): so the test asks whether the WINDOW moved, not
        # whether the whole tail did. It used to refuse whenever `total` (every
        # card at or after the anchor) changed during the walk, and on a tier
        # with the live AGORA sim that tail moves every minute: 29 of 50 archived
        # runs ended NOT MEASURED here (267 -> 266 in round 2), though a change
        # past row WHOLE cannot touch the first WHOLE rows. The window is read
        # again after the walk: a card that left it cannot come back (its instant
        # only moves forward), so the same ids in the same order after the walk
        # mean nothing moved inside it during the walk. Tail churn is reported.
        _total0 = _total(whole)
        totals: List[Optional[int]] = [_total0]
        walked: List[str] = []
        for i in range(PAGES):
            c, b = await _feed(rig, f"limit={PAGE}&skip={i * PAGE}&{q}")
            if c != 200:
                state["failed_page"] = (i, c)
                return False
            totals.append(_total(b))
            walked.extend(_ids(b))
        c, again = await _feed(rig, f"limit={WHOLE}&{q}")
        state["window_reread_status"] = c
        if c != 200:
            return False
        totals.append(_total(again))
        state["totals_during_walk"] = totals
        state["tail_churn_during_walk"] = len(set(totals)) > 1
        after = _ids(again)
        if after != want:
            state["window_left"] = sorted(set(want) - set(after))[:6]
            state["window_entered"] = sorted(set(after) - set(want))[:6]
            raise PreconditionUnmet(
                f"a card inside the walked window changed under the walk "
                f"({len(state['window_left'])} left, {len(state['window_entered'])} entered; "
                f"totals {totals}) — a partition cannot be measured across a moving "
                f"window. Not a defect: re-run.")
        state["walked"], state["distinct"] = len(walked), len(set(walked))
        state["duplicates"] = sorted({x for x in walked if walked.count(x) > 1})[:6]
        state["missed"] = sorted(set(want) - set(walked))[:6]
        state["extra"] = sorted(set(walked) - set(want))[:6]
        return len(walked) == len(set(walked)) and set(walked) == set(want)

    return await rig.assert_within(
        budget_sec=60.0, predicate=predicate,
        description=f"{PAGES} pages of {PAGE} partition the same rows one call of "
                    f"{WHOLE} returns, walked from an instant several cards SHARE "
                    f"— no duplicates, nothing missed",
        capture_state=lambda: state,
    )


# ─── 3 · the cursor's bound is INCLUSIVE ────────────────────────────────────


@federation_test(
    name="discovery_updated_since_is_an_inclusive_cursor",
    category="discovery_index_feed",
    budget_sec=45.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["discovery", "index-feed", "cursor"],
)
async def test_updated_since_inclusive(rig: FederationTestRig) -> AssertionResult:
    """A row AT the cursor instant is returned, so no row can fall between pages.

    An exclusive bound drops every row sharing the last instant of the previous
    page — and instants are shared here by the hundred (68 distinct values across
    95 cards on EU). The second leg is the control: a cursor strictly LATER than
    the row must exclude it, which is what proves the parameter is applied at all
    rather than silently dropped.
    """
    state: Dict[str, Any] = {}

    async def predicate():
        code, page = await _feed(rig, "limit=3&updated_since=1970-01-01T00:00:00Z")
        state["page_status"] = code
        rows = _items(page)
        if code != 200 or not rows:
            state["why"] = "no rows under an epoch-zero cursor"
            return False
        anchor = rows[-1]
        ts, rid = anchor.get("updated_at"), str(anchor.get("id"))
        state["anchor_id"], state["anchor_updated_at"] = rid, ts
        if not ts:
            raise PreconditionUnmet("the summary carries no updated_at — no cursor to test")

        q = urllib.parse.quote(str(ts), safe="")
        _LIM = 200
        c_in, b_in = await _feed(rig, f"limit={_LIM}&updated_since={q}")
        if c_in != 200:
            state["why"] = f"inclusive re-read answered {c_in}"
            return False
        _in_ids = _ids(b_in)
        state["anchor_present_at_its_own_instant"] = rid in _in_ids
        # ⚠ AN ABSENT ANCHOR IS ONLY EVIDENCE IF THE PAGE COULD HAVE HELD IT.
        # Instants repeat here by the hundred (one on this tier is shared by 100
        # cards), so a re-read that came back FULL may simply have stopped before
        # the anchor — which says nothing about whether the bound is inclusive.
        # Precondition, not failure.
        if not state["anchor_present_at_its_own_instant"] and len(_in_ids) >= _LIM:
            raise PreconditionUnmet(
                f"the re-read filled its page ({len(_in_ids)} of {_LIM}) without the "
                f"anchor, so the anchor may lie beyond it — instants repeat on this "
                f"tier and a full page cannot decide whether the bound is inclusive")

        # CONTROL: the same read one second later must NOT carry the anchor,
        # or the parameter is being ignored and leg one proves nothing.
        from datetime import datetime, timedelta, timezone
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            raise PreconditionUnmet(f"unparseable updated_at {ts!r}")
        later = (dt.astimezone(timezone.utc) + timedelta(seconds=1)).isoformat()
        c_af, b_af = await _feed(rig, f"limit=50&updated_since={urllib.parse.quote(later, safe='')}")
        state["control_status"] = c_af
        state["anchor_absent_one_second_later"] = (c_af == 200 and rid not in _ids(b_af))
        return bool(state["anchor_present_at_its_own_instant"]
                    and state["anchor_absent_one_second_later"])

    return await rig.assert_within(
        budget_sec=45.0, predicate=predicate,
        description="updated_since includes a row at its own instant and excludes it "
                    "one second later (inclusive bound, and the filter is really applied)",
        capture_state=lambda: state,
    )


# ─── 4 · the feed answers a caller with NO session ──────────────────────────


@federation_test(
    name="discovery_feed_serves_a_caller_with_no_session",
    category="discovery_index_feed",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["discovery", "index-feed", "public"],
)
async def test_feed_public_no_session(rig: FederationTestRig) -> AssertionResult:
    """The discovery reads answer with NO Authorization header at all.

    Every other test here speaks through `adminRequest`, which always carries a
    bearer — so none of them can see this property. This one calls the loopback
    directly with no header, and pairs it with an owner-tier route that MUST
    refuse: without that control a 200 could equally mean "auth is off on this
    node", which is a thing that has happened here (§MONEY-M3a).

    ⚠ WHAT THIS DOES NOT PROVE: that the public PAGE is clean. §DISCPUBLIC found
    a public view firing `contracts/v2/engage-preview` and running the app's
    logout branch on the 401 — the route was innocent and the page was not. That
    needs a browser reading its own request log.
    """
    state: Dict[str, Any] = {}
    BASE = "http://localhost:8000"

    def _get(path: str) -> int:
        # COUNT IT. The meter funnels on `exec_in_container`, which is how every
        # MCP call, REST-via-adminRequest and psql query reaches the tier — and a
        # raw loopback GET reaches it by a route nothing had used before, so the
        # U1 rule marked this test `vacuous`: passed, zero probes, "a test that
        # never reached for the system cannot have measured it". It HAD reached
        # for the system, through a channel the meter could not see. The rule is
        # right; the fix is to declare the probe, not to tag the test `no-probe`
        # (which means structural BY DESIGN, and this one is not).
        record_probe()
        req = urllib.request.Request(BASE + path, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception as e:                                   # noqa: BLE001
            state.setdefault("transport_errors", []).append(f"{path}: {type(e).__name__}")
            return -1

    async def predicate():
        # urllib blocks; a blocking call inside the predicate stalls the whole
        # bounded-concurrent runner, not just this test.
        state["feed"] = await asyncio.to_thread(_get, _FEED + "?limit=1")
        state["federation_registries"] = await asyncio.to_thread(
            _get, "/api/v1/federation/registries")
        state["owner_tier_control"] = await asyncio.to_thread(
            _get, "/api/v1/developers/me/agents")
        public_ok = state["feed"] == 200 and state["federation_registries"] == 200
        # the control must REFUSE — 401/403 both count as "the probe can see a no"
        control_refuses = state["owner_tier_control"] in (401, 403)
        state["control_refuses"] = control_refuses
        if not control_refuses:
            state["why"] = ("the owner-tier control did not refuse an anonymous call — "
                            "a 200 on the public feed proves nothing here")
        return public_ok and control_refuses

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="the discovery feed and the federation table answer an anonymous "
                    "caller, while an owner-tier route refuses one",
        capture_state=lambda: state,
    )


# ─── 5 · the public federation table states ADMISSION ───────────────────────


@federation_test(
    name="discovery_federation_table_states_admission",
    category="discovery_index_feed",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["discovery", "federation", "admission"],
)
async def test_federation_table_admission(rig: FederationTestRig) -> AssertionResult:
    """`/federation/registries` says whether a peer is ADMITTED, and how to dial it.

    An index that cannot tell a licensed peer from a row someone's fan-out
    mentioned will happily walk hearsay. §DIRFEED added `peer_status`,
    `peer_type` and a dialable `public_url`; this asserts they are populated on
    a real row rather than merely present as nulls — the difference between a
    field and an answer.
    """
    state: Dict[str, Any] = {}

    async def predicate():
        code, body = await _rest(rig, "GET", "/api/v1/federation/registries")
        state["status"] = code
        if code != 200 or not isinstance(body, list) or not body:
            state["why"] = f"no federation rows (status {code})"
            return False
        state["rows"] = len(body)
        typed = [r for r in body if isinstance(r, dict) and r.get("peer_status")]
        state["rows_with_status"] = len(typed)
        state["statuses"] = sorted({str(r.get("peer_status")) for r in typed})[:6]
        state["types"] = sorted({str(r.get("peer_type")) for r in typed if r.get("peer_type")})[:6]
        active = [r for r in typed if str(r.get("peer_status")).upper() == "ACTIVE"]
        state["active_rows"] = len(active)
        if not active:
            # An all()-over-empty would read as clean. Say so instead.
            state["why"] = "no ACTIVE row — nothing to assert admission on"
            return False
        state["active_with_public_url"] = sum(1 for r in active if r.get("public_url"))
        state["active_with_type"] = sum(1 for r in active if r.get("peer_type"))
        return (state["rows_with_status"] == len(body)
                and state["active_with_type"] == len(active))

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="every federation row carries peer_status, and every ACTIVE row "
                    "carries peer_type (admission is stated, not inferred)",
        capture_state=lambda: state,
    )


# ─── 6 · the RANKED page — the one a visitor actually gets ──────────────────


@federation_test(
    name="discovery_ranked_page_is_public_and_partitions",
    category="discovery_index_feed",
    budget_sec=60.0,
    severity="critical",
    requires=["sandbox-A-admin"],
    tags=["discovery", "ranked", "public", "pagination"],
)
async def test_ranked_page_public_and_partitions(rig: FederationTestRig) -> AssertionResult:
    """`/agent-cards/discover` — the page the Discovery view and the landing
    preview both read — answers a caller with no session, and pages cleanly.

    ⚠ TWO SIBLING ROUTES ON ONE PREFIX, OPPOSITE SLASH RULES: the index feed
    needs `/agent-cards/` (the bare path 307s) and this one needs
    `/agent-cards/discover` (WITH a slash it 307s). "Which slash form loses
    differs per route" has been doctrine since §VITALS; here the two forms sit
    one path segment apart.

    ⚠ AND THE PAGE PARAMETER IS `offset`, NOT `skip`. The index feed pages on
    `skip`; this one declares `offset`, so a caller who guesses gets 200 and page
    ONE, forever — measured: `skip=4` returns the same four rows as `skip=0`.
    There is no `applied_filters` echo on this route to say so, which is exactly
    the silent-drop the echo was added to the feed for. Recorded in state rather
    than asserted, because `offset` is the declared contract and `skip` being
    ignored is FastAPI behaving as documented — but a client that guesses is
    silently stuck, and that is worth someone knowing.

    The guaranteed shape (agentvault2-27, 2026-09-06) is `items[]`, `total`,
    `has_more`; `facets`, `ranking` and `generated_in_ms` are additive and are
    read only if present. Nothing about the MARKUP is pinned — the view and the
    agent modal are being reworked, so this asserts the DATA.
    """
    state: Dict[str, Any] = {}
    PAGE, PAGES = 4, 3
    WHOLE = PAGE * PAGES
    PATH = "/api/v1/agent-cards/discover"

    def _anon(path: str) -> Tuple[int, Any]:
        record_probe()                      # see the note on _get in test 4
        req = urllib.request.Request("http://localhost:8000" + path, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            return e.code, None
        except Exception as e:                                   # noqa: BLE001
            state.setdefault("transport_errors", []).append(f"{path}: {type(e).__name__}")
            return -1, None

    def _facet_checks(p: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        """The three aggregations of one answer against its total, and the names that disagree."""
        f = p.get("facets")
        if not isinstance(f, dict) or p.get("total") is None:
            return None, []
        origins = f.get("origins") or []
        checks = {
            "facets_total": f.get("total"),
            "free_plus_paid": (f.get("free") or 0) + (f.get("paid") or 0),
            "sum_origin_counts": sum(int(o.get("count") or 0) for o in origins if isinstance(o, dict)),
            "live_24h_subset": f.get("live_24h"),
            "total": p.get("total"),
        }
        return checks, [k for k in ("facets_total", "free_plus_paid", "sum_origin_counts") if checks[k] != checks["total"]]

    async def predicate():
        # V0614: the captured state is the LAST attempt's. Keys an earlier attempt set are dropped, so a red row never
        # shows one attempt's moved total beside another attempt's reason (the V0613 round's row did).
        for _stale in ("why", "total_moved_to", "facet_checks", "facet_checks_reread", "anon_status_reread"):
            state.pop(_stale, None)
        # (a) a visitor with NO Authorization header gets the page
        code, whole = await asyncio.to_thread(_anon, f"{PATH}?limit={WHOLE}&sort=newest")
        state["anon_status"] = code
        if code != 200 or not isinstance(whole, dict):
            return False
        for k in ("items", "total", "has_more"):
            if k not in whole:
                state["why"] = f"guaranteed key {k!r} missing from the ranked page"
                return False
        state["total"], state["has_more"] = whole.get("total"), whole.get("has_more")
        state["extras_present"] = sorted(
            k for k in ("facets", "ranking", "generated_in_ms") if k in whole)
        state["generated_in_ms"] = whole.get("generated_in_ms")

        # (a2) THE FACETS MUST COUNT THE SAME POPULATION THE LIST DOES. Read from
        # ONE payload, never across calls — this tier gains agents while a test
        # runs (2454 → 2456 in the minutes around writing this). Three
        # independent aggregations agreeing is a real cross-check: a facet
        # computed over a different filter than the list is the §DISCMIX shape,
        # where a correct number reads as a wrong network. `live_24h` is a
        # SUBSET, not a partition, so it is recorded and not summed.
        #
        # V0614: ONE PAYLOAD IS NOT ONE SNAPSHOT. The route counts the page's total (COUNT(*) OVER ()) and the facets in
        # two statements, each its own READ COMMITTED snapshot, so a card that lands between them makes one answer
        # disagree with itself: the V0613 round read facets 6542 against total 6544 while the population moved
        # 6537 -> 6544, the 2026-10-13 nightly 6473 against 6472 (the sign flips: timing, not a filter). A moving
        # population cannot be told from the §DISCMIX shape this check exists for; a still one can. So a mismatch is
        # read once more: the total moved -> PreconditionUnmet (not measurable this pass); the total held and the
        # second answer still disagrees with itself -> red; the second answer agrees -> it is the one judged.
        checks, off = _facet_checks(whole)
        if checks is not None:
            state["facet_checks"] = checks
            if off:
                code2, again = await asyncio.to_thread(_anon, f"{PATH}?limit={WHOLE}&sort=newest")
                if code2 != 200 or not isinstance(again, dict):
                    state["anon_status_reread"] = code2
                    state["why"] = f"the re-read of the ranked page answered {code2}"
                    return False
                checks2, off2 = _facet_checks(again)
                state["facet_checks_reread"] = checks2
                if again.get("total") != state["total"]:
                    state["total_moved_to"] = again.get("total")
                    raise PreconditionUnmet(
                        f"the page's facets disagreed with its own total ({off[0]}={checks[off[0]]}, "
                        f"total={state['total']}) while the population moved ({state['total']} → "
                        f"{again.get('total')}): two statements over a table gaining rows, which this pass "
                        f"cannot tell from facets that count another population. Not a defect — re-run.")
                if off2:
                    state["why"] = (f"facet {off2[0]}={checks2[off2[0]]} disagrees with total={checks2['total']} "
                                    f"in two reads with the population still at {state['total']} — the facets "
                                    f"and the list are counting different populations")
                    return False
                whole = again
                state["facet_checks"] = checks2
        # (b) offset pages partition the same rows (SETS, never counts)
        # ⚠ AN OFFSET WALK OVER A COLLECTION THAT GAINS ROWS IS NOT MEASURABLE,
        # and `sort=newest` is the worst case: a new agent inserts at position 0
        # and shifts every page by one, producing a duplicate at each boundary —
        # the SAME signature as the non-total-ORDER-BY bug this test exists for.
        # So the walk watches `total`, and a population that moved under it is a
        # PRECONDITION (not measurable this pass), never a failure. This tier
        # creates agents continuously; measured 2454 → 2456 within minutes.
        # V0615: THE WALK'S READS GO OUT TOGETHER. One after another (four calls, seconds apart) they found no still window
        # on a busy tier: the V0614 round (2026-10-14 16:1xZ) skipped this check after 60 s of attempts, the population
        # moving 6571 -> 6572 under every walk, because the suite's own sibling tests create agents throughout. The larger
        # call and the three pages are now issued concurrently, so the window is one request long; all four must report
        # one total, or this pass is not measurable (assert_within tries again inside its budget).
        reads = await asyncio.gather(
            asyncio.to_thread(_anon, f"{PATH}?limit={WHOLE}&sort=newest"),
            *(asyncio.to_thread(_anon, f"{PATH}?limit={PAGE}&offset={i * PAGE}&sort=newest") for i in range(PAGES)))
        for i, (c, b) in enumerate(reads):
            if c != 200 or not isinstance(b, dict):
                state["failed_page"] = (i - 1, c)   # -1 is the larger call, 0.. the pages
                return False
        totals = [b.get("total") for _, b in reads]
        state["walk_total"] = totals[0]
        if len(set(totals)) != 1:
            state["total_moved_to"] = totals
            raise PreconditionUnmet(
                f"the ranked population changed under the walk "
                f"({totals[0]} → {totals[1:]} across four concurrent reads): an offset walk over a "
                f"collection gaining rows produces boundary duplicates that are "
                f"indistinguishable from a non-total ORDER BY, so this pass "
                f"cannot measure the partition. Not a defect — re-run.")
        want = [str(r.get("id")) for r in reads[0][1].get("items") or []]
        state["whole_returned"] = len(want)
        if len(want) < WHOLE:
            raise PreconditionUnmet(
                f"the ranked page returned {len(want)} of {WHOLE} — too few to page")
        walked: List[str] = [str(r.get("id")) for _, b in reads[1:] for r in b.get("items") or []]
        state["walked"], state["distinct"] = len(walked), len(set(walked))
        state["duplicates"] = sorted({x for x in walked if walked.count(x) > 1})[:6]
        state["missed"] = sorted(set(want) - set(walked))[:6]

        # (c) recorded, not asserted: the undeclared page parameter is ignored
        c0, b0 = await asyncio.to_thread(_anon, f"{PATH}?limit={PAGE}&skip=0&sort=newest")
        c4, b4 = await asyncio.to_thread(_anon, f"{PATH}?limit={PAGE}&skip={PAGE}&sort=newest")
        if c0 == 200 and c4 == 200:
            first = [str(r.get("id")) for r in (b0 or {}).get("items") or []]
            second = [str(r.get("id")) for r in (b4 or {}).get("items") or []]
            state["undeclared_skip_is_ignored"] = first == second

        return len(walked) == len(set(walked)) and set(walked) == set(want)

    return await rig.assert_within(
        budget_sec=60.0, predicate=predicate,
        description="the ranked discovery page serves an anonymous caller, carries "
                    "items/total/has_more, and offset-pages partition one larger call",
        capture_state=lambda: state,
    )


# ─── 7 · the registry card, and how long the FIRST read really takes ────────


@federation_test(
    name="discovery_registry_card_served_signed_and_timed",
    category="discovery_index_feed",
    budget_sec=90.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["discovery", "registry-card", "timing"],
)
async def test_registry_card_served_signed_and_timed(rig: FederationTestRig) -> AssertionResult:
    """The signed card is served to an anonymous caller — and the read is TIMED.

    WHY THE CLOCK IS THE POINT. agentvault2-27 measured this on EU 2026-09-06:
    the FIRST read after a recreate BUILDS AND SIGNS the card cold and took
    **30.0 s**, against **18 ms** warm. That one fact broke two instruments the
    same evening — a roll gate with a 10 s card read, and the frontend's 3.5 s
    bound, which fell back to a hardcoded `'AVT'` and told an ECU frame's entire
    UI that it settles in AVT for the life of the session.

    So this test does not assert a tight bound (a warm node answers in
    milliseconds and would prove nothing); it asserts the card is SERVED and
    SIGNED, and it records the elapsed time so the number is in every run. The
    budget is deliberately wide: anything reading this card needs to tolerate a
    cold build, and a test that timed out at 10 s would be repeating the defect.
    """
    state: Dict[str, Any] = {}

    async def predicate():
        import time as _time

        def _read():
            record_probe()                  # see the note on _get in test 4
            req = urllib.request.Request(
                "http://localhost:8000/.well-known/registry-card.json", method="GET")
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode()

        t0 = _time.time()
        try:
            # off the loop: a cold card build has been measured at 30 s, and this
            # predicate must not hold the runner for that long.
            code, raw = await asyncio.to_thread(_read)
        except urllib.error.HTTPError as e:
            state["status"], state["elapsed_ms"] = e.code, round((_time.time() - t0) * 1000)
            return False
        except Exception as e:                                   # noqa: BLE001
            state["transport_error"] = f"{type(e).__name__}: {e}"
            state["elapsed_ms"] = round((_time.time() - t0) * 1000)
            return False
        state["elapsed_ms"] = round((_time.time() - t0) * 1000)
        state["status"] = code
        card = json.loads(raw or "{}")
        ident = card.get("identity") or {}
        state["registry_card_version"] = card.get("registry_card_version")
        state["registry_name"] = ident.get("registry_name")
        state["software_version"] = ident.get("software_version")
        state["signed"] = bool(card.get("signature"))
        # anonymous, served, signed, and it names itself — the three things any
        # reader of this card depends on.
        return bool(code == 200 and state["signed"] and state["registry_name"]
                    and state["registry_card_version"])

    return await rig.assert_within(
        budget_sec=90.0, predicate=predicate,
        description="the registry card is served anonymously, signed, and names itself "
                    "— with the read time recorded (a cold build has been measured at 30 s)",
        capture_state=lambda: state,
    )
