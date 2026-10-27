"""§BAFIN (2026-10-01): staking can be switched off per registry, and so can its rewards.

His words: "gate stacking behind a flag" and "remove all staking yelds figures from frontpage". The public
frames run as a test network whose units have no monetary value; a published annual rate (13.2 % to
18.4 %, served without login) and a daily distributor that would pay it were the most investment-like facts
on the platform, and the regulator inquiry describes the platform as it actually runs.

Two switches, because staking does two jobs here. A locked position is the only source of governance
weight (veToken, routers/governance.py), and it is also what the reward distributor pays on:

    STAKING_ENABLED          default "true". Off: no new positions at all (stake is refused). Rewards are off too.
    STAKING_REWARDS_ENABLED  default "true". Off: positions may still be opened for governance weight, but no
                             rate is published and nothing is paid. The compliant half on its own.

Both default ON, so a node that sets neither is byte-identical to before. An unknown value counts as ON (the
core/legacy_surfaces.py rule: a typo must never silently retire a surface a running network relies on); only
0/false/no/off disable.

What "off" does:
  * the rails that START a position (stake, on both rails) answer 403 with STAKING_DISABLED_SENTENCE;
  * the rails that GROW a reward (claim, estimate, auto-compound changes, the manual distribution) answer 403
    with REWARDS_DISABLED_SENTENCE; the code word comes first, because the RFC 7807 layer stringifies;
  * every APY-tier read answers no tiers, and every APY figure on a position or a stats read is 0;
  * the daily distributor pays nothing and records a skip (never a failure);
  * unstake, balances, positions and history keep working on every rail, so nobody's units are stuck, and
    governance keeps counting the positions that exist;
  * /api/v1/public/registry-config says staking_enabled / staking_rewards_enabled, and the console hides the
    staking surfaces and every rate where they are false.
"""
from __future__ import annotations

import os

from fastapi import HTTPException, status

_OFF = {"0", "false", "no", "off"}

STAKING_DISABLED_SENTENCE = (
    "staking_disabled: Locking is not enabled on this registry (STAKING_ENABLED=false). Units cannot be "
    "locked and no payout on locked units is made; existing positions can still be unlocked."
)
REWARDS_DISABLED_SENTENCE = (
    "staking_rewards_disabled: Paying out on locked units is not enabled on this registry (STAKING_REWARDS_ENABLED=false). "
    "No rate is published and no payout is made; existing positions keep their voting weight where votes count by "
    "locks, and can be unlocked."
)
# Kept for callers that only know one sentence.
DISABLED_SENTENCE = STAKING_DISABLED_SENTENCE


def _flag(name: str) -> bool:
    v = (os.getenv(name, "true") or "true").strip().lower()
    return v not in _OFF


def staking_enabled() -> bool:
    """Can a new position be opened here? Read per call, never cached: a flip takes effect on recreate."""
    return _flag("STAKING_ENABLED")


def staking_rewards_enabled() -> bool:
    """Is a staking rate published and paid here? Never true where staking itself is off."""
    return staking_enabled() and _flag("STAKING_REWARDS_ENABLED")


def require_staking_enabled() -> None:
    """FastAPI dependency for the rails that START a position (never for unstake)."""
    if not staking_enabled():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=STAKING_DISABLED_SENTENCE)


def require_staking_rewards_enabled() -> None:
    """FastAPI dependency for the rails that GROW a reward (claim, estimate, auto-compound, manual distribution)."""
    if not staking_rewards_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=STAKING_DISABLED_SENTENCE if not staking_enabled() else REWARDS_DISABLED_SENTENCE,
        )


def disabled_tiers_payload(shape: str = "engine") -> dict | list:
    """What an APY-tier read answers while rewards are off: no tiers, and the reason in words.

    `engine` mirrors DynamicAPYEngine.get_current_tiers ({"tiers": [...], "metadata": {...}}); `list` is the
    legacy list shape (routers/staking_rewards.py)."""
    if shape == "list":
        return []
    return {
        "tiers": [],
        "metadata": {
            "staking_enabled": staking_enabled(),
            "staking_rewards_enabled": False,
            "engine": "disabled",
            "note": STAKING_DISABLED_SENTENCE if not staking_enabled() else REWARDS_DISABLED_SENTENCE,
        },
    }


# W3 (agentvault2-d6, 2026-10-25; his words through agentvault2-69: "i want the illegal wording completly gone before
# opening"): the OpenAPI schema leaves out the routes these switches refuse, so a frame that runs neither locking nor
# payouts on locked units documents neither. A left-out route still answers (with the switch's sentence) when called.
# A route says which switch it obeys by its dependency (require_staking_enabled, require_staking_rewards_enabled); the
# payout reads that answer "no tiers" or zeros instead of refusing carry no dependency, so their paths are named here.
PAYOUT_READ_PATHS = (
    "/api/v1/staking/rewards/", "/api/v1/teg/rewards/", "/api/v1/staking/apy-tiers", "/api/v1/teg/staking/apy-tiers",
    "/api/v1/staking/claim-rewards", "/api/v1/tokenomics/rewards/",
)


def route_documented(path: str, dependency_calls) -> bool:
    """Is this route in the OpenAPI schema on this registry? `dependency_calls` are the callables its dependency tree
    holds (FastAPI's dependant, flattened). Read when the schema is built (once per process: the switches are env, a
    flip takes effect on recreate)."""
    calls = set(dependency_calls or ())
    if require_staking_enabled in calls and not staking_enabled():
        return False
    if require_staking_rewards_enabled in calls and not staking_rewards_enabled():
        return False
    if any(path == p or path.startswith(p) for p in PAYOUT_READ_PATHS) and not staking_rewards_enabled():
        return False
    return True
