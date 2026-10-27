"""§MCPSWEEP 2026-09-27 — the lifecycle fixture stakes what the frame requires to open a proposal.

Measured on sbx-alpha in every sweep of the day (03:09Z, 14:05Z, 20:50Z): createProposal answered
403 "This frame requires 100 locked units to open a proposal (governance.min_stake_to_propose_avt); you hold 10 locked."
(V0643's words) because the
fixture staked a literal 10 while the frame's policy (§FRAMEPOLICY, shipped default 100) asks for more. `proposal_id`
never reached the bag, so getProposalDetail, getProposalVotes and getMyVoteOnProposal skipped every night as "fixture
missing". The fixture now reads governance.min_stake_to_propose_avt from the frame's resolved policy and stakes it
(within a ceiling), and a failed create names the product's reason instead of "no proposal_id in the reply".
Every control below builds the input that must fail, and fails for the reason it names.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as flow  # noqa: E402

KEY = "governance.min_stake_to_propose_avt"
LIFECYCLE = Path(flow.__file__)


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    # asyncio.run() leaves the thread with no current loop; put one back, or the next file's get_event_loop() fails and
    # the red lands in a file this one never touched.
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _resolved(value, source="default"):
    return json.dumps({"policy_version": 76, "policy_source": "amended",
                       "governed": {KEY: {"value": value, "source": source},
                                    "governance.standard_quorum_percent": {"value": 10.0, "source": "default"}}})


# ── reading the frame's minimum ───────────────────────────────────────────────

def test_the_minimum_is_read_from_the_resolved_policy():
    assert flow._proposal_stake_from_resolved(_resolved(100)) == (100.0, "")
    assert flow._proposal_stake_from_resolved(_resolved("250")) == (250.0, "")


def test_control_a_policy_without_the_key_is_unread_not_zero():
    body = json.dumps({"governed": {"governance.standard_quorum_percent": {"value": 10.0}}})
    val, why = flow._proposal_stake_from_resolved(body)
    assert val is None and KEY in why


def test_control_a_body_that_is_not_json_or_not_a_number_is_unread():
    val, why = flow._proposal_stake_from_resolved("<html>403</html>")
    assert val is None and "not JSON" in why
    val, why = flow._proposal_stake_from_resolved(_resolved("a hundred"))
    assert val is None and "not a number" in why


# ── what the fixture stakes ───────────────────────────────────────────────────

def test_the_fixture_stakes_the_frames_minimum_when_it_is_above_the_base():
    assert flow._proposal_stake_amount(100.0) == (100.0, "")
    assert flow._proposal_stake_amount(1000.0) == (1000.0, "")


def test_a_frame_asking_for_no_more_than_the_base_keeps_the_base():
    assert flow._proposal_stake_amount(10.0) == (10.0, "")
    assert flow._proposal_stake_amount(5.0) == (10.0, "")


def test_control_unread_or_above_the_ceiling_keeps_the_base_and_says_why():
    amt, why = flow._proposal_stake_amount(None)
    assert amt == 10.0 and "not read" in why
    amt, why = flow._proposal_stake_amount(5000.0)
    assert amt == 10.0 and "5000" in why and "ceiling" in why


# ── the read itself, through the container exec the fixture uses ─────────────

def _fake_exec(out, rc=0, seen=None):
    def run(container, argv, timeout=30):
        if seen is not None:
            seen.append((container, argv))
        return rc, out
    return run


def test_the_read_asks_the_resolved_policy_route_with_the_admin_token(monkeypatch):
    seen = []
    monkeypatch.setattr(flow, "exec_in_container",
                        _fake_exec(_resolved(100) + "\n" + flow._HTTP_MARKER + "200--", seen=seen))
    assert asyncio.run(flow._required_proposal_stake("sbx-alpha-registry", "tok")) == (100.0, "")
    (container, argv), = seen
    assert container == "sbx-alpha-registry"
    assert "/api/v1/admin/enforcement/policy/resolved" in argv[-1] and "Bearer tok" in argv[-1]


def test_control_a_refused_read_is_unread_and_names_the_status(monkeypatch):
    monkeypatch.setattr(flow, "exec_in_container",
                        _fake_exec('{"detail":"Not enough privileges"}\n' + flow._HTTP_MARKER + "403--"))
    val, why = asyncio.run(flow._required_proposal_stake("sbx-alpha-registry", "tok"))
    assert val is None and "HTTP 403" in why


def test_control_no_container_or_no_token_reads_nothing(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not exec without a container and a token")
    monkeypatch.setattr(flow, "exec_in_container", boom)
    assert asyncio.run(flow._required_proposal_stake("", "tok"))[0] is None
    assert asyncio.run(flow._required_proposal_stake("sbx-alpha-registry", ""))[0] is None


# ── the product side the fixture depends on ──────────────────────────────────

def test_the_key_is_governed_so_the_resolved_route_publishes_it():
    from agentvault_registry.services.frame_policy import GOVERNED_PATHS
    assert KEY in GOVERNED_PATHS


def test_the_governance_refusal_names_the_same_key():
    src = (Path(flow.__file__).resolve().parents[3] / "routers" / "governance.py").read_text(encoding="utf-8")
    assert f'"{KEY}"' in src and f"({KEY})" in src


# ── the fixture wires it (the literal it replaces is gone) ───────────────────

def test_the_stake_step_uses_the_frames_minimum_not_a_literal():
    src = LIFECYCLE.read_text(encoding="utf-8")
    assert '{"agent_jwt": bag.sentinel_jwt, "amount": "10", "lock_period_days": 0}' not in src
    assert '"amount": f"{_stake_amt:g}", "lock_period_days": 0' in src
    assert "_required_proposal_stake(" in src and "_proposal_stake_amount(_prop_min)" in src


def test_a_failed_proposal_names_the_recorded_reason():
    src = LIFECYCLE.read_text(encoding="utf-8")
    assert 'setup_outcomes.get("theprotocol_createProposal")' in src
    assert 'getattr(_prop_outcome, "fail_reason", "")' in src
