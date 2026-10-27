"""§MCPTEST30 (V0550): a tool its target switched off is held to its switch's refusal, and a member votes once.

A registry switches surfaces off (§BAFIN: STAKING_ENABLED, STAKING_REWARDS_ENABLED, AGORA_DISTRIBUTIONS_ENABLED;
§MEMBERSHIP: GOVERNANCE_WEIGHT_MODE=member) and says so in /api/v1/public/registry-config. The tester reads that once
per run (api_tests/contracts/mcp_switches.py) and judges a switched-off tool by the refusal its switch documents: a
contract that asked for success, and a lifecycle that asked "any", both become that refusal; a 2xx is a finding (the
switch did not hold), another refusal a failure (the row would measure something else). A target that reports no
switch reads exactly as before. The dependency-switched tools are checked against the routes by the request survey
(test_mcp_tool_requests_meet_their_routes.py); the two inline switches against their handlers here.
"""
from __future__ import annotations

import ast
import asyncio
import inspect

from agentvault_registry.api_tests.contracts import mcp_contracts as C
from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
from agentvault_registry.api_tests.contracts import mcp_switches as M

STAKE = "theprotocol_lockUnits"
OFF_TEXT = ("Error: HTTP 403: staking_disabled: Locking is not enabled on this registry (STAKING_ENABLED=false). Units "
            "cannot be locked and no payout on locked units is made; existing positions can still be unlocked.")


def _run(coro_fn, config):
    """Run under a target config in a fresh context (as a flow runs in its own request task)."""
    async def go():
        M.use_target(config)
        return await coro_fn()
    return asyncio.run(go())


def test_the_switches_follow_the_config_and_nothing_else():
    assert _run(lambda: _async(M.switched_off(STAKE)), {"staking_enabled": False}) is M.STAKING_OFF
    assert _run(lambda: _async(M.switched_off(STAKE)), {"staking_enabled": True}) is None
    # a target older than §BAFIN reports no switch: nothing is switched, never guessed
    assert _run(lambda: _async(M.switched_off(STAKE)), {"fx_enabled": True}) is None
    assert _run(lambda: _async(M.switched_off(STAKE)), None) is None
    # rewards: off where staking is off (the config reports staking_rewards_enabled false there too)
    cfg = {"staking_enabled": True, "staking_rewards_enabled": False}
    assert _run(lambda: _async(M.switched_off("theprotocol_claimTegPayouts")), cfg) is M.REWARDS_OFF
    assert _run(lambda: _async(M.switched_off(STAKE)), cfg) is None
    assert _run(lambda: _async(M.switched_off("theprotocol_federationVoteProposal")),
                {"governance_weight_mode": "member"}) is M.MEMBER_FEDERATION_VOTE
    assert _run(lambda: _async(M.switched_off("theprotocol_federationVoteProposal")),
                {"governance_weight_mode": "lock"}) is None
    # an unswitched tool is never switched
    assert _run(lambda: _async(M.switched_off("theprotocol_unlockUnits")), {"staking_enabled": False}) is None


async def _async(v):
    return v


def test_each_run_reads_only_its_own_target():
    """The frame's run and an operator's run are separate tasks: one target's switches never reach the other."""
    async def flow(cfg, seen, gate):
        M.use_target(cfg)
        await gate.wait()
        seen.append(M.switched_off(STAKE))

    async def main():
        gate, seen_a, seen_b = asyncio.Event(), [], []
        ta = asyncio.create_task(flow({"staking_enabled": False}, seen_a, gate))
        tb = asyncio.create_task(flow({"staking_enabled": True}, seen_b, gate))
        await asyncio.sleep(0)
        gate.set()
        await asyncio.gather(ta, tb)
        return seen_a, seen_b, M.switched_off(STAKE)
    a, b, outside = asyncio.run(main())
    assert a == [M.STAKING_OFF] and b == [None] and outside is None


def test_the_judge():
    assert M.judge(STAKE, M.STAKING_OFF, 403, OFF_TEXT) == (True, None)
    ok, why = M.judge(STAKE, M.STAKING_OFF, 200, '{"stake_id": "x"}')
    assert not ok and why.startswith("BUG-FIND: lockUnits answered HTTP 200") and "did not hold" in why
    ok, why = M.judge(STAKE, M.STAKING_OFF, 400, "Error: HTTP 400: amount must be positive")
    assert not ok and "expected its refusal (403 staking_disabled)" in why
    ok, why = M.judge(STAKE, M.STAKING_OFF, 400, OFF_TEXT)
    assert not ok and "answered HTTP 400" in why
    # rewards off where staking is off: the gate names staking itself, and that is the documented refusal too
    assert M.judge("theprotocol_claimLockPayouts", M.REWARDS_OFF, 403, OFF_TEXT) == (True, None)


def test_a_switched_contract_is_the_refusal_and_a_do_not_call_stays_one():
    async def go():
        M.use_target({"staking_enabled": False, "staking_rewards_enabled": False})
        return C.get_contract(STAKE), C.get_contract("theprotocol_unlockUnits")
    stake, unstake = asyncio.run(go())
    assert stake.expect_status == "error_4xx" and stake.expect_error_message_contains == ["staking_disabled"]
    assert stake.expect_events == [] and stake.side_effect_assert is None and not stake.expect_idempotent
    assert "staking_enabled=false" in stake.notes
    assert unstake.expect_status != "error_4xx" or "staking_enabled" not in (unstake.notes or "")
    # outside a run nothing is switched: the same tool has its own contract back
    assert C.get_contract(STAKE).expect_status != "error_4xx" or "switched off" not in (C.get_contract(STAKE).notes or "")
    base = C.McpContract(tier="2", skip_reason="do not call: it would do the thing")
    assert M.refusal_contract(base, M.STAKING_OFF) is base


def _fake_rpc(answers, seen):
    async def rpc(tool, args, jwt="", timeout=15):
        seen.append((tool, dict(args)))
        ans = answers[tool]
        if callable(ans):
            ans = ans(args)
        code, payload = ans
        if 200 <= int(code) < 300:
            return True, {"result": payload}, str(code)
        return False, {"result": {"_text": payload}}, str(code)
    return rpc


def _parse(body):
    return (body or {}).get("result") or {}


def _step(answer, config, expect_status="any"):
    seen, outcomes = [], {}

    async def go():
        M.use_target(config)
        return await L._exec_step(_fake_rpc({STAKE: answer}, seen), _parse, STAKE, "2", {"amount": "10"}, "dev",
                                  outcomes, expect_status=expect_status, expect_events=["TokensStaked"])
    ok, _ = asyncio.run(go())
    return ok, outcomes[STAKE]


def test_a_lifecycle_step_on_a_switched_tool_is_held_to_the_switch():
    off = {"staking_enabled": False}
    ok, row = _step((403, OFF_TEXT), off)
    # the row holds the switch's verdict; the lifecycle hears no success, so it builds nothing on the refusal (V0551:
    # round 17 read a 403 as a stake without an id)
    assert not ok and row["healthy"] and row["probe_expect_status"] == "error_4xx" and row["fail_reason"] is None
    assert row["switched_off"] == "staking_enabled=false"
    # asked for success, it is still the refusal that is right here
    ok, row = _step((403, OFF_TEXT), off, expect_status="success")
    assert not ok and row["healthy"]
    ok, row = _step((200, {"stake_id": "s1"}), off)
    assert not ok and row["fail_reason"].startswith("BUG-FIND: lockUnits answered HTTP 200")
    ok, row = _step((400, "Error: HTTP 400: amount below the minimum"), off)
    assert not ok and "expected its refusal" in row["fail_reason"]
    # control: where staking is on, the step reads exactly as before ("any" takes a 4xx, success takes a 2xx)
    ok, row = _step((403, OFF_TEXT), {"staking_enabled": True})
    assert ok and row["healthy"] and row["probe_expect_status"] == "any"
    ok, row = _step((200, {"stake_id": "s1"}), {}, expect_status="success")
    assert ok and row["healthy"] and row["probe_expect_status"] == "success"
    assert "switched_off" not in row


def test_a_read_after_a_refused_switched_step_blames_nothing():
    """updatePayoutRelock refused by the rewards switch, then getMyPayoutRelock finds the flag unchanged: the switch
    holding, never a write that failed (round 17 named it a BUG-FIND)."""
    tool, read = "theprotocol_updatePayoutRelock", "theprotocol_getMyPayoutRelock"
    off_text = OFF_TEXT.replace("staking_disabled", "staking_rewards_disabled")
    answers = {tool: (403, off_text), read: (200, {"enabled": False})}

    def run(config):
        outcomes = {}

        async def go():
            M.use_target(config)
            rpc = _fake_rpc(answers, [])
            await L._exec_step(rpc, _parse, tool, "3", {"enabled": True}, "dev", outcomes, expect_status="any")
            await L._exec_step(rpc, _parse, read, "2", {}, "dev", outcomes, expect_status="any",
                               record_as_separate=False, verify_against=tool,
                               verify_against_check=lambda inner: None if inner.get("enabled") else "did not flip")
        asyncio.run(go())
        return outcomes[tool]
    row = run({"staking_rewards_enabled": False})
    assert row["healthy"] and row["fail_reason"] is None and row["switched_off"] == "staking_rewards_enabled=false"
    # control: where rewards are on, the same unchanged flag is the finding it always was
    answers[tool] = (200, {"enabled": True})
    row = run({"staking_rewards_enabled": True})
    assert not row["healthy"] and row["fail_reason"] == "BUG-FIND: did not flip"


def test_the_federation_vote_probe_sends_a_vote_the_tool_takes():
    import inspect
    from agentvault_registry.api_tests.contracts import earned_agent_public as E
    # §MCPTEST30 (V0636): the probe moved to the by-design lifecycle, as a refusal row naming why the route refuses it
    src = inspect.getsource(E.lifecycle_earned_by_design)
    assert '"vote": "FOR"' in src and '"vote": "ABSTAIN"' not in src
    assert "theprotocol_federationVoteProposal" not in inspect.getsource(L.lifecycle_federation_safe_paths)


def test_the_inline_switches_are_still_in_their_handlers():
    from agentvault_registry.routers import governance
    from agentvault_registry.services import exchange_service
    src = inspect.getsource(exchange_service.declare_dividend)
    head = src.split("await _require_venue_open", 1)[0]
    assert "distributions_enabled()" in head and "DISTRIBUTIONS_DISABLED_SENTENCE" in head, \
        "declare_dividend no longer checks AGORA_DISTRIBUTIONS_ENABLED first"
    from agentvault_registry.core.agora_gate import DISTRIBUTIONS_DISABLED_SENTENCE
    assert DISTRIBUTIONS_DISABLED_SENTENCE.startswith(M.AGORA_DISTRIBUTIONS_OFF.words[0] + ":")
    src = inspect.getsource(governance.federation_vote)
    assert "member_mode()" in src and '"federation_ballot_pending"' in src and "HTTP_409_CONFLICT" in src
    # V0555: the ballot-mode refusal comes first in the same handler, and the switch names its word too
    assert "_federation_ballot_mode()" in src and '"registry_ballots"' in src
    assert src.index("_federation_ballot_mode()") < src.index("member_mode()")
    assert M.MEMBER_FEDERATION_VOTE.words == ("federation_ballot_pending", "registry_ballots")
    assert M.AGORA_DISTRIBUTIONS_OFF.where == "inline: exchange_service.declare_dividend"
    assert M.MEMBER_FEDERATION_VOTE.where == "inline: governance.federation_vote"
    from agentvault_registry.core.staking_gate import REWARDS_DISABLED_SENTENCE, STAKING_DISABLED_SENTENCE
    assert STAKING_DISABLED_SENTENCE.startswith(M.STAKING_OFF.words[0] + ":")
    assert REWARDS_DISABLED_SENTENCE.startswith(M.REWARDS_OFF.words[0] + ":")


# ── the member vote (§MEMBERSHIP, GOVERNANCE_WEIGHT_MODE=member) ──────────────────────────────────────────────────────
class _Bag:
    developer_jwt, sentinel_jwt = "dev", "sentinel"

    def __init__(self, second="second"):
        self.flow_values = {"second_agent_jwt": second, "second_agent_did": "did:theprotocol:second"}

    def get(self, k):
        return self.flow_values.get(k)


POWER = {"mode": "member", "votingPower": "100", "canVote": True, "positions": [],
         "membership": {"is_member": True, "points": 100, "missing": []}}
ALREADY = ("Error: HTTP 409: developer_already_voted: your developer already voted on proposal 7 with another agent "
           "(one member, one vote)")


def _vote(power=POWER, first=(200, {"id": 1, "proposal_id": 7, "voting_power": 100}), second=(409, ALREADY),
          bag=None):
    seen, outcomes = [], {}

    def cast(args):
        return first if args["agent_jwt"] == "sentinel" else second
    answers = {"theprotocol_getMyVotingPower": (200, power), "theprotocol_castVote": cast}

    async def go():
        M.use_target({"governance_weight_mode": "member"})
        await L._member_vote(_fake_rpc(answers, seen), _parse, bag or _Bag(), outcomes, 7,
                             {"agent_jwt": "sentinel", "proposal_id": 7, "vote_in_favor": True, "reason": "r"})
    asyncio.run(go())
    return outcomes, seen


def test_a_member_votes_once_with_the_weight_its_membership_names():
    outcomes, seen = _vote()
    assert outcomes["theprotocol_castVote"]["healthy"], outcomes["theprotocol_castVote"]
    row = outcomes[L.MEMBER_VOTE_ROW]
    assert row["healthy"] and row["status_code"] == 409, row
    assert row["result_excerpt"]["second_agent"] == "refused, already voted"
    assert [t for t, _ in seen] == ["theprotocol_getMyVotingPower", "theprotocol_castVote", "theprotocol_castVote"]


def test_a_second_vote_by_the_same_member_is_a_finding():
    outcomes, _ = _vote(second=(200, {"id": 2, "proposal_id": 7, "voting_power": 100}))
    row = outcomes[L.MEMBER_VOTE_ROW]
    assert not row["healthy"] and row["fail_reason"].startswith("BUG-FIND: a second agent of the same member developer")


def test_a_vote_that_weighs_other_than_the_membership_is_a_finding():
    outcomes, _ = _vote(first=(200, {"id": 1, "proposal_id": 7, "voting_power": 1}))
    row = outcomes["theprotocol_castVote"]
    assert not row["healthy"] and "weighs 1" in row["fail_reason"] and "100 points" in row["fail_reason"]


def test_not_a_member_is_held_to_its_refusal_and_the_repeat_is_not_measured():
    power = dict(POWER, canVote=False, votingPower="0", membership={"is_member": False, "points": 0,
                                                                     "missing": ["bond"]})
    refused = (403, "Error: HTTP 403: not_a_member: Only members of this registry can do this.")
    outcomes, seen = _vote(power=power, first=refused)
    assert outcomes["theprotocol_castVote"]["healthy"]
    assert outcomes[L.MEMBER_VOTE_ROW]["skip_reason"].startswith("NOT MEASURED: the sentinel's developer is not a "
                                                                 "member yet (bond)")
    assert len(seen) == 2
    # control: refused for another reason, the castVote row fails
    outcomes, _ = _vote(power=power, first=(403, "Error: HTTP 403: Only agents with locked units can vote"))
    assert not outcomes["theprotocol_castVote"]["healthy"]


def test_a_voting_power_read_that_disagrees_with_the_config_is_a_finding():
    outcomes, _ = _vote(power=dict(POWER, mode=None))
    row = outcomes[L.MEMBER_VOTE_ROW]
    assert not row["healthy"] and row["fail_reason"].startswith("BUG-FIND: the target's registry-config says "
                                                                "governance_weight_mode=member")


def test_a_second_agent_without_gov_vote_is_not_measured_rather_than_failed():
    """IRONKEY answers before membership is asked: a 403 naming gov.vote says nothing of one member, one vote."""
    outcomes, _ = _vote(second=(403, "Error: HTTP 403: Agent lacks required permission: gov.vote"))
    row = outcomes[L.MEMBER_VOTE_ROW]
    assert not row["healthy"] and row["fail_reason"] is None
    assert row["skip_reason"].startswith("NOT MEASURED: the second agent lacks gov.vote")


def test_without_a_second_agent_the_repeat_is_not_measured():
    outcomes, seen = _vote(bag=_Bag(second="sentinel"))
    assert outcomes[L.MEMBER_VOTE_ROW]["skip_reason"].startswith("NOT MEASURED: the setup made no second agent")
    assert len(seen) == 2

def test_the_sweep_takes_a_switched_refusal_as_measured_even_under_a_do_not_call_contract():
    """Round 17: tegLockDirect, claimTegPayouts and triggerLockPayoutRun carry a do-not-call contract (the sweep
    must never perform them), their lifecycle met the switch's refusal, and the credential guard re-read that refusal
    against the success contract: NOT MEASURED. The guard now takes the switch's verdict where the row carries it."""
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
    row = {"healthy": True, "status_code": 403, "result_excerpt": {"_text": OFF_TEXT}, "switched_off": "staking_enabled=false"}

    async def go(cfg, r):
        M.use_target(cfg)
        return F._credential_laundering_guard(r, "theprotocol_tegLockDirect")
    assert asyncio.run(go({"staking_enabled": False}, row)) is None
    # controls: the same row where staking is on, or a row the switch did not judge, is still laundering
    assert "lifecycle recorded a 403 as healthy" in asyncio.run(go({"staking_enabled": True}, row))
    unjudged = {k: v for k, v in row.items() if k != "switched_off"}
    assert "lifecycle recorded a 403 as healthy" in asyncio.run(go({"staking_enabled": False}, unjudged))


# ── the commons (§MEMBERSHIP phase B, V0551) ─────────────────────────────────────────────────────────────────────────
def test_the_commons_switch_holds_every_commons_tool_and_every_commons_route_applies_it():
    from agentvault_registry.mcp import tools_commons as TC
    from agentvault_registry.routers import commons as R
    from agentvault_registry.services import commons as SC
    schemas = (TC.COMMONS_PUBLIC_TOOL_SCHEMAS + TC.COMMONS_DEVELOPER_TOOL_SCHEMAS + TC.COMMONS_AGENT_TOOL_SCHEMAS
               + TC.COMMONS_ADMIN_TOOL_SCHEMAS)
    commons_tools = {t["name"] for t in schemas if "Commons" in t["name"]}
    assert len(commons_tools) == 11
    assert {t for t, sw in M.SWITCHED_TOOLS.items() if sw is M.COMMONS_OFF} == commons_tools
    assert "theprotocol_getMyMembership" not in M.SWITCHED_TOOLS, "membership is never behind the commons switch"
    assert SC.DISABLED_SENTENCE.startswith(M.COMMONS_OFF.words[0] + ":") and "commons_enabled" in M.KEYS
    # every commons route applies the switch: in its handler, or in the service function the handler calls
    svc = ast.parse(inspect.getsource(SC))
    gated = {n.name for n in svc.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "require_enabled"
                     for c in ast.walk(n))}
    routes = [n for n in ast.parse(inspect.getsource(R)).body if isinstance(n, ast.AsyncFunctionDef)
              and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("get", "post")
                      for d in n.decorator_list)]
    assert len(routes) == 11
    for fn in routes:
        called = {c.func.attr for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                  and isinstance(c.func.value, ast.Name) and c.func.value.id == "_commons"}
        assert called & ({"require_enabled", "commons_enabled"} | gated), f"{fn.name} reaches no commons switch"
    # control: the read helpers apply no switch of their own, so a route calling only them would fail above
    assert not ({"season_detail", "list_seasons", "season_summary"} & gated)


def test_a_commons_tool_on_a_commons_off_target_passes_on_its_refusal():
    from agentvault_registry.services.commons import DISABLED_SENTENCE
    text = "Error: HTTP 403: " + DISABLED_SENTENCE
    assert M.judge("theprotocol_getCommonsSeasons", M.COMMONS_OFF, 403, text) == (True, None)
    ok, why = M.judge("theprotocol_adminCommonsPaySeason", M.COMMONS_OFF, 200, '{"paid": 1}')
    assert not ok and why.startswith("BUG-FIND") and "commons_enabled=false" in why
    assert _run(lambda: _async(M.switched_off("theprotocol_castCommonsBallot")), {"commons_enabled": False}) is M.COMMONS_OFF
    assert _run(lambda: _async(M.switched_off("theprotocol_castCommonsBallot")), {"commons_enabled": True}) is None
    # a target older than V0551 reports no commons switch: nothing is switched, never guessed
    assert _run(lambda: _async(M.switched_off("theprotocol_castCommonsBallot")), {"staking_enabled": True}) is None

