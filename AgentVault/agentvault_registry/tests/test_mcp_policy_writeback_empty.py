"""§MCPTEST30 V0644 (agentvault2-66, 2026-10-26): the enforcement policy write-back takes an empty active document.

earned_ad_agents._policy_unchanged writes the active policy back unchanged (updateEnforcementPolicy: a new version,
nothing else changed). It read an empty `policy_json` as unreadable (`not pj`), so once the sandbox's three phase6-only
rows were replaced by {} (sbx_policy_clean.py, 2026-10-26 09:32Z) V0643's operator read still left the row NOT MEASURED,
now saying "the active policy could not be read (HTTP 200)". An empty document is a policy row too: it is written back as
it reads; a policy that cannot be read, and a target with no policy row, keep their own reasons. RED on c5257273e: the
empty row is NOT MEASURED as unreadable and nothing is written.
"""
import asyncio

import pytest

from agentvault_registry.api_tests.contracts import earned_ad_agents as E

TOOL = "theprotocol_updateEnforcementPolicy"


def _run(reads, write_ok=True):
    """reads: the answers of getEnforcementPolicy in turn, as (ok, answer, code)."""
    seen = {"unmeasured": [], "bugs": [], "writes": []}
    answers = list(reads)

    async def admin_read(bag, parse, tool, args):
        return answers.pop(0) if len(answers) > 1 else answers[0]

    async def effect(bag, parse, tool, args, outcomes, **kw):
        seen["writes"].append((tool, args["policy_json"]))
        return write_ok, {}

    def unmeasured(outcomes, tool, why):
        seen["unmeasured"].append(why)

    def bug(outcomes, tool, why):
        seen["bugs"].append(why)

    mp = pytest.MonkeyPatch()
    mp.setattr(E, "_admin_read", admin_read)
    mp.setattr(E, "effect", effect)
    mp.setattr(E, "effect_unmeasured", unmeasured)
    mp.setattr(E, "_bug", bug)
    try:
        asyncio.run(E._policy_unchanged(None, None, {}))
    finally:
        mp.undo()
    return seen


def test_an_empty_active_document_is_written_back_as_it_reads():
    seen = _run([(True, {"policy_json": {}, "version": 77}, "200")])
    assert seen["writes"] == [(TOOL, {})] and seen["unmeasured"] == [] and seen["bugs"] == []


def test_a_policy_with_keys_is_written_back_as_before():
    pj = {"thresholds": {"warn": 0.3}}
    seen = _run([(True, {"policy_json": pj, "version": 5}, "200")])
    assert seen["writes"] == [(TOOL, pj)] and seen["unmeasured"] == [] and seen["bugs"] == []


@pytest.mark.parametrize("read", [(False, {}, "503"), (True, {"policy_json": None, "version": 3}, "200"),
                                  (True, {"policy_json": "phase6", "version": 3}, "200")])
def test_an_answer_that_is_not_a_policy_stays_unreadable(read):
    seen = _run([read])
    assert seen["writes"] == [] and len(seen["unmeasured"]) == 1 and "could not be read" in seen["unmeasured"][0]


def test_a_target_with_no_policy_row_keeps_its_own_reason():
    seen = _run([(True, {"policy_json": {}, "version": 0}, "200")])
    assert seen["writes"] == [] and len(seen["unmeasured"]) == 1 and "factory defaults" in seen["unmeasured"][0]


def test_a_write_back_that_reads_differently_is_a_bug_find():
    seen = _run([(True, {"policy_json": {}, "version": 77}, "200"), (True, {"policy_json": {"x": 1}}, "200")])
    assert seen["writes"] == [(TOOL, {})] and seen["bugs"] == ["the policy reads differently after it was written back unchanged"]
