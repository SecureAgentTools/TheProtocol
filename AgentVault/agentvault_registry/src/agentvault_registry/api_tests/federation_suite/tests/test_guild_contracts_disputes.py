"""Guild work exchange, contracts and disputes under federation (§FEDGUILD 2026-09-04).

The suite had no guild, contract or dispute-lifecycle coverage — only the
read-only staking/settlement surfaces in test_staking_and_dispute.py. These
pin the claims that federation itself can break:

  * the NETWORK board actually polls peers (peers_polled > 0)
  * a remote order reaches a frame whose OWN board is empty, carrying the
    ORIGIN frame's currency — the §FOREIGNACT law that an entity's label uses
    its own currency, never the viewer's
  * list row and detail row agree (the denormalised-render class, §SYSROW)
  * an unknown order is REFUSED, not answered as an empty object
  * guild status + dispute status/ruling are closed vocabularies
  * the contract rails enforce their auth TIER in both directions

Vocabularies are taken from the product's own source, not invented:
guild statuses from `routers/guild.py`; dispute status/ruling from the
`Dispute` model docstring in `models.py`.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
)

_MAINFRAMES = ("sandbox-A", "sandbox-B")

# routers/guild.py — every status literal the router itself uses.
_GUILD_STATUSES = {
    "open", "awarded", "submitted", "disputed", "cancelled",
    "held", "released", "resolving", "resolved", "settling", "settled",
}
# models.py::Dispute — "Current status of the dispute (OPEN, VOTING, CLOSED)"
_DISPUTE_STATUSES = {"OPEN", "VOTING", "CLOSED"}
# models.py::Dispute — ruling is null until resolved.
_DISPUTE_RULINGS = {"IN_FAVOR_OF_COMPLAINANT", "IN_FAVOR_OF_DEFENDANT", "DISMISSED"}


def _soft_error(r: Any) -> Optional[str]:
    if isinstance(r, dict) and set(r.keys()) == {"_text"} and isinstance(r["_text"], str):
        return r["_text"]
    if isinstance(r, str):
        return r
    return None


async def _call(rig, label: str, tool: str, args: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    try:
        r = await rig.mcp(label).call(tool, args)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    return r, _soft_error(r)


def _orders(r: Any) -> list:
    if isinstance(r, dict):
        return [o for o in (r.get("orders") or []) if isinstance(o, dict)]
    return [o for o in (r or []) if isinstance(o, dict)]


@federation_test(
    name="guild_network_board_polls_peers",
    category="guild_federation",
    budget_sec=25.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-B"],
    tags=["guild", "federation", "reach"],
)
async def test_guild_board_polls_peers(rig: FederationTestRig) -> AssertionResult:
    """guildNetworkBoard must actually reach across the federation.

    `peers_polled` is the board's own count of registries it asked. Zero means
    the board silently degraded to a local view — which looks identical to "no
    remote work available" from the outside. That indistinguishability is the
    whole reason this is asserted rather than eyeballed.
    """
    state: Dict[str, Any] = {}

    async def predicate():
        ok = True
        for label in _MAINFRAMES:
            r, refused = await _call(rig, label, "guildNetworkBoard", {})
            if refused or not isinstance(r, dict):
                state[label] = f"unreadable: {refused}"
                ok = False
                continue
            polled = r.get("peers_polled")
            state[label] = {"peers_polled": polled, "orders": len(_orders(r))}
            if not isinstance(polled, int) or polled < 1:
                ok = False
        return ok

    return await rig.assert_within(
        budget_sec=25.0, predicate=predicate,
        description="guild network board polls >=1 peer on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="guild_network_board_surfaces_remote_orders_with_origin_currency",
    category="guild_federation",
    budget_sec=30.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-B"],
    tags=["guild", "federation", "currency"],
)
async def test_guild_remote_orders(rig: FederationTestRig) -> AssertionResult:
    """Work posted on one frame is visible on the other's NETWORK board, and
    keeps the ORIGIN frame's currency.

    This is the guild's whole cross-registry promise in one assertion. It also
    guards the §FOREIGNACT defect: an amount rendered in the VIEWER's currency
    while the money lives on another frame. An order that travels must keep the
    unit it was posted in.

    Reports NOT MEASURED (a named skip, never a pass) when no frame has posted
    work, rather than passing over an empty population.
    """
    state: Dict[str, Any] = {}

    async def predicate():
        local: Dict[str, list] = {}
        board: Dict[str, list] = {}
        for label in _MAINFRAMES:
            lr, ref1 = await _call(rig, label, "guildListOrders", {})
            br, ref2 = await _call(rig, label, "guildNetworkBoard", {})
            if ref1 or ref2:
                state[label] = f"unreadable local={ref1} board={ref2}"
                return False
            local[label] = _orders(lr)
            board[label] = _orders(br)
            state[label] = {"local": len(local[label]), "board": len(board[label])}

        if not any(local.values()):
            state["verdict"] = "NOT MEASURED — no guild order posted on either frame"
            return False

        # Find a frame whose network board carries an order its own list lacks.
        found = None
        for label in _MAINFRAMES:
            local_ids = {o.get("id") for o in local[label]}
            for o in board[label]:
                if o.get("id") and o["id"] not in local_ids:
                    found = (label, o)
                    break
            if found:
                break
        if not found:
            state["verdict"] = "NOT MEASURED — no order appeared on a board that its own frame lacks"
            return False

        viewer, order = found
        origin = [o for lbl in _MAINFRAMES for o in local[lbl] if o.get("id") == order.get("id")]
        state["remote_order"] = {
            "seen_on": viewer, "id": order.get("id"),
            "currency_on_board": order.get("currency"),
            "currency_at_origin": origin[0].get("currency") if origin else None,
        }
        if not origin:
            state["verdict"] = "remote order has no origin row to compare currency against"
            return False
        return bool(order.get("currency")) and order["currency"] == origin[0].get("currency")

    res = await rig.assert_within(
        budget_sec=30.0, predicate=predicate, poll_interval_sec=2.0,
        description="a remote guild order reaches the peer board carrying its origin currency",
        capture_state=lambda: state,
    )
    # §TESTBED (2026-09-19): an empty population is a coverage hole (a named skip, counted against the pass
    # rate), never a defect: on a fresh frame no order exists yet, and the red read as a broken guild.
    if not res.passed and str(state.get("verdict", "")).startswith("NOT MEASURED"):
        raise PreconditionUnmet(state["verdict"])
    return res


@federation_test(
    name="guild_order_detail_agrees_with_list_row",
    category="guild_federation",
    budget_sec=25.0,
    severity="high",
    requires=["sandbox-A"],
    tags=["guild", "consistency"],
)
async def test_guild_detail_agrees(rig: FederationTestRig) -> AssertionResult:
    """guildGetOrder and guildListOrders must not disagree.

    A list row rendered from a denormalised column and a detail row read live
    is exactly how `conversations.last_preview` drifted for 318 threads: the
    fix reached only rows written after it. Comparing the two is the cheapest
    detector for that class.
    """
    state: Dict[str, Any] = {}
    FIELDS = ("bounty", "currency", "status", "title")

    # ⚠ Precondition BEFORE the poller. assert_within CATCHES predicate
    # exceptions and retries to budget, so a PreconditionUnmet raised inside
    # predicate() is swallowed and the test still burns its budget and goes red.
    # §FEDBETA: on a FRESH frame there is simply no order to compare, and a red
    # row there says "this frame is broken" when it means "this frame is new" —
    # 14 of the mirrored Beta run's 43 failures are absence-of-history.
    _pre, _pre_ref = await _call(rig, "sandbox-A", "guildListOrders", {})
    if not _pre_ref and not _orders(_pre):
        raise PreconditionUnmet(
            "no guild order posted on this frame — nothing to compare "
            "list-vs-detail against")

    async def predicate():
        lr, refused = await _call(rig, "sandbox-A", "guildListOrders", {})
        if refused:
            state["verdict"] = f"unreadable: {refused}"
            return False
        rows = _orders(lr)
        if not rows:
            state["verdict"] = "orders vanished mid-run"
            return False
        row = rows[0]
        dr, ref2 = await _call(rig, "sandbox-A", "guildGetOrder", {"order_id": row.get("id")})
        if ref2:
            state["verdict"] = f"detail refused for a listed order: {ref2}"
            return False
        detail = dr.get("order") if isinstance(dr, dict) and "order" in dr else dr
        if not isinstance(detail, dict):
            state["verdict"] = f"detail shape {type(detail).__name__}"
            return False
        diffs = {f: {"list": row.get(f), "detail": detail.get(f)}
                 for f in FIELDS if row.get(f) != detail.get(f)}
        state["order_id"] = row.get("id")
        state["diffs"] = diffs
        return not diffs

    return await rig.assert_within(
        budget_sec=25.0, predicate=predicate,
        description="guild list row and detail row agree on bounty/currency/status/title",
        capture_state=lambda: state,
    )


@federation_test(
    name="guild_unknown_order_is_refused",
    category="guild_federation",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["guild", "negative"],
)
async def test_guild_unknown_order(rig: FederationTestRig) -> AssertionResult:
    """An unknown order id is refused 404 — never an empty order object."""
    state: Dict[str, Any] = {}

    async def predicate():
        r, refused = await _call(rig, "sandbox-A", "guildGetOrder",
                                 {"order_id": "gwo_federationsuite_does_not_exist"})
        state["refused"] = refused
        state["raw"] = None if refused else str(r)[:200]
        if not refused:
            return False
        return "404" in refused or "not found" in refused.lower() or "not_found" in refused.lower()

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="unknown guild order id refused 404 rather than answered empty",
        capture_state=lambda: state,
    )


@federation_test(
    name="guild_order_status_is_a_closed_vocabulary",
    category="guild_federation",
    budget_sec=25.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["guild", "vocabulary"],
)
async def test_guild_status_vocabulary(rig: FederationTestRig) -> AssertionResult:
    """Every live guild status is one `routers/guild.py` itself uses.

    A status the router never writes means either a new state shipped without
    the vocabulary being updated, or a foreign frame is speaking a dialect this
    one does not share — both worth a red build.
    """
    state: Dict[str, Any] = {}

    async def predicate():
        seen: set = set()
        counted = 0
        for label in _MAINFRAMES:
            for tool in ("guildListOrders", "guildNetworkBoard"):
                r, refused = await _call(rig, label, tool, {})
                if refused:
                    continue
                for o in _orders(r):
                    if o.get("status"):
                        seen.add(o["status"])
                        counted += 1
        state["orders_examined"] = counted
        state["statuses_seen"] = sorted(seen)
        if counted == 0:
            state["verdict"] = "NOT MEASURED — no order carried a status on either frame"
            return False
        unknown = seen - _GUILD_STATUSES
        state["unknown"] = sorted(unknown)
        return not unknown

    res = await rig.assert_within(
        budget_sec=25.0, predicate=predicate,
        description="every live guild order status is in the router's own vocabulary",
        capture_state=lambda: state,
    )
    # §TESTBED (2026-09-19): an empty population is a coverage hole (a named skip, counted against the pass
    # rate), never a defect: on a fresh frame no order exists yet, and the red read as a broken guild.
    if not res.passed and str(state.get("verdict", "")).startswith("NOT MEASURED"):
        raise PreconditionUnmet(state["verdict"])
    return res


@federation_test(
    name="contract_rails_enforce_agent_tier",
    category="guild_federation",
    budget_sec=25.0,
    severity="high",
    requires=["sandbox-A"],
    tags=["contracts", "auth", "negative"],
)
async def test_contract_tier_boundary(rig: FederationTestRig) -> AssertionResult:
    """The contract rail is AGENT-tier and the dispute rail is DEVELOPER-tier.

    Both legs are required: a developer JWT must be REFUSED by getMyContracts
    and ACCEPTED by getMyDisputes. A one-legged version of this test would pass
    if the tier map collapsed and everything started refusing — which is how
    `/developers/me/exchange/portfolio` inherited the agent tier by substring
    and 401'd in the browser while working from a script.
    """
    state: Dict[str, Any] = {}

    async def predicate():
        c, c_ref = await _call(rig, "sandbox-A", "getMyContracts", {})
        state["getMyContracts"] = {"refused": c_ref, "raw": None if c_ref else str(c)[:120]}
        agent_tier_enforced = bool(c_ref) and ("401" in c_ref or "403" in c_ref
                                               or "auth" in c_ref.lower())

        d, d_ref = await _call(rig, "sandbox-A", "getMyDisputes", {})
        state["getMyDisputes"] = {"refused": d_ref,
                                  "shape": type(d).__name__ if not d_ref else None}
        dev_tier_allowed = (not d_ref) and isinstance(d, dict)

        state["verdict"] = {"agent_tier_enforced": agent_tier_enforced,
                            "dev_tier_allowed": dev_tier_allowed}
        return agent_tier_enforced and dev_tier_allowed

    return await rig.assert_within(
        budget_sec=25.0, predicate=predicate,
        description="developer JWT refused by the agent-tier contract rail, accepted by the dispute rail",
        capture_state=lambda: state,
    )


@federation_test(
    name="dispute_status_and_ruling_are_typed_and_terminal",
    category="guild_federation",
    budget_sec=25.0,
    severity="high",
    requires=["sandbox-A"],
    tags=["disputes", "vocabulary"],
)
async def test_dispute_typing(rig: FederationTestRig) -> AssertionResult:
    """Dispute status is a closed set, and a CLOSED dispute carries a ruling.

    "Closed with no ruling" is the shape that made `running` mean two things in
    agent_deployments — a status word that reads terminal while carrying none
    of the terminal state. If a dispute can close without a ruling, every
    downstream consumer of the outcome is reading a hole.
    """
    state: Dict[str, Any] = {}

    # Precondition BEFORE the poller — see the note above.
    _pre, _pre_ref = await _call(rig, "sandbox-A", "getMyDisputes", {})
    if not _pre_ref and isinstance(_pre, dict) and not (_pre.get("disputes") or []):
        raise PreconditionUnmet(
            "no dispute rows on this frame — the status/ruling vocabulary has "
            "nothing to be checked against")

    async def predicate():
        r, refused = await _call(rig, "sandbox-A", "getMyDisputes", {})
        if refused or not isinstance(r, dict):
            state["verdict"] = f"unreadable: {refused}"
            return False
        rows = [d for d in (r.get("disputes") or []) if isinstance(d, dict)]
        state["examined"] = len(rows)
        if not rows:
            state["verdict"] = "disputes vanished mid-run"
            return False

        bad_status = sorted({d.get("status") for d in rows
                             if d.get("status") not in _DISPUTE_STATUSES})
        closed = [d for d in rows if d.get("status") == "CLOSED"]
        closed_without_ruling = [d.get("id") for d in closed if not d.get("ruling")]
        bad_ruling = sorted({d.get("ruling") for d in rows
                             if d.get("ruling") and d.get("ruling") not in _DISPUTE_RULINGS})

        state["bad_status"] = bad_status
        state["closed"] = len(closed)
        state["closed_without_ruling"] = closed_without_ruling
        state["bad_ruling"] = bad_ruling
        return not bad_status and not closed_without_ruling and not bad_ruling

    return await rig.assert_within(
        budget_sec=25.0, predicate=predicate,
        description="dispute statuses/rulings are typed and every CLOSED dispute has a ruling",
        capture_state=lambda: state,
    )
