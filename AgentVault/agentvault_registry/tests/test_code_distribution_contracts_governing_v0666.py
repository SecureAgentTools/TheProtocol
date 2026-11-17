"""V0666: the tester's contracts for the writes of a code distribution know the governing-registry posture (session-release's pair proof nt261116x5, room seq
5338: "the lifecycle's proposeCodeDistributionChange contract expects 'Not Found' and got 403 'Code changes are governed on EU; open them there'").

Where this registry is not the one that governs code (services/code_authority), every WRITE of the rail answers 403 with the authority's sentence BEFORE it looks at the
line named, so the refusal a sweep meets there is that sentence, not "no code distribution with that name". Each write tool's contract names both refusals, and both
must be the words the registry really says: the contract's phrase is read from services/code_authority.sentence(), never typed twice.
Red before: both contracts name only the not-found sentence.
"""
from __future__ import annotations

import pytest

from agentvault_registry.api_tests.contracts import mcp_contracts as mc
from agentvault_registry.services import code_authority

WRITES = ("theprotocol_proposeCodeDistributionChange", "theprotocol_voteCodeDistributionChange")


@pytest.mark.parametrize("tool", WRITES)
def test_a_write_contract_accepts_the_governing_registrys_refusal(tool, monkeypatch):
    monkeypatch.delenv(code_authority.ENV, raising=False)       # nothing set: this registry is not the governing one
    assert not code_authority.is_governing()
    wanted = list(mc.MCP_CONTRACTS[tool].expect_error_message_contains)
    sentence = code_authority.sentence()
    assert any(a in sentence for a in wanted), f"{tool}: none of {wanted} is in the real refusal {sentence!r}"


@pytest.mark.parametrize("tool", WRITES)
def test_a_write_contract_still_accepts_the_governing_registrys_own_not_found(tool):
    assert any("no code " in a for a in mc.MCP_CONTRACTS[tool].expect_error_message_contains)


def test_the_two_reads_are_not_given_the_governing_sentence():
    for tool in ("theprotocol_getCodeDistribution", "theprotocol_listOrganizationCodeDistributions"):
        assert not any("governed" in a for a in mc.MCP_CONTRACTS[tool].expect_error_message_contains), tool


# --- the switch row (session-release's pair proof nt261116x6, room seq 5404): where code distributions are OFF and this registry is not the governing one, propose answers the governed 403
# before it looks at the switch, so the row that judges a switched-off tool must accept that refusal too, and only for the tool whose flow asks the gate first ---------------------------

from agentvault_registry.api_tests.contracts import mcp_switches as sw  # noqa: E402

GOVERNED = "Code changes are governed on EU; open them there: https://eu.theprotocol.cloud/#/code-changes"


def test_propose_where_distributions_are_off_and_the_registry_does_not_govern_is_healthy_on_the_governed_403():
    s = sw.SWITCHED_TOOLS["theprotocol_proposeCodeDistributionChange"]
    assert sw.judge("theprotocol_proposeCodeDistributionChange", s, 403, GOVERNED)[0] is True
    assert sw.judge("theprotocol_proposeCodeDistributionChange", s, 404, "Not Found")[0] is True              # a governing registry with the switch off: the switch's own 404


@pytest.mark.parametrize("code,text", [(200, "created"), (403, "forbidden"), (404, "no such route"), (409, GOVERNED), (500, "boom")])
def test_propose_still_fails_anything_else(code, text):
    s = sw.SWITCHED_TOOLS["theprotocol_proposeCodeDistributionChange"]
    assert sw.judge("theprotocol_proposeCodeDistributionChange", s, code, text)[0] is False


@pytest.mark.parametrize("tool", ["theprotocol_getCodeDistribution", "theprotocol_listOrganizationCodeDistributions", "theprotocol_voteCodeDistributionChange"])
def test_the_other_distribution_tools_keep_the_one_sentence_because_their_routes_ask_the_switch_first(tool):
    s = sw.SWITCHED_TOOLS[tool]
    assert sw.judge(tool, s, 403, GOVERNED)[0] is False
    assert sw.judge(tool, s, 404, "Not Found")[0] is True


def test_the_refusal_contract_of_propose_names_both_sentences_and_stays_a_4xx():
    base = mc.MCP_CONTRACTS["theprotocol_proposeCodeDistributionChange"]
    held = sw.refusal_contract(base, sw.SWITCHED_TOOLS["theprotocol_proposeCodeDistributionChange"])
    assert held.expect_status == "error_4xx" and "Not Found" in held.expect_error_message_contains and "Code changes are governed on" in held.expect_error_message_contains
    other = sw.refusal_contract(mc.MCP_CONTRACTS["theprotocol_getCodeDistribution"], sw.SWITCHED_TOOLS["theprotocol_getCodeDistribution"])
    assert "Code changes are governed on" not in other.expect_error_message_contains


def test_the_switch_rows_governed_words_are_the_real_refusals_words_never_typed_twice(monkeypatch):
    monkeypatch.delenv(code_authority.ENV, raising=False)
    assert not code_authority.is_governing()
    s = sw.SWITCHED_TOOLS["theprotocol_proposeCodeDistributionChange"]
    (status, words), = s.also
    assert status == 403 and all(w in code_authority.sentence() for w in words)
    # and the judge accepts the real sentence, link and all
    assert sw.judge("theprotocol_proposeCodeDistributionChange", s, 403, code_authority.sentence())[0] is True
