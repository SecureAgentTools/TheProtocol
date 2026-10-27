"""§MCPTEST30 V0643 (agentvault2-aa, 2026-10-25): a refusal-only row says its by-design reason where one is known.

His rule of 2026-10-19 (no softened failure class) and the backlog's V0642 candidate (BACKLOG_2026-10-19_MCP_REFUSAL_ONLY_
PASSES.md: "the frame's pinned refusal-only rows say their own reason"). The frame's 41 refusal-only rows of V0641's pair
nt261025x3 (run 2a89a516f8d94077) read one generic sentence; each now names why its success path is not driven
(api_tests/contracts/refusal_reasons.py). The flow puts the reason on the row it hands the router (both the frame's and a
cloud operator's rows), the router says it, and nothing else moves: the same rows count as not measured, the refusal is
still measured, a tool earned anywhere in the run shows nothing, and a row with no known reason keeps the generic sentence.
"""
from __future__ import annotations

import inspect

from agentvault_registry.api_tests.contracts import refusal_reasons as R
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.routers import mcp_tester
from agentvault_registry.routers.mcp_tester import _REFUSAL_ONLY_REASON, _apply_refusal_only, refusal_only_reason

# the frame's refusal-only tools of nt261025x3 (scratchpad/mcpgaps/nt261025x3_frame_refusal_only.json)
NT261025X3_FRAME = """acknowledgeAgentFlag adminDownloadOperatorBundle adminGrafanaQuery approveFrameInvitation
approveOperatorApplication blacklistRegistry completeAdmission deleteFederationLicense deleteOauthFederationTrust
federationCliAudit federationPolicyUpdateRequest finalizeRetryFrameInvitation fireCanaryPath forceEmailVerify liftQuarantine
quarantineRegistry refundFiatPurchase reinstateFederationLicense reinstateOperator rejectOperatorApplication
replayFiatPurchase resendFiatMagicLink resyncFrameEventStore revokeFederationLicense revokeFrame revokeOperatorAccess
rotateOperatorPullToken simulationFundingPreview suspendFederationLicense suspendOperator tegTreasuryMint toggleCanaryPath
triggerDiagnosticAction updateEnforcementPolicy uploadRegistryCardIcon getOperatorMyBundle oauthIntrospect oauthRevoke
oauthTokenExchange operatorPortalSelfLogs requestFrame""".split()


def _row(tool, status=200, healthy=True, declared=None):
    return {"tool": tool, "status": status, "healthy": healthy, "skipped": False, "skip_reason": None,
            "switched_off": None, "has_explicit_contract": True, "declared_unmeasured": declared}


# §MCPTEST30 V0644 (agentvault2-66): the operators' own refusal-only tools outside the frame's 41, a second pinned set
# (V0641's read of both sandbox operators: acceptComplianceBaseline, guildCrossRegistryBid, slashAgentStake, now
# slashAgent; logTegDispute left the set, earned on an operator since V0644)
OPERATORS_V0641 = """acceptComplianceBaseline guildCrossRegistryBid slashAgent""".split()
# §MCPTEST30 V0644 (agentvault2-aa's word 2026-10-26): three sandbox-only routes, which SANDBOX_MODE (a sandbox
# frame's switch, unset on an operator) opens; on an operator each row says why
OPERATORS_SANDBOX_ONLY = """previewVotingPowerAttestation runAttestationExpirySweep runAttestationScheduleCron""".split()


def test_every_one_of_the_frames_41_has_its_reason():
    assert len(NT261025X3_FRAME) == 41 and not set(NT261025X3_FRAME) & set(OPERATORS_V0641 + OPERATORS_SANDBOX_ONLY)
    assert set(R.BY_DESIGN_REFUSAL) == {"theprotocol_" + t for t in NT261025X3_FRAME + OPERATORS_V0641
                                         + OPERATORS_SANDBOX_ONLY}
    for tool, why in R.BY_DESIGN_REFUSAL.items():
        assert why and why[0].islower() and not why.endswith(".") and "—" not in why, tool
    assert R.declared("theprotocol_tegTreasuryMint").startswith("minting is never automated")
    assert R.declared("theprotocol_getMyBalance") is None and R.declared("") is None


def test_the_operators_own_three_say_why_on_an_operator():
    # each names what an operator lacks, the switch or the lifecycle, so the label holds where it shows
    says = {t: R.declared("theprotocol_" + t) for t in OPERATORS_V0641}
    assert "IS_CENTRAL_REGISTRY" in says["acceptComplianceBaseline"]
    assert "earned_guild_cross_registry" in says["guildCrossRegistryBid"]
    assert "STAKING_ENABLED=false" in says["slashAgent"]
    assert R.declared("theprotocol_logTegDispute") is None, "earned on an operator since V0644, so no label"


def test_the_sandbox_only_three_say_why_on_an_operator():
    for t in OPERATORS_SANDBOX_ONLY:
        why = R.declared("theprotocol_" + t)
        assert why.startswith("a sandbox-only route") and "SANDBOX_MODE" in why, t


def test_the_lifecycles_403_on_a_sandbox_only_route_carries_the_reason():
    # the guard that turns a lifecycle's healthy 403 into NOT MEASURED keeps its own sentence (its census family)
    # and adds the by-design reason where one is declared; a tool with none reads as before (the control)
    row = {"healthy": True, "status_code": 403, "result_excerpt": {"_text": "Error: HTTP 403: sandbox-only endpoint"}}
    said = F._credential_laundering_guard(row, "theprotocol_previewVotingPowerAttestation")
    assert said.startswith("lifecycle recorded a 403 as healthy")
    assert "By design: a sandbox-only route" in said and "sandbox-only endpoint" in said
    plain = F._credential_laundering_guard(row, "theprotocol_getMyBalance")
    assert plain is None or "By design" not in plain


def test_a_refusal_only_row_says_its_reason_and_counts_as_before():
    why = R.declared("theprotocol_revokeFrame")
    rows = [_row("theprotocol_revokeFrame", 404, declared=why),               # refusal only, a reason
            _row("theprotocol_rotateAgentCredentials", 404),                  # refusal only, no reason
            _row("theprotocol_suspendOperator", 404, declared=R.declared("theprotocol_suspendOperator")),
            _row("admin_effect: suspendOperator", 200)]                        # earned: nothing to say
    summary, skipped = {"passed": 4, "skipped": 0, "tool_count": 4, "pass_pct": 100.0}, []
    n = _apply_refusal_only(rows, summary, skipped)
    assert n == 2 and summary["refusal_only"] == 2 and summary["passed"] == 2
    assert rows[0]["skip_reason"] == f"refusal only, by design: {why}; the refusal is measured, the success path is not"
    assert rows[1]["skip_reason"] == _REFUSAL_ONLY_REASON
    assert rows[2].get("refusal_only") is not True and rows[2]["skip_reason"] is None
    assert [s["reason"] for s in skipped] == [rows[0]["skip_reason"], _REFUSAL_ONLY_REASON]
    assert refusal_only_reason({"declared_unmeasured": "  "}) == _REFUSAL_ONLY_REASON


def test_the_flow_puts_the_reason_on_both_runs_rows_and_the_router_carries_it():
    src = inspect.getsource(F)
    assert src.count('"declared_unmeasured": _refusal_reasons.declared(o.tool_name),') == 2, "the frame's and an operator's"
    router = inspect.getsource(mcp_tester)
    assert '"declared_unmeasured": (rr.get("responseData") or {}).get("declared_unmeasured"),' in router
    assert "why = refusal_only_reason(r)" in router
