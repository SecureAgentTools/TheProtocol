"""GÖDEL FORGE — feature flags (all default OFF → byte-inert, IRONKEY/evals precedent).

The self-improving-harness arena. Frame-c is the live arena; everywhere else these read
false so the code ships dark (image uniformity, not activation). No flag here moves money
or authority on its own — royalty is Δ-neutral by construction, permissions ride IRONKEY.
"""
from __future__ import annotations

import os


def forge_enabled() -> bool:
    """Master switch — every /forge/* endpoint 403s when off, and the code_patch scorer,
    royalty carve, and eval_bounty auto-settle are all no-ops."""
    return os.getenv("FORGE_ENABLED", "false").strip().lower() == "true"


def evals_agent_trigger_enabled() -> bool:
    """May an agent (harness) self-trigger an eval run? Separate from EVALS_ENABLED (the
    runner) so the trigger surface stages independently."""
    return os.getenv("EVALS_AGENT_TRIGGER_ENABLED", "false").strip().lower() == "true"


def royalty_enabled() -> bool:
    """Carve fork royalties up the lineage at eval-pay / guild-settle. Off → payouts are
    undivided (today's behavior)."""
    return os.getenv("FORGE_ROYALTY_ENABLED", "false").strip().lower() == "true"


def verifier_quorum_m() -> int:
    """M in the N-of-M code_patch verifier quorum (default 3-of-5)."""
    try:
        return max(1, int(os.getenv("FORGE_VERIFIER_QUORUM", "3")))
    except (TypeError, ValueError):
        return 3


def verifier_min_stake() -> float:
    """Minimum staked balance for a code_patch verifier (anti-sybil). Default 0 = grant-only."""
    try:
        return max(0.0, float(os.getenv("FORGE_VERIFIER_MIN_STAKE", "0")))
    except (TypeError, ValueError):
        return 0.0


def verifier_min_reputation() -> float:
    """Minimum EigenTrust reputation_score for a code_patch verifier. Default 0 (batch 8):
    fresh jurors carry no reputation yet — the floor exists so islands can ratchet it as
    their verifier population matures, same staircase as the stake floor."""
    try:
        return max(0.0, float(os.getenv("FORGE_VERIFIER_MIN_REPUTATION", "0")))
    except (TypeError, ValueError):
        return 0.0


def verifier_max_per_operator() -> int:
    """Seat cap per controlling developer in a selected quorum pool (batch 8 anti-collusion):
    default quorum_m − 1, so NO single operator can constitute a quorum majority. Overridable
    per island via FORGE_VERIFIER_MAX_PER_OPERATOR (min 1)."""
    try:
        explicit = os.getenv("FORGE_VERIFIER_MAX_PER_OPERATOR", "").strip()
        if explicit:
            return max(1, int(explicit))
    except (TypeError, ValueError):
        pass
    return max(1, verifier_quorum_m() - 1)


def verifier_require_sig() -> bool:
    """When true, quorum votes without a VALID Ed25519 verifier co-signature are dropped.
    Default off: community verifiers without registered signing keys still count (their
    votes are stored as unsigned); flip per-frame once the verifier fleet signs."""
    return os.getenv("FORGE_VERIFIER_REQUIRE_SIG", "false").strip().lower() in ("1", "true", "yes", "on")


def royalty_default_bps() -> int:
    """Default fork royalty when a bundle sets none. Commander-decided 250 bps (cap 500)."""
    try:
        return max(0, min(500, int(os.getenv("FORGE_ROYALTY_DEFAULT_BPS", "250"))))
    except (TypeError, ValueError):
        return 250


ROYALTY_MAX_BPS = 500       # hard cap (Commander-decided)
ROYALTY_MAX_DEPTH = 3       # nearest fork-ancestors that share (Commander-decided)
