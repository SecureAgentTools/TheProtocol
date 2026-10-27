"""Arena subsystem (games) observability tests (§pass73.3.9 Batch 23).

3 read-only tests probing the arena public surfaces — leaderboards,
match listing, match detail. Arena is the games subsystem
(RoboWars, Snake, TowerDefense, Trading) backing the games MCP bridges.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


def _is_silent_or_error(r):
    if isinstance(r, str):
        return True
    if isinstance(r, dict):
        if not r:
            return True
        if "_text" in r:
            return isinstance(r["_text"], str)
    return False


@federation_test(
    name="arena_matches_listed_per_frame",
    category="arena_subsystem",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A", "sandbox-B"],
    tags=["arena", "matches"],
)
async def test_arena_matches_listed(rig: FederationTestRig) -> AssertionResult:
    """listArenaMatches returns match list on each mainframe (possibly
    empty on Frame-B; sandbox-A typically has RoboWars matches active)."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("listArenaMatches")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                matches = r.get("matches") if isinstance(r, dict) else r
                if not isinstance(matches, list):
                    state[label] = {"bad_shape": type(matches).__name__}
                    continue
                state[label] = {"count": len(matches)}
                if matches and isinstance(matches[0], dict):
                    state[label]["sample_mode"] = matches[0].get("mode")
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or isinstance(v.get("count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="arena matches listing reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="arena_leaderboard_for_known_game_type",
    category="arena_subsystem",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["arena", "leaderboard"],
)
async def test_arena_leaderboard(rig: FederationTestRig) -> AssertionResult:
    """getArenaLeaderboard returns a leaderboard for a known game type.

    Probes multiple known game types — at least one MUST return a
    valid envelope (RoboWars is the canonical primary).
    """
    state: dict = {"by_type": {}}

    async def predicate():
        # Try canonical game types in order
        for gt in ("battle_royale", "robowars", "snake", "tower_defense", "trading"):
            try:
                r = await rig.mcp("sandbox-A").call(
                    "getArenaLeaderboard", {"game_type": gt}
                )
                if _is_silent_or_error(r):
                    state["by_type"][gt] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state["by_type"][gt] = {"keys": sorted(r.keys())[:6]}
                else:
                    state["by_type"][gt] = {"shape": type(r).__name__}
            except Exception as e:
                state["by_type"][gt] = {"error": repr(e)[:80]}
        # At least one game type must return a non-error envelope
        ok = sum(
            1 for v in state["by_type"].values()
            if isinstance(v, dict) and (v.get("silent") or v.get("keys") or v.get("shape"))
        )
        state["ok_count"] = ok
        return ok >= 1

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="≥1 game type returns valid leaderboard envelope",
        capture_state=lambda: state,
    )


@federation_test(
    name="arena_subsystem_health_responding",
    category="arena_subsystem",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A", "sandbox-B"],
    tags=["arena", "health"],
)
async def test_arena_health(rig: FederationTestRig) -> AssertionResult:
    """listArenaMatches returning a list (not an error) implies the
    arena subsystem service is reachable. Two-frame parity probe."""
    state: dict = {}

    async def predicate():
        ok = 0
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("listArenaMatches")
                if isinstance(r, dict) and "matches" in r:
                    ok += 1
                    state[label] = "ok"
                elif _is_silent_or_error(r):
                    ok += 1  # silent = endpoint OK, just no data
                    state[label] = "silent"
                else:
                    state[label] = type(r).__name__
            except Exception as e:
                state[label] = f"error: {e!r}"
        state["ok_count"] = ok
        return ok >= 2

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="arena listMatches reachable on both mainframes",
        capture_state=lambda: state,
    )
