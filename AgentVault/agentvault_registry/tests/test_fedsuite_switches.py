"""§MCPTEST30 (V0550): the federation suite reads its target's switches and says what they make unmeasurable.

The sandbox's V0550 roll switches staking off and governance to member mode (agentvault2-33's §MEMBERSHIP phase A). The
suite staked for its governance rows and for its staking-event row, and counted three or more APY tiers. Without the
switches read, those rows would fail on the switch (a refused stake read as a missing fixture under an unnamed reason,
an empty tier list as a broken read). Now: the tier row passes on the documented off shape (no tiers) and fails on a
tier; the staking-event row is NOT MEASURED as switched_off; a governance row whose developer is not a member is
not_a_member, and one member's vote short of the quorum member_quorum_unreachable; each code has a structural ceiling.
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.api_tests.federation_suite import rig as rig_mod
from agentvault_registry.api_tests.federation_suite import skip_codes as sc
from agentvault_registry.api_tests.federation_suite.tests import test_event_emission_matrix_2 as em2
from agentvault_registry.api_tests.federation_suite.tests import test_staking_distribution_observability as sdo


class _Client:
    def __init__(self, answers, seen):
        self.answers, self.seen = answers, seen

    async def call(self, tool, arguments=None, **_kw):
        self.seen.append(tool)
        a = self.answers.get(tool)
        if isinstance(a, Exception):
            raise a
        return a


class _Rig(rig_mod.FederationTestRig):
    def __init__(self, per_label):
        super().__init__()
        self.per_label, self.seen = per_label, []

    def mcp(self, label):
        return _Client(self.per_label.get(label, {}), self.seen)

    async def assert_within(self, *, budget_sec, predicate, description, poll_interval_sec=1.0, capture_state=None):
        ok = await predicate()
        return rig_mod.AssertionResult(passed=bool(ok), description=description, budget_sec=budget_sec,
                                       elapsed_sec=0.0, polling_attempts=1,
                                       last_state=capture_state() if capture_state else None)


OFF = {"staking_enabled": False, "staking_rewards_enabled": False, "agora_distributions_enabled": True,
       "governance_weight_mode": "member", "governance_presence_mode": "off", "fx_enabled": True}
ON = {"staking_enabled": True, "staking_rewards_enabled": True, "governance_weight_mode": "lock"}


def test_the_skip_codes_name_what_a_switch_makes_unmeasurable():
    assert sc.classify_skip("switched_off: staking is not enabled on sandbox-A") == "switched_off"
    assert sc.classify_skip("not_a_member: governance weighs membership on sandbox-A") == "not_a_member"
    # the refusal itself, as _must reports it, is the same code
    assert sc.classify_skip("POST /api/v1/governance/proposals → HTTP 403: not_a_member: Only members of this "
                            "registry can do this.") == "not_a_member"
    assert sc.classify_skip("member_quorum_unreachable: on sandbox-A one member's vote") == "member_quorum_unreachable"
    assert (sc.BASELINE_SKIPS["switched_off"], sc.BASELINE_SKIPS["not_a_member"],
            sc.BASELINE_SKIPS["member_quorum_unreachable"]) == (1, 3, 2)
    assert sc.skip_verdict({"switched_off": 1, "not_a_member": 3, "member_quorum_unreachable": 2})[0]
    assert not sc.skip_verdict({"switched_off": 2})[0]
    # control: an earlier code still wins its own reasons
    assert sc.classify_skip("unanswered: every leg answered an error or nothing (a, b)") == "unanswered"


def test_the_switches_are_read_once_when_read_and_asked_again_when_not():
    rig = _Rig({"sandbox-A": {"getPublicRegistryConfig": OFF}})
    got = asyncio.run(rig_mod.target_switches(rig, "sandbox-A-admin"))
    assert got == {k: OFF[k] for k in rig_mod._SWITCH_KEYS} and "fx_enabled" not in got
    asyncio.run(rig_mod.target_switches(rig, "sandbox-A"))
    assert rig.seen == ["getPublicRegistryConfig"], "a read config is cached"
    assert rig_mod.member_mode(got) and rig_mod.staking_off(got) and rig_mod.rewards_off(got)
    rig2 = _Rig({"sandbox-B": {"getPublicRegistryConfig": RuntimeError("down")}})
    assert asyncio.run(rig_mod.target_switches(rig2, "sandbox-B")) == {}
    asyncio.run(rig_mod.target_switches(rig2, "sandbox-B"))
    assert rig2.seen == ["getPublicRegistryConfig"] * 2, "an unreadable config is asked again, never cached as none"
    # a later run (a new rig) asks again: a recreate can flip a switch
    rig3 = _Rig({"sandbox-A": {"getPublicRegistryConfig": ON}})
    assert rig_mod.member_mode(asyncio.run(rig_mod.target_switches(rig3, "sandbox-A"))) is False
    assert not rig_mod.member_mode({}) and not rig_mod.staking_off({}) and not rig_mod.rewards_off({})


def _tiers(n):
    return [{"name": f"t{i}", "base_apy": 1.0, "min_stake": 10} for i in range(n)]


def test_the_tier_row_passes_on_the_off_shape_where_rewards_are_off():
    off_answer = {"tiers": [], "metadata": {"engine": "disabled", "staking_rewards_enabled": False}}
    rig = _Rig({"sandbox-A": {"getPublicRegistryConfig": OFF, "getLockPayoutTiersTeg": off_answer},
                "sandbox-B": {"getPublicRegistryConfig": ON, "getLockPayoutTiersTeg": {"tiers": _tiers(3)}}})
    res = asyncio.run(sdo.test_apy_tiers_published(rig))
    assert res.passed, res.last_state
    assert res.last_state["sandbox-A"]["rewards_off"] and res.last_state["sandbox-A"]["off_shape"]
    # a tier served where rewards are off is a finding (each case a run of its own: the cache is the run's rig's)
    rig = _Rig({"sandbox-A": {"getPublicRegistryConfig": OFF, "getLockPayoutTiersTeg": {"tiers": _tiers(3)}},
                "sandbox-B": {"getPublicRegistryConfig": ON, "getLockPayoutTiersTeg": {"tiers": _tiers(3)}}})
    assert not asyncio.run(sdo.test_apy_tiers_published(rig)).passed
    # control: where rewards are on, an empty list still fails
    rig = _Rig({"sandbox-A": {"getPublicRegistryConfig": ON, "getLockPayoutTiersTeg": off_answer},
                "sandbox-B": {"getPublicRegistryConfig": ON, "getLockPayoutTiersTeg": {"tiers": _tiers(3)}}})
    assert not asyncio.run(sdo.test_apy_tiers_published(rig)).passed


def test_the_staking_event_row_is_switched_off_before_it_makes_anything():
    rig = _Rig({"sandbox-A": {"getPublicRegistryConfig": OFF}})

    async def no_catalog(*_a, **_k):
        return {"roles": {}, "mode": "enforce"}
    em2_catalog = em2._catalog
    em2._catalog = no_catalog
    try:
        with pytest.raises(rig_mod.PreconditionUnmet) as e:
            asyncio.run(em2.test_tokens_staked_is_evented(rig))
    finally:
        em2._catalog = em2_catalog
    assert str(e.value).startswith("switched_off: staking is not enabled on sandbox-A")
    assert sc.classify_skip(str(e.value)) == "switched_off"
    assert "createAgent" not in rig.seen, "no agent is made for a row that cannot measure"
