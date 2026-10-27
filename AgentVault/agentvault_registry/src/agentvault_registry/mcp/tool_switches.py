"""Which public MCP tools are LISTED depends on the registry's switches (W3, agentvault2-d6, 2026-10-25; his words through
agentvault2-69: "i want the illegal wording completly gone before opening").

A tool that starts a lock is listed only where STAKING_ENABLED is on; a tool that pays, rates, relocks, distributes or
reports a payout on locked units only where STAKING_REWARDS_ENABLED is on. These are the switches the routes themselves
obey (core/staking_gate.py, read per call, so a flip takes effect on recreate). Unlocking and the lock reads stay listed
everywhere: core/staking_gate.py keeps them working whatever the switches say, so nobody's units are stuck.

Listing is what a client is told, never what it may try: a tool that is not listed still executes when called by its
name (tools/call, invokeTool), and its route refuses with the switch's own sentence where the switch is off. Every door
that ENUMERATES tools (tools/list, GET /mcp/tools, searchTools, describeTools, listToolsets, the counts and the
initialize instructions) goes through filter_listed().
"""
from __future__ import annotations

from typing import Iterable, List

from ..core import legacy_surfaces, staking_gate

_P = "theprotocol_"

NEEDS_STAKING = frozenset(_P + n for n in ("lockUnits", "tegLockDirect"))

NEEDS_STAKING_PAYOUTS = frozenset(_P + n for n in (
    "claimLockPayouts", "estimateMyLockPayouts", "getLockPayoutTiers", "getLockPayoutTiersTeg", "getLockPayoutRuns",
    "getLockPayoutRecords", "getLockPayoutStats", "getMyPayoutHistory", "getAgentPayoutHistory", "getAgentPendingPayouts",
    "claimTegPayouts", "getUnitPayouts", "getMyPayoutRelock", "updatePayoutRelock", "getPayoutRelockForAgent",
    "triggerLockPayoutRun",
))

NEEDS_STAKING_PROMPTS = frozenset({"lock_units"})

# Arena betting is a retired surface where ARENA_BETTING_ENABLED is off (core/legacy_surfaces.py, D8): its bet reads are
# not listed there (his word through agentvault2-69, 2026-10-25 21:15Z); the route refuses with the surface's sentence.
NEEDS_ARENA_BETTING = frozenset({_P + "getArenaMatchBets"})


def listed(name: str) -> bool:
    if name in NEEDS_STAKING:
        return staking_gate.staking_enabled()
    if name in NEEDS_STAKING_PAYOUTS:
        return staking_gate.staking_rewards_enabled()
    if name in NEEDS_ARENA_BETTING:
        return legacy_surfaces.surface_enabled("ARENA_BETTING_ENABLED")
    return True


def filter_listed(schemas: Iterable[dict]) -> List[dict]:
    return [s for s in schemas if listed(s.get("name", ""))]


def prompt_listed(name: str) -> bool:
    if name in NEEDS_STAKING_PROMPTS:
        return staking_gate.staking_enabled()
    return True
