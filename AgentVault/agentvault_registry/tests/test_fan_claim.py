"""§FANCLAIM 2026-09-07 — the coverage fan may not answer a contract's question
with an easier one.

MEASURED before the fix, on the shipped contracts:
  * 538 tools are named by a lifecycle; 261 of them hold NO contract at all
    (neither hand-curated nor autogen) and every one reported
    `has_explicit_contract=True`, because `_make_outcome` hardcoded it.
  * 81 tools whose OWN contract says `expect_status="success"` are reached only
    through an `expect_status="any"` reachability probe, so the fan wrote a
    "did anything come back" row over a "did the documented 2xx come back"
    contract and returned — the success path measured by nothing.
  * 41 of those 81 also carry an explicit `skip_reason` — a declared
    "do not sweep this" answered by a probe anyway (§MCPADMSKIP, one layer up).

The twelve tools that were reported to us (`tegSystemTransfer`, `claimTegPayouts`,
the three bridge tools, `blockFederationAgent` …) are a SAMPLE of that 81, found
by reading them one at a time. Counting the population first is what turns twelve
anecdotes into a class.

Each test carries its control: the property must be absent somewhere it should be
(RED) as well as present where it should be (GREEN).
"""
import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "api_tests"
SWEEP = SRC / "categories" / "flow_mcp_lifecycle" / "test_flow_mcp_lifecycle.py"
LIFECYCLES = SRC / "contracts" / "mcp_lifecycles.py"


# ── 1. the three fan branches must ask ONE question ─────────────────────────
def test_every_fan_branch_goes_through_the_one_verdict():
    """The guard used to be inlined three times and I fixed one copy of it earlier
    tonight (commit c2880b6) — the cloud-op numbers did not move and that silence
    was the only evidence. This is the gate for that mistake: the shared verdict is
    called once per fan branch, and NO branch reaches the raw laundering guard.

    CONTROL: the direct-call count must be 0. If someone re-inlines a branch the
    count goes to 1 and this fails — which is the whole point of asserting an
    ABSENCE rather than a presence."""
    tree = ast.parse(SWEEP.read_text())
    verdict_calls, raw_guard_calls = 0, 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "_fan_row_verdict":
                verdict_calls += 1
            if node.func.id == "_credential_laundering_guard":
                raw_guard_calls += 1
    # four branches since V0637: the central public and admin sweeps, and the cloud-op admin and (its earned
    # lifecycles, test_mcp_cloudop_earned) cloud-op public sweeps
    assert verdict_calls == 4, (
        f"expected the public, admin, cloud-op admin and cloud-op public fan branches to share one verdict; "
        f"found {verdict_calls} call(s)")
    assert raw_guard_calls == 1, (
        "the laundering guard must be reached ONLY from inside _fan_row_verdict "
        f"(found {raw_guard_calls} call sites — a branch has been re-inlined)")


def test_no_fan_branch_hardcodes_has_explicit_contract():
    """CONTROL on the excision: `has_explicit_contract=True` as a LITERAL is what
    made 261 contract-less tools claim a contract.

    Targeted STRUCTURALLY rather than by a count, because a count is a ceiling that
    goes stale and then passes loudest about what it cannot see: a fan row is the
    one that reads its fields out of the fan's dict (`skip_reason=d["skip_reason"]`),
    and only those must compute the flag. The three skip rows elsewhere that pass a
    literal True are correct — they fire BECAUSE the tool has an explicit contract."""
    tree = ast.parse(SWEEP.read_text())
    offenders, fan_rows, computed = [], [], []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "ContractOutcome"):
            continue
        kw = {k.arg: k.value for k in node.keywords}
        sr = kw.get("skip_reason")
        is_fan_row = (isinstance(sr, ast.Subscript) and isinstance(sr.value, ast.Name)
                      and sr.value.id in ("d", "_d"))
        if not is_fan_row:
            continue
        fan_rows.append(node.lineno)
        hec = kw.get("has_explicit_contract")
        if isinstance(hec, ast.Constant) and hec.value is True:
            offenders.append(node.lineno)
        if ast.unparse(hec) == "tool_name in MCP_CONTRACTS" if hec is not None else False:
            computed.append(node.lineno)
    assert not offenders, (
        f"fan row(s) at line(s) {offenders} still hardcode has_explicit_contract=True — "
        "a row claiming a contract it does not have inflates 'explicit_contracts', the "
        "number a reader uses to judge how much of the pass count was really tested")
    # and the honest expression must actually be present in every fan row. §MCPTEST30 (2026-10-01): this was a total
    # count of the expression (== 3), which went stale the day the explicit admin rows gained it too — the ceiling
    # this docstring warns about, in the gate's own last line. It asks the fan rows themselves now.
    assert len(fan_rows) >= 3 and computed == fan_rows, (fan_rows, computed)


def test_lifecycle_rows_record_the_standard_they_were_judged_by():
    """A row that does not carry its own `expect_status` cannot be told apart from a
    row that passed a real contract — the fan's whole defect in one field."""
    src = LIFECYCLES.read_text()
    assert '"probe_expect_status": expect_status' in src
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_make_outcome"]
    assert calls, "no _make_outcome call sites found — the census is measuring itself"
    for c in calls:
        kws = {k.arg for k in c.keywords}
        assert "expect_status" in kws, (
            "every _make_outcome call must pass expect_status; one that does not "
            "silently defaults to 'success' and re-creates the defect for its rows")


# ── 2. the verdict itself, with both controls ───────────────────────────────
@pytest.fixture(scope="module")
def verdict():
    import importlib
    m = importlib.import_module(
        "agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle")
    return m._fan_row_verdict


def _row(**kw):
    d = {"tool_name": "theprotocol_x", "contract_tier": "3", "healthy": True,
         "status_code": 404, "elapsed_ms": 1, "skip_reason": None, "fail_reason": None,
         "probe_expect_status": "any", "has_explicit_contract": True,
         "args_used": {}, "result_excerpt": {}}
    d.update(kw)
    return d


def test_any_probe_cannot_satisfy_a_success_contract(verdict):
    """GREEN: one of the twelve he was shown. `claimTegPayouts` has a hand contract
    demanding success and is reached only by an any-status probe."""
    out = verdict(_row(), "theprotocol_claimTegPayouts")
    assert out["healthy"] is False
    assert "NOT MEASURED" in out["skip_reason"]
    assert out["fail_reason"] is None, "an unmeasured row is a skip, never a failure"


def test_a_refusal_contract_is_answered_by_the_probe(verdict):
    """CONTROL. A contract that expects a 4xx IS satisfied by the fan's probe —
    this must stay a pass, or the fix trades one false number for another."""
    from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS
    name = next((t for t, c in MCP_CONTRACTS.items()
                 if c.expect_status in ("error_4xx", "error_5xx")), None)
    assert name, "no refusal contract in the shipped set — control cannot run"
    out = verdict(_row(), name)
    assert out["healthy"] is True, f"{name} expects a refusal; the probe answers it"
    assert out["skip_reason"] is None


def test_a_probe_held_to_success_keeps_its_pass(verdict):
    """CONTROL. A lifecycle step that ALREADY asserted success is real coverage and
    must not be downgraded — otherwise every genuine lifecycle pass disappears."""
    out = verdict(_row(probe_expect_status="success", status_code=200),
                  "theprotocol_claimTegPayouts")
    assert out["healthy"] is True
    assert out["skip_reason"] is None


def test_a_failing_probe_keeps_its_failure(verdict):
    """CONTROL. A 5xx under an any-probe is a real finding; burying it in 'not
    measured' would be this fix hiding a defect the old code caught."""
    out = verdict(_row(healthy=False, status_code=500, fail_reason="server error"),
                  "theprotocol_claimTegPayouts")
    assert out["healthy"] is False
    assert out["fail_reason"] == "server error"
    assert "NOT MEASURED" not in (out["skip_reason"] or "")


def test_an_explicit_skip_reason_is_quoted_not_replaced(verdict):
    """41 of the 81 carry a reason someone wrote deliberately. The fan overrode it;
    the verdict must SAY it rather than invent a generic sentence."""
    from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS
    c = MCP_CONTRACTS["theprotocol_claimTegPayouts"]
    assert c.skip_reason, "fixture premise changed — this tool no longer declares a skip"
    out = verdict(_row(), "theprotocol_claimTegPayouts")
    assert c.skip_reason[:40] in out["skip_reason"]


def test_success_path_unmeasured_is_a_separate_sentence_from_do_not_call(verdict):
    """§FANCLAIM's own correction, caught by my gate from earlier tonight.

    `skip_reason` means DO NOT CALL — `test_no_contradicted_admin_skips` enforces
    that by refusing to let such a tool sit in a lifecycle call batch, which is what
    stopped `adminAgoraDelistListing` being blind-swept. The seven tools this
    batch gave contracts to ARE deliberately called (against nonexistent targets),
    so writing their gap as a `skip_reason` both lied and tripped that gate. They
    say it with `success_path_unmeasured`, and the verdict must read BOTH fields.

    CONTROL: the tool must not be in the do-not-call population, or the two
    sentences are still sharing one field and nothing has been separated."""
    from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS
    # (V0549: bridgeIssueWrapped, the example until then, reaches a peer-only route and now pins its refusal; its
    # sibling bridgeRedeem is still deliberately called with its success path unmeasured)
    c = MCP_CONTRACTS["theprotocol_bridgeRedeem"]
    assert c.success_path_unmeasured, "the declaration is missing"
    assert c.skip_reason is None, (
        "a deliberately-called tool must NOT claim 'do not call' — that is the "
        "contradiction the §MCPADMSKIP-3 gate exists to find")
    out = verdict(_row(), "theprotocol_bridgeRedeem")
    assert out["healthy"] is False
    assert "redeeming a real bridge transaction" in out["skip_reason"], (
        "the verdict must quote the declared reason, not a generic sentence")


def test_all_twelve_reported_tools_are_now_declared(verdict):
    """The deliverable, asserted as a whole rather than tool by tool: none of the twelve named to us reads as a
    silent pass.

    §MCPTEST30 (V0549): six of them reach a route only a federation peer can call (the request survey's PEER_ROUTE),
    so no MCP caller has a success path to leave unmeasured: their contracts pin the refusal and run it against
    nonexistent targets (`override_coverage_fan`), which IS a measurement. The other six stay NOT MEASURED."""
    import sys
    from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS
    unmeasured = ["tegSystemTransfer", "claimTegPayouts", "authRefresh", "selectFlare",
                  "requestSelfRevocation", "bridgeRedeem"]
    still_silent = [t for t in unmeasured
                    if verdict(_row(), "theprotocol_" + t)["healthy"] is not False]
    assert not still_silent, f"still sold as a pass with nothing measuring them: {still_silent}"
    peer_only = ["blockFederationAgent", "unblockFederationAgent", "ironhandDeleteAgentProxy",
                 "bridgeIssueWrapped", "bridgeUnlock", "getCloudOperatorSelfLogs"]
    # §MCPTEST30 (V0641): three of them are said by design on their own rows now (ADMIN_PEER_ONLY_TOOLS), their
    # refusal a refusal row, so their contracts name why and pin nothing; the other three keep the pinned refusal
    said_by_design = {"blockFederationAgent", "unblockFederationAgent", "ironhandDeleteAgentProxy"}
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import test_mcp_tool_requests_meet_their_routes as gate  # noqa: PLC0415
    for t in peer_only:
        c = MCP_CONTRACTS["theprotocol_" + t]
        assert "theprotocol_" + t in gate.PEER_ROUTE_BASELINE, t
        assert c.expect_status in ("error_4xx", "error") and c.expect_error_message_contains, t
        if t in said_by_design:
            assert not c.override_coverage_fan and c.success_path_unmeasured and not c.skip_reason, t
        else:
            assert c.override_coverage_fan and not c.success_path_unmeasured and not c.skip_reason, t


def test_credential_laundering_still_wins(verdict):
    """CONTROL. The older guard must keep precedence: a row whose credential was
    dead is not 'unmeasured coverage', it is a broken probe, and conflating them
    would lose the §RUNNERCRED finding."""
    out = verdict(_row(status_code=401,
                       result_excerpt={"error": "Invalid authentication credentials"}),
                  "theprotocol_claimTegPayouts")
    assert out["healthy"] is False
    assert out["skip_reason"]


def test_a_2xx_under_an_any_probe_keeps_its_pass(verdict):
    """§FANCLAIM-2 — THE OVER-REACH, AND ITS CONTROL.

    Under `expect_status="any"`, `healthy` means only `code < 500`, so the first
    version of this verdict swept up rows whose probe actually got a **2xx** and
    declared them "no success-path coverage". False: the tool was called and it
    succeeded. What went unchecked is the contract's `expect_keys` SHAPE — a weaker
    claim, and not the same finding. Reported as a regression in the headline rate,
    correctly, on those rows.

    The class this verdict exists for is a REFUSAL sold as a pass."""
    out = verdict(_row(status_code=200), "theprotocol_claimTegPayouts")
    assert out["healthy"] is True, "a 2xx exercised the success path; it is not unmeasured"
    assert out["skip_reason"] is None


@pytest.mark.parametrize("code", [400, 404, 409, 422])
def test_a_refusal_under_an_any_probe_is_still_not_measured(verdict, code):
    """CONTROL the other way: the refusals must STILL be caught, or the correction
    has quietly deleted the fix. And the reason must name the status it saw — a
    verdict that says 'refused' without saying how is the §29e class again."""
    out = verdict(_row(status_code=code), "theprotocol_claimTegPayouts")
    assert out["healthy"] is False
    assert f"HTTP {code}" in out["skip_reason"] or "contract says:" in out["skip_reason"]
