"""The skip census's families, with the control table that caught its first bug.

§SKIPCENSUS 2026-09-06 — the operator sweeps reported `642 passed / 113 skipped`
and nothing else. A bare count is exactly the state the FEDERATION suite was in
before its taxonomy, and reading those skips by hand is what found two live
defects. So the sweeps now census their skips into families derived from the
reasons the module and the contract table actually emit.

⚠ THIS FILE EXISTS BECAUSE THE FIRST VERSION WAS WRONG AND ONLY A CONTROL TABLE
COULD SAY SO. `db_debris`'s own reason ends "Cover in destructive bucket", which
a bare /destructive/ in the `destructive_infra` family swallowed — first match
wins. The families are ORDERED, and an ordering is a thing you can only test by
naming the expected answer for every family at once.

The reasons below are REAL: each is a literal grepped out of
`test_flow_mcp_lifecycle.py` or `contracts/mcp_contracts.py`. A fixture written
from a family's description would test the description.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_CENSUS_TESTS") == "0",
    reason="explicitly disabled",
)

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import (  # noqa: E402
    classify_tool_skip, skip_census, _SKIP_FAMILIES,
)

# (real skip_reason, the family it must land in)
CASES = [
    ("provisions a REAL cloud operator (containers) — destructive/heavy infra op.",
     "destructive_infra"),
    ("destructive teardown of provisioned infra.", "destructive_infra"),
    ("provisions a WHOLE frame — heavy infra op.", "destructive_infra"),
    ("provisions a chained operator topology — heavy infra op.", "destructive_infra"),
    ("recursive/heavy — runs an api-test flow; re-invokes the tester.",
     "recursive_tester"),
    ("recursive — admin endpoint that re-invokes the API tester itself; would loop",
     "recursive_tester"),
    ("Creates a new developer row — leaves DB debris. Cover in destructive bucket.",
     "db_debris"),
    ("Creates a new agent — covered by /admin/api-test/sandbox-credentials reset.",
     "db_debris"),
    ("cloud-op admin contract_gap — no expect_keys nor outputSchema.required "
     "(Phase 2 — admin contract synthesis)", "cloudop_admin_contract_gap"),
    ("cloud-op tier-2 fixture missing: no sentinel JWT (Phase 2 — synthetic agent "
     "bootstrap)", "cloudop_no_sentinel_jwt"),
    ("default contract: tool has required params {'agent_did'} — add explicit contract",
     "default_contract_required_params"),
    ("phase-3 fixture missing: 'contract_v2_id' — entity setup didn't expose this ID",
     "phase3_fixture_missing"),
    ("Phase-3: needs a known distribution_id fixture.", "phase3_fixture_missing"),
    ("mainframe-only — sandbox is not a mainframe; covered by prod gate",
     "mainframe_only"),
    ("No pagination — returns ALL pending (BUG-18). Re-enable when paginated.",
     "known_product_gap"),
    ("needs a live listing_ref + mutates halt state; resolve dynamically",
     "needs_live_entity"),
    ("heavy — kicks api-tester eager bootstrap (side effects).", "heavy"),
    # ── the families the DECLARED contract table uses (all real strings) ─────
    ("EVTYPES2 probed: the tool sends a body missing a field the endpoint "
     "requires (observed: 422 'Field required')", "tool_contract_defect"),
    ("EVTYPES2 probed: the MCP tool declares proposal_id as an INTEGER while the "
     "EventStore route parses it as a string", "tool_contract_defect"),
    ("EVTYPES2: not probed - would change the sweep's own password mid-run",
     "self_state_mutation"),
    ("EVTYPES2: not probed - acts on the CALLER's session - a probe would log the "
     "sweep out mid-run", "self_state_mutation"),
    ("EVTYPES2: not probed - revokes the calling agent's own identity",
     "self_state_mutation"),
    ("EVTYPES2: not probed - rotates this registry's federation licence",
     "self_state_mutation"),
    ("EVTYPES2: not probed - mints a real API key", "self_credential_or_sentinel"),
    ("EVTYPES2: not probed - could revoke the key the sweep is authenticating with",
     "self_credential_or_sentinel"),
    ("EVTYPES2: not probed - deletes the sentinel agent every later tool depends on",
     "self_credential_or_sentinel"),
    ("EVTYPES2: not probed - moves value from the payout pool", "moves_value"),
    ("EVTYPES2: not probed - moves value: fires a lock payout distribution", "moves_value"),
    # §MCPTEST30 W6 (2026-10-25): a distribution or a pool in its old or its new words, also without "moves value"
    # (the line above is the real literal; these two hold the family's other alternatives to account)
    ("EVTYPES2: not probed - fires a staking distribution", "moves_value"),
    ("EVTYPES2: not probed - fires a lock payout distribution", "moves_value"),
    ("EVTYPES2: not probed - moves value: it unlocks the caller's matured bond share (escrow -> funder, once per bond) and takes no entity argument, so there is nothing non-existent to aim at. Proven through the real dispatcher by tests/test_mcp_unlock_bond_wire.py.", "moves_value"),
    ("EVTYPES2: not probed - PROVISIONING - HIS word", "provisioning_his_word"),
    ("DESTRUCTIVE — cancels all orders + refunds escrow (exchange.py:1058)",
     "destructive_entity"),
    ("EVTYPES2: not probed - writes agent liveness state the health checker reads",
     "mutates_shared_state"),
    ("EVTYPES2: not probed - kicks the federation sync worker for the whole node",
     "mutates_shared_state"),
    ("EVTYPES2: takes no entity argument, so there is nothing non-existent to aim at",
     "no_entity_to_aim_at"),
    ("EVTYPES6: the nodes DO differ here, but not by node CLASS — by DATA",
     "data_not_class_difference"),
    # ── from the FIRST census run against the real 114 (2026-09-07) ──────────
    # Both verbatim: the two skips the table could not name on its first outing.
    ("cloud-op flag-gated: A2A_DID_JWT_AUTOGEN unset, so agents carry no "
     "registered public key. MEASURED unset on this operator",
     "cloudop_lacks_frame_fixture_or_flag"),
    ("cloud-op fixture unavailable: the review grant in API_TEST_SUPPORT_GRANT_ID "
     "is seeded on the FRAME (1 row) and this operator has none",
     "cloudop_lacks_frame_fixture_or_flag"),
    # §GUILDDARK 2026-09-07 — the guild fixture, both measured states. Verbatim
    # from the sweep, which is the only reason a family test means anything.
    ("cloud-op fixture unavailable: ['guild_order_id'] — GUILD_ENABLED unset — The "
     "Guild is disabled on this registry (MEASURED 503). The fixture cannot exist "
     "here at all; this is a node-class difference, not missing setup.",
     "cloudop_lacks_frame_fixture_or_flag"),
    ("cloud-op fixture unavailable: ['guild_order_id'] — the Guild is ENABLED here "
     "but this operator holds no orders of its own (0 local), and network-board ids "
     "are federated — `GET /guild/orders/{id}` answers 404 for them (measured). "
     "Posting one costs a bounty the operator treasury cannot fund (B8)",
     "cloudop_lacks_frame_fixture_or_flag"),
    # §MCPTEST30 (V0644): the same skip on a FUNDED operator names its real cause (the sweep stages no orders there)
    ("cloud-op fixture unavailable: ['guild_order_id'] — the Guild is ENABLED here "
     "but this operator holds no orders of its own (0 local), and network-board ids "
     "are federated — `GET /guild/orders/{id}` answers 404 for them (measured). "
     "this sweep stages no guild orders on an operator (a frame's phase-3 posts its own, each escrowing a "
     "bounty); the operator treasury reads 292,937.38, so B8 is not the cause",
     "cloudop_lacks_frame_fixture_or_flag"),
    # §RUNNERCRED 2026-09-07 — verbatim from the guard.
    ("lifecycle recorded a 401 as healthy — the step ran under expect_status='any' "
     "while this tool's contract expects SUCCESS, so the success path was not "
     "measured. The body says: {\"_text\": \"Error: HTTP 401: Could not validate "
     "credentials\"}", "lifecycle_4xx_sold_as_pass"),
    ("lifecycle recorded a 403 as healthy — the step ran under expect_status='any' "
     "while this tool's contract expects SUCCESS, so the success path was not "
     "measured. The body says: (no excerpt)", "lifecycle_4xx_sold_as_pass"),
    # §MCPSWEEP 2026-09-27 — the two sentences mcp_lifecycles._dispatcher_refusal_skip writes, verbatim in shape
    ("probe never reached the tool: the dispatcher answered invalid params (Invalid params: reinstate_developer() got "
     "an unexpected keyword argument 'reason') before 'theprotocol_reinstateDeveloper' ran — a tester defect: send "
     "the arguments its inputSchema declares", "probe_never_reached_tool"),
    ("probe never reached the tool: the bridge answered tool not found (Tool not found: 'theprotocol_revokeFrame'. "
     "Use tools/list to see available tools.); an admin tool is measured by the admin lifecycle on the admin bridge, "
     "not here", "probe_never_reached_tool"),
]

# §MCPTEST30 (V0545): the probe rows' own sentences, verbatim from the probes (round 11 and V0545)
CASES += [
    ("NOT MEASURED: the list is empty (0 rows), so no detail can be asked", "probe_not_measured"),
    ("NOT MEASURED: 2 row(s), none carrying `id`", "probe_not_measured"),
    ("NOT MEASURED: every detail answer was a designed step (refused 409), so none showed the row", "probe_not_measured"),
    ("NOT MEASURED: the list moved between two identical reads (a row came or went during the probe), so two pages "
     "cannot be compared with one", "probe_not_measured"),
    ("NOT MEASURED: 0 row(s), no second page of 3 to compare", "probe_not_measured"),
    ("NOT MEASURED: the unfiltered list is empty or unreadable, so no filter can be judged", "probe_not_measured"),
    ("NOT MEASURED: the sentinel's contract is an open offer, which any agent may read by design", "probe_not_measured"),
    # a step whose answer never arrived (V0545, mcp_lifecycles.lost_answer_sentence): its own family, not a probe's
    ("NOT MEASURED: no HTTP status came back for theprotocol_getArenaMatchMap (the answer was lost in transit; the "
     "server may have answered)", "transport_lost"),
    ("NOT MEASURED: no HTTP status came back for theprotocol_transferUnits (curl reached no server: 000)",
     "transport_lost"),
]


def test_a_probe_sentence_never_hides_a_family_above_it():
    """probe_not_measured is LAST: a reason an earlier family names keeps that family even when it opens the same way."""
    assert [c for c, _p, _m in _SKIP_FAMILIES][-1] == "probe_not_measured"
    assert classify_tool_skip("phase-3 fixture: NOT MEASURED: later") == "phase3_fixture_missing"
    assert classify_tool_skip("a reason that mentions NOT MEASURED: in its middle") == "unclassified", "anchored"


# Families produced at RUN time by the sweep rather than declared in the contract
# table — the distinguishability check must not demand a declared example.
_RUNTIME_ONLY = {
    "cloudop_admin_contract_gap",
    "cloudop_no_sentinel_jwt",
    "default_contract_required_params",
    "phase3_fixture_missing",
}


@pytest.mark.parametrize("reason,expected", CASES)
def test_every_real_reason_lands_in_its_family(reason, expected):
    assert classify_tool_skip(reason) == expected


def test_an_unknown_reason_is_unclassified_not_silently_bucketed():
    """The whole point: a skip nobody has read must SAY so.

    A classifier that finds a home for everything is the `or True` of taxonomies
    — it can never tell you there is something new to look at.
    """
    assert classify_tool_skip("a reason invented after this table was written") == "unclassified"
    assert classify_tool_skip("") == "unclassified"
    assert classify_tool_skip(None) == "unclassified"


def test_the_families_are_distinguishable_from_each_other():
    """No family may be unreachable behind an earlier one.

    This is the leg that caught the real bug: `db_debris` was ordered after
    `destructive_infra`, whose pattern matched the word "destructive" inside
    db_debris's own text. Ordering bugs are invisible one case at a time.
    """
    landed = {classify_tool_skip(r) for r, _ in CASES}
    declared = {code for code, _p, _m in _SKIP_FAMILIES}
    unreachable = declared - landed - _RUNTIME_ONLY
    assert not unreachable, (
        f"families no real reason reaches: {sorted(unreachable)} — either they are "
        f"dead, or an earlier pattern is swallowing them")


class _Outcome:
    def __init__(self, tool_name, skip_reason):
        self.tool_name = tool_name
        self.skip_reason = skip_reason


def test_census_counts_only_real_skips_and_surfaces_examples():
    out = [
        _Outcome("provisionCloudOperator", "provisions a WHOLE frame — heavy infra op."),
        _Outcome("runAllApiTests", "recursive — would loop"),
        _Outcome("somethingNew", "a reason invented after this table was written"),
        _Outcome("healthyTool", None),          # not a skip at all
    ]
    c = skip_census(out)
    assert sum(c["skip_census"].values()) == 3, "an outcome with no skip_reason is not a skip"
    assert c["skip_census"]["unclassified"] == 1
    assert any("somethingNew" in e for e in c["unclassified_examples"]), (
        "an unclassified skip must carry an EXAMPLE — without one, a reader cannot "
        "write the next family, which is how skips sit unread")
    # meanings are published only for families the run actually used, so the
    # summary does not carry a glossary of things that did not happen.
    assert set(c["skip_code_meanings"]) <= set(c["skip_census"])
    assert "unclassified" not in c["skip_code_meanings"]


def test_census_is_empty_for_a_run_with_no_skips():
    """An empty census must be empty — not absent, and not a zero-filled glossary."""
    c = skip_census([_Outcome("a", None), _Outcome("b", None)])
    assert c["skip_census"] == {}
    assert c["skip_code_meanings"] == {}
    assert c["unclassified_examples"] == []
