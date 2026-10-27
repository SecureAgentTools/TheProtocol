"""D8 (his decision 2026-09-04, built 2026-09-05 for the fresh-network rehearsal) — the legacy money
surfaces are RETIRED BEHIND FLAGS, never deleted.

Each flag defaults to ON, so every node running today is byte-identical; the fresh frame's template
sets them OFF. A surface that is off is not mounted (or, for the arena bet, refuses with a sentence),
so it cannot move value on a network that never chose it.

  LEGACY_CONTRACTS_ENABLED   the pre-spine /api/v1/contracts/ RUC family (routers/contracts.py)
  TOKEN_BRIDGE_ENABLED       /api/v1/bridge/* wrapped-token transfers (routers/token_bridge.py)
  ARENA_BETTING_ENABLED      the Robo Wars `robowars_bet` tool (arena/mcp_server.py)
  (TEG side, same shape)     TEG_ONBOARDING_MINT_ENABLED — the TEG's own onboarding faucet
  (already flagged)          TREASURY_MM_ENABLED, TEG_STAKING_REWARD_CYCLE_ENABLED,
                             REGISTRY_STAKING_CLAIM_REWARDS_ENABLED (default off since R30/R33)
"""
from __future__ import annotations

import os

LEGACY_SURFACES = ("LEGACY_CONTRACTS_ENABLED", "TOKEN_BRIDGE_ENABLED", "ARENA_BETTING_ENABLED")
_OFF = {"0", "false", "no", "off"}


def surface_enabled(name: str, default: str = "true") -> bool:
    """True unless the env says off. An unknown value counts as ON — a typo must never silently
    retire a surface a running network relies on."""
    v = (os.getenv(name, default) or default).strip().lower()
    return v not in _OFF


def retired_sentence(name: str) -> str:
    return (f"This surface is retired on this registry ({name}=false, decision D8); "
            "the network it belongs to does not carry it.")
