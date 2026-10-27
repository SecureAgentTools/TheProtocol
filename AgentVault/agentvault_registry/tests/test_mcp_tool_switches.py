"""W3 (agentvault2-d6, 2026-10-25; his words through agentvault2-69: "i want the illegal wording completly gone before
opening"): which public MCP tools are LISTED follows the registry's switches (mcp/tool_switches.py), and no listed name
on production's switches carries a staking, reward, rate, earnings or token-as-value word.

A tool that starts a lock is listed only where STAKING_ENABLED is on, a payout tool only where STAKING_REWARDS_ENABLED is
on; unlocking and the lock reads are listed everywhere (core/staking_gate.py keeps them working). A tool that is not
listed still executes by name. The prompt that locks units follows STAKING_ENABLED and still answers under its old name.
RED control: against bddf8fd6 the switches change no listing and the names carry the words.
"""
from __future__ import annotations

import asyncio
import re

import pytest

from agentvault_registry.mcp import prompts, server, tool_switches

CRITICAL = re.compile(r"stak|reward|apy|\bapr|yield|earn|tokenomic|token|dividend|invest|profit|insur", re.I)
SIGN_IN = {"theprotocol_getAgentToken", "theprotocol_oauthTokenExchange"}   # sign-in words, kept (§VOCAB)


def _listed():
    return {t["name"] for t in asyncio.new_event_loop().run_until_complete(server._handle_tools_list())["tools"]}


@pytest.fixture
def switches(monkeypatch):
    def set_(staking: bool, payouts: bool):
        monkeypatch.setenv("STAKING_ENABLED", "true" if staking else "false")
        monkeypatch.setenv("STAKING_REWARDS_ENABLED", "true" if payouts else "false")
    return set_


def test_every_gated_name_is_a_dispatch_key():
    for n in tool_switches.NEEDS_STAKING | tool_switches.NEEDS_STAKING_PAYOUTS:
        assert n in server.TOOL_DISPATCH, n
    assert tool_switches.NEEDS_STAKING_PROMPTS <= {p for p in prompts._PROMPTS}


def test_production_switches_list_no_lock_start_and_no_payout(switches):
    switches(False, False)
    listed = _listed()
    assert not (listed & tool_switches.NEEDS_STAKING) and not (listed & tool_switches.NEEDS_STAKING_PAYOUTS)
    for keep in ("unlockUnits", "getMyLocks", "getMyLockStatus", "getLockStats", "tegUnlockDirect", "transferUnits"):
        assert "theprotocol_" + keep in listed, keep
    bad = sorted(n for n in listed - SIGN_IN if CRITICAL.search(n.replace("theprotocol_", "")))
    assert not bad, f"listed names carrying a critical word on production's switches: {bad}"
    assert "lock_units" not in {p["name"] for p in prompts.list_prompts()["prompts"]}
    init = asyncio.new_event_loop().run_until_complete(server._handle_initialize({}))
    text = init["instructions"]
    assert f"provides {len(listed)} tools" in text, "the count a client is told is the count tools/list gives it"
    assert "getLockPayoutTiers" not in text and "getMyPayoutRelock" not in text and "stak" not in text.lower()


def test_staking_on_payouts_off_lists_the_lock_start_only(switches):
    switches(True, False)
    listed = _listed()
    assert tool_switches.NEEDS_STAKING <= listed and not (listed & tool_switches.NEEDS_STAKING_PAYOUTS)
    assert "lock_units" in {p["name"] for p in prompts.list_prompts()["prompts"]}


def test_both_on_lists_everything(switches):
    switches(True, True)
    listed = _listed()
    assert (tool_switches.NEEDS_STAKING | tool_switches.NEEDS_STAKING_PAYOUTS) <= listed
    assert len(listed) == len(server.ALL_TOOL_SCHEMAS)


def test_a_tool_not_listed_still_dispatches_and_the_old_prompt_name_still_answers(switches):
    switches(False, False)
    assert "theprotocol_lockUnits" in server.TOOL_DISPATCH and "theprotocol_claimLockPayouts" in server.TOOL_DISPATCH
    from agentvault_registry.mcp.tool_aliases import resolve_alias
    assert resolve_alias("theprotocol_stakeTokens") == "theprotocol_lockUnits"
    assert resolve_alias("getApyRates") == "getLockPayoutTiers"
    got = prompts.get_prompt("stake_and_earn", {"amount": "5"})
    assert got is not None and "lockUnits" in got["messages"][0]["content"]["text"]


def test_the_gateway_enumerates_what_tools_list_lists(switches):
    switches(False, False)
    loop = asyncio.new_event_loop()
    found = loop.run_until_complete(server._gateway_search_tools(query="lock", limit=200))
    names = {t.get("name") for t in found.get("tools", found.get("results", []))}
    assert "theprotocol_lockUnits" not in names
    described = loop.run_until_complete(server._gateway_describe_tools(names=["theprotocol_claimLockPayouts"]))
    assert "theprotocol_claimLockPayouts" not in str(described.get("tools", described))


def test_no_listed_tool_says_a_critical_word_on_production_switches(switches):
    """The descriptions and parameter descriptions of every listed tool, in agentvault2-69's vocabulary (locks, payouts
    on locked units, payment authorizations, units, income); the sign-in tokens stay (reset, verification, OAuth,
    invitation, an agent JWT)."""
    switches(False, False)
    word = re.compile(r"\b(staking|staked|stakes?|unstak\w*|rewards?|yields?|APY|APR|dividends?|stocks?|IPOs?|"
                      r"invest\w*|profits?|revenue|earn(?:s|ed|ing|ings)?|tokenomics|tokens?|insurance|premiums?)\b", re.I)
    sign_in = re.compile(r"\b(reset|verification|invitation|oauth|access|refresh|bearer|header|agent|jwt|subject|"
                         r"actor|exchange|introspect\w*|revoke\w*)[ -]?(tokens?)\b|\btoken (?:exchange|introspection|"
                         r"revocation|endpoint|type)\b|`[^`]*`", re.I)
    # the tools about a sign-in, reset, verification, invitation or OAuth token: there "token" is the credential (§VOCAB)
    credential_tools = {"theprotocol_" + n for n in ("authResetPassword", "authVerifyEmail", "oauthIntrospect", "oauthRevoke",
                                                     "acceptOrgInvitation", "inviteOrganizationMember")}
    listed = {t["name"]: t for t in asyncio.new_event_loop().run_until_complete(server._handle_tools_list())["tools"]}
    bad = []
    for name, t in listed.items():
        if name in SIGN_IN:
            continue
        if name in credential_tools:
            word_here = re.compile(word.pattern.replace("|tokens?|", "|"), re.I)
        else:
            word_here = word
        texts = [t.get("description") or ""] + [v.get("description") or "" for v in
                                                 ((t.get("inputSchema") or {}).get("properties") or {}).values()
                                                 if isinstance(v, dict)]
        for text in texts:
            for m in word_here.finditer(sign_in.sub(" ", text)):
                bad.append(f"{name}: {m.group(0)} in {text[:80]!r}")
    assert not bad, "\n".join(bad[:30])
