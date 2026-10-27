"""TheProtocol Registry Card v0.3 — SDK helpers.

Reference implementations:
  - compute_total_cost(agent_card, host_registry_card) → buyer cost breakdown
  - verify_registry_card(card, jwks) → True if signature verifies (EdDSA)
  - extract_signed_payload(card) → 13 canonical paths in deterministic order

Spec: https://docs.theprotocol.cloud/specs/registry-card-v0.3
"""
from .cost_composition import (
    SIGNED_CANONICAL_PATHS,
    compute_total_cost,
    extract_signed_payload,
)
from .card_verify import extract_paths, verify_registry_card

__all__ = [
    "SIGNED_CANONICAL_PATHS",
    "compute_total_cost",
    "extract_signed_payload",
    "extract_paths",
    "verify_registry_card",
]
