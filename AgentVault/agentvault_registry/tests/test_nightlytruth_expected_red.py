"""§NIGHTLYTRUTH (2026-09-14) — a red row carries its state, and a row red BY DESIGN is listed apart.

Two of the nightly's eleven standing reds are documented findings (§FEDPROOF F2 and F7) that stay red until
the product changes; before this they sat in `hard_fails` beside the new reds, indistinguishable, and the
rows whose reason read "budget exhausted" carried no state at all. Now `@federation_test(expected_red=...)`
travels spec -> outcome -> runner row -> the tester's projection, which splits `hard_fails` (new) from
`expected_reds` (documented) and keeps `last_state` on both.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite import decorator as dec
from agentvault_registry.api_tests.federation_suite.tests import test_federation_mechanisms_driven as drv
from agentvault_registry.routers.mcp_tester import _bounded_state, _hard_fail_row, _split_red_rows


def _spec(name, expected_red=None):
    async def _run(rig):  # pragma: no cover - never invoked
        return None
    return dec.FederationTestSpec(name=name, category="c", budget_sec=1.0, severity="low", requires=[], tags=[], runner=_run,
                                  expected_red=expected_red)


def test_the_outcome_dict_carries_the_declaration():
    o = dec.TestOutcome(spec=_spec("t", "§X: red until Y"), state="failed", arrange_ms=0, act_ms=1, propagation_ms=0, total_ms=1,
                        failure_detail="budget exhausted", last_state={"peer": 4})
    d = o.to_dict()
    assert d["expected_red"] == "§X: red until Y" and d["last_state"] == {"peer": 4}
    assert dec.TestOutcome(spec=_spec("u"), state="failed", arrange_ms=0, act_ms=1, propagation_ms=0, total_ms=1).to_dict()["expected_red"] is None


def test_the_two_by_design_rows_declare_their_findings():
    by_name = {s.name: s for s in dec.REGISTRY}
    # §SUITES1018 (2026-10-18): §FEDPROOF F2 is fixed (the recorder counts an inbound FX-booth settlement on its own
    # side, one normalizer for both keys), so the row is red only when it fails, and it now proves the counter moved for
    # ITS settlement, not for whichever settlement moved it within the budget (it passed by coincidence with the sim on)
    assert not by_name["peer_trust_counters_move_on_both_sides_after_one_settlement"].expected_red
    # §MCPTEST30 (V0555): F7 is closed by §MEMBERSHIP D2's federal ballots; the row drives the ballot path and is red
    # only when it fails (switched off, it reads NOT MEASURED and says so)
    assert not by_name["federation_elevation_reaches_the_peer_floor"].expected_red
    assert drv is not None
    undeclared = [s.name for s in dec.REGISTRY if s.expected_red and "FINDINGS_" not in s.expected_red]
    assert undeclared == [], f"an expected_red must name its findings file: {undeclared}"


def _row(name, healthy, expected_failure=False, last_state=None, expected_red=None, error="budget 30.0s exhausted"):
    return {"name": f"federation_suite: c/{name}", "healthy": healthy, "expected_failure": expected_failure, "error": error,
            "responseData": {"name": name, "last_state": last_state, "expected_red": expected_red}}


def test_the_projection_keeps_the_state_and_splits_the_documented_reds():
    rows = [
        _row("green", True),
        _row("skip", False, expected_failure=True),
        _row("new_red", False, last_state={"dash_total": 12, "devs_total": 14}),
        _row("documented", False, last_state={"home": 20, "peer": 4}, expected_red="§FEDPROOF F2 (FINDINGS_2026-09-13_FEDPROOF.md)"),
    ]
    hard, expected = _split_red_rows(rows, lambda rr: rr["responseData"]["name"])
    assert [r["tool"] for r in hard] == ["new_red"] and hard[0]["last_state"] == {"dash_total": 12, "devs_total": 14}
    assert [r["tool"] for r in expected] == ["documented"] and expected[0]["expected_red"].startswith("§FEDPROOF F2")
    assert "last_state" not in _hard_fail_row("x", _row("x", False)), "no state captured -> no key"


def test_a_captured_state_is_bounded_for_the_run_record():
    big = {"text": "y" * 5000, "list": list(range(100)), "nested": {"k": object()}, "n": 3, "ok": None}
    b = _bounded_state(big)
    assert len(b["text"]) == 401 and len(b["list"]) == 20 and isinstance(b["nested"]["k"], str) and b["n"] == 3 and b["ok"] is None
