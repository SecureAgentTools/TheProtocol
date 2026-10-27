"""§MCPTEST30 W6 (agentvault2-aa, 2026-10-25): the MCP tester reads the critical words on the MCP surface.

His words that day to agentvault2-69: "i want the illegal wording completly gone before opening"
(sessionlogs2026/PLAN_2026-10-25_COMPLIANT_OPENING.md, W6). The listings: a listed tool whose name or description names a
critical word fails its own row, and so does a renamed tool's old name still listed (read from the listing: calling an old
name would count kind="mcp_w3", the instrument for dropping the old names). The answers: every answer is scanned and the
census row names the tools whose answers carry a word, judging nothing yet. Words, never identifiers: TokensTransferred,
staked_balance and getMyEarnings inside a sentence are names, not words.
"""
from __future__ import annotations

import inspect

from agentvault_registry.api_tests.contracts import critical_words as W
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F


def _row(tool, healthy=True, skip=None):
    return F.ContractOutcome(tool_name=tool, contract_tier="explicit", healthy=healthy, status_code=200, elapsed_ms=1,
                             skip_reason=skip, fail_reason=None, has_explicit_contract=True, args_used={},
                             result_excerpt={})


def test_the_words_and_the_kept_senses():
    for s in ["Claim your staking rewards", "APY", "a yield optimizer", "the IPO", "investors", "Earnings", "crypto",
              "insurance products", "tokenomics", "the token economy", "staked units", "returns on your units", "shares"]:
        assert W.in_text(s), s
    for s in ["Locked units", "earn their trust", "non-profit use", "cryptographic proof", "investigating",
              "the remainder returns to the client", "a bootstrap token", "the OAuth access token", "an API token",
              "the TokensTransferred event", "staked_balance", "learn more", "getMyEarnings answers", "a bounty"]:
        assert W.in_text(s) == [], s


def test_a_tools_name_is_read_as_words():
    assert W.in_name("theprotocol_getMyEarnings") == ["earnings"]
    assert W.in_name("theprotocol_stakeTokens") == ["stake"]
    assert W.in_name("theprotocol_getApyRates") == ["apy"]
    for n in ("theprotocol_lockUnits", "theprotocol_getAgentToken", "theprotocol_getMyIncome", "theprotocol_transferUnits"):
        assert W.in_name(n) == [], n


def test_the_listing_findings_and_the_old_names():
    tools = [{"name": "theprotocol_lockUnits", "description": "Lock units for a proposal."},
             {"name": "theprotocol_getMyEarnings", "description": "Your income."},
             {"name": "theprotocol_getLockPayoutTiers", "description": "The payout rate, with an APY figure."},
             {"name": "theprotocol_stakeTokens", "description": "An old name."}]
    found = {f["tool"]: f for f in W.listing_findings(tools)}
    assert set(found) == {"theprotocol_getMyEarnings", "theprotocol_getLockPayoutTiers", "theprotocol_stakeTokens"}
    assert found["theprotocol_getLockPayoutTiers"] == {"tool": "theprotocol_getLockPayoutTiers", "name": [],
                                                        "description": ["apy"]}
    # both are W3's old names: getMyEarnings for getMyIncome, stakeTokens for lockUnits
    assert W.old_names_listed(tools) == ["theprotocol_getMyEarnings", "theprotocol_stakeTokens"]


def test_a_run_closes_into_rows():
    token = W.begin()
    W.record("theprotocol_getAgentProfile", {"description": "Autonomous yield optimizer", "staked_balance": 3})
    W.record("theprotocol_getNetworkStats", {"total_agents": 3, "note": "units moved"})
    tools = [{"name": "theprotocol_getLockPayoutTiers", "description": "The APY of a lock."},
             {"name": "theprotocol_getNetworkStats", "description": "Network numbers."}]
    rows = [_row("theprotocol_getLockPayoutTiers"), _row("theprotocol_getNetworkStats")]
    summary = F._wording_close(rows, token, {"public": F._listing_words(tools)})
    assert rows[0].healthy is False and rows[0].fail_reason.startswith("WORDING: the listing names a critical word")
    assert rows[1].healthy is True
    listing, answers = rows[-2], rows[-1]
    assert listing.tool_name == W.LISTING_ROW and listing.healthy is False and "1 listed tool" in listing.fail_reason
    assert answers.tool_name == W.ANSWERS_ROW and answers.healthy is True and answers.fail_reason is None
    assert answers.result_excerpt["tools"] == {"getAgentProfile": ["yield"]} and answers.result_excerpt["responses_scanned"] == 2
    assert summary["listings"]["tools_listed"] == {"public": 2}


def test_a_clean_listing_is_green_and_an_unread_one_is_not_measured():
    rows = []
    F._wording_close(rows, W.begin(), {"public": F._listing_words([{"name": "theprotocol_lockUnits", "description": "x"}])})
    assert rows[-2].healthy is True and rows[-2].fail_reason is None
    assert rows[-1].healthy is False and "NOT MEASURED" in rows[-1].skip_reason, "no answer scanned is not a green census"
    rows = []
    F._wording_close(rows, W.begin(), {})
    assert rows[-2].healthy is False and rows[-2].skip_reason.startswith("the critical-words listing check NOT MEASURED")


def test_an_old_name_listed_fails_its_row():
    rows = [_row("theprotocol_stakeTokens")]
    F._wording_close(rows, W.begin(), {"admin": F._listing_words([{"name": "theprotocol_stakeTokens", "description": "x"}])})
    assert rows[0].healthy is False and "an old name is listed" in rows[0].fail_reason


def test_record_outside_a_run_is_a_no_op_and_never_raises():
    W.record("theprotocol_x", object())
    W.record("theprotocol_x", {"a": "rewards"})


def test_every_answer_and_both_runs_are_wired():
    src = inspect.getsource(F)
    assert src.count("_words.record(") == src.count("credential_exposure.record(") == 4
    assert src.count("_wording_close(outcomes, _words_token, _listing_words_found)") == 2, "the frame and cloud-op runs"
    assert src.count("_listing_words(admin_tools)") == 2 and src.count("{\"public\": _listing_words(tools)}") == 2
