"""V0666 the games switch in the federation suite (session-release, 2026-11-16; V0666's pair proof nt261116x5): the three
arena_subsystem tests called the game tools on a pair whose games are off (GAMES_ENABLED=false, production's posture after
V0666) and failed hard on the switch's own refusal ("the games are off on this registry"). Where either frame's
registry-config says games_enabled false, each test is NOT MEASURED (PreconditionUnmet "games_off: ...", its own skip
code, capped at the three arena rows), never a pass and never a failure; where the games are on, nothing changes.
Red before: the rig reads no games switch, and the three tests call the tools regardless.
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.api_tests.federation_suite import rig as R
from agentvault_registry.api_tests.federation_suite import skip_codes as S
from agentvault_registry.api_tests.federation_suite.tests import test_arena_subsystem as arena

TESTS = (arena.test_arena_matches_listed, arena.test_arena_leaderboard, arena.test_arena_health)


class _Client:
    def __init__(self, rig, label):
        self.rig, self.label = rig, label

    async def call(self, name, *args, **kwargs):
        self.rig.calls.append((self.label, name))
        if name == "getPublicRegistryConfig":
            return {"games_enabled": self.rig.games[self.label]}
        return {"matches": [], "entries": [], "leaderboard": []}


class _Rig:
    def __init__(self, games):
        self.games, self.calls = games, []

    def mcp(self, label):
        return _Client(self, label)

    async def assert_within(self, budget_sec, predicate, description, capture_state=None):
        return await predicate()


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_the_rig_reads_the_games_switch():
    assert "games_enabled" in R._SWITCH_KEYS
    assert R.games_off({"games_enabled": False}) is True
    assert R.games_off({"games_enabled": True}) is False
    assert R.games_off({}) is False          # an older registry that does not say: games on


@pytest.mark.parametrize("fn", TESTS, ids=lambda f: f.__name__)
@pytest.mark.parametrize("games", [{"sandbox-A": False, "sandbox-B": False}, {"sandbox-A": True, "sandbox-B": False}])
def test_games_off_is_not_measured_and_calls_no_game_tool(fn, games):
    rig = _Rig(games)
    with pytest.raises(R.PreconditionUnmet) as e:
        _run(fn(rig))
    assert str(e.value).startswith("games_off: ")
    assert S.classify_skip(str(e.value)) == "games_off"
    assert {n for _, n in rig.calls} == {"getPublicRegistryConfig"}, rig.calls


@pytest.mark.parametrize("fn", TESTS, ids=lambda f: f.__name__)
def test_games_on_runs_as_before(fn):
    rig = _Rig({"sandbox-A": True, "sandbox-B": True})
    _run(fn(rig))                              # no PreconditionUnmet
    assert any(n != "getPublicRegistryConfig" for _, n in rig.calls), rig.calls


# ── the MCP tester's probes (V0666's pair proof, lifecycle run 069b23ab240348c5): range and types asked listArenaMatches on a
# target whose games are off; every hostile value met the switch's refusal (-32601) and the probes called it two BUG-FINDs ──
from agentvault_registry.api_tests.contracts import mcp_switches as SW
from agentvault_registry.api_tests.contracts import type_confusion as TC
from agentvault_registry.api_tests.contracts import value_range as VR


def _outcome(name, cat, healthy, status, ms, err, extra, expect_status=None, skip_reason=None):
    return {"name": name, "healthy": healthy, "error": err, "skip_reason": skip_reason}


@pytest.mark.parametrize("runner,target", [
    (VR.run_range, ("theprotocol_listArenaMatches", "1", {}, (("limit", "int64+1", 2 ** 63),))),
    (TC.run_types, ("theprotocol_listArenaMatches", "1", {}, (("limit", "not-a-number"),))),
], ids=["range", "types"])
def test_probes_do_not_ask_a_game_tool_where_games_are_off(runner, target):
    asked = []

    async def raw(body, **kw):
        asked.append(body)
        return 404, {"error": {"code": -32601}}, None

    outcomes = {}
    SW.use_target({"games_enabled": False})
    try:
        assert (SW.probe_skip("theprotocol_listArenaMatches") or "").startswith("NOT MEASURED: the games are off")
        _run(runner(raw, object(), outcomes, _outcome, todo=[target]))
    finally:
        SW.use_target({})
    (row,) = outcomes.values()
    assert asked == [], "a switched-off game tool is never asked"
    assert (row["skip_reason"] or "").startswith("NOT MEASURED"), row
    assert not row["error"], row
    # games on: the probe asks as before
    SW.use_target({"games_enabled": True})
    try:
        assert SW.probe_skip("theprotocol_listArenaMatches") is None
    finally:
        SW.use_target({})


def test_the_games_off_code_is_capped_at_the_three_arena_rows():
    assert S.BASELINE_SKIPS["games_off"] == 3
    assert S.classify_skip("games_off: the games are off on sandbox-A") == "games_off"
    assert S.classify_skip("precondition unmet: games_off: the games are off on sandbox-B") == "games_off"
    assert S.skip_verdict({"games_off": 3})[0] and not S.skip_verdict({"games_off": 4})[0]
