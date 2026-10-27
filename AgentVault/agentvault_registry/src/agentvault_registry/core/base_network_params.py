"""
core/base_network_params.py — Canonical Locked Parameter Set

Every federated registry must comply with these values exactly.
Deviation on CRITICAL/HIGH params triggers immediate or 48-hour quarantine.

Imported by:
  - services/federation_policy_validator.py  (validation)
  - services/federation_compliance_monitor.py (drift detection)
  - background_tasks/compliance_poller.py     (hash check)

Author: OWL-23 / Phase 1 Implementation
Date: 2026-03-12
"""
from enum import Enum
from typing import Dict, Any, Optional


class DriftSeverity(str, Enum):
    CRITICAL = "CRITICAL"   # Immediate quarantine, no grace
    HIGH     = "HIGH"       # 48-hour grace → quarantine
    MEDIUM   = "MEDIUM"     # 7-day grace → quarantine
    LOW      = "LOW"        # 14-day grace → soft quarantine


# ── LOCKED PARAMETERS ─────────────────────────────────────────────────────────
# These must match EXACTLY in submitted policy. Any deviation = admission denied.
# Keys use dotted path notation; deep_get() in the validator traverses nested dicts.

LOCKED_PARAMS: Dict[str, Any] = {
    # Supply integrity
    "supply_integrity.supply_invariant_check_enabled": True,
    "supply_integrity.auto_lockdown_on_invariant_breach": True,
    "supply_integrity.opa_minting_ban_for_federated_teg": True,
    "supply_integrity.eventstore_double_entry_validation": True,
    "supply_integrity.genesis_only_minting": True,
    "supply_integrity.cryptographic_mint_signatures_required": True,
    # Fee engine
    # Fee rates are governance-configurable. Current network values (2026-04-19):
    # 0.5% base, 5% max velocity-scaled. If governance moves these values, update
    # this file in the same PR as the policy-change proposal so the compliance
    # validator stays aligned with the live network.
    "transaction_fees.base_rate_percent": 0.5,
    "transaction_fees.max_rate_percent": 5.0,
    "transaction_fees.velocity_scaling_factor": 1.0,
    "transaction_fees.destination": "treasury_recycle",
    # Staking rewards
    "staking_rewards.max_apy_percent": 15.0,
    "staking_rewards.decay_steepness_k": 0.05,
    "staking_rewards.circuit_breaker_tvl_percent": 75.0,
    "staking_rewards.reputation_floor_for_rewards": 0.05,
    "staking_rewards.slashing_insurance_prohibited": True,
    # Enforcement
    "enforcement.force_unstake_enabled": True,
    "enforcement.force_unstake_min_penalty_percent": 10,
    "enforcement.fourth_offense_auto_suspend": True,
    "enforcement.slashing_insurance": "PROHIBITED",
    # EigenTrust canonical algorithm constants
    "reputation.eigentrust.teleportation_alpha": 0.15,
    "reputation.eigentrust.epoch_decay": 0.95,
    "reputation.eigentrust.volume_weight_exponent": 0.3,
    # Governance hard caps
    "governance.max_lock_days": 365,
    "governance.flexible_stake_ve_multiplier_max": 0.01,
}


# ── BOUNDED PARAMETERS ────────────────────────────────────────────────────────
# These must fall within [min, max]. None = no bound on that side.

BOUNDED_PARAMS: Dict[str, Dict[str, Optional[float]]] = {
    "transaction_fees.velocity_target":               {"min": 0.5,   "max": 2.0},
    "staking_rewards.min_apy_percent":                {"min": 0.5,   "max": 5.0},
    "staking_rewards.tvl_target_percent":             {"min": 20.0,  "max": 60.0},
    "staking_rewards.treasury_buffer_warning_days":   {"min": 7,     "max": 90},
    "enforcement.reputation_bond_min_avt":            {"min": 50,    "max": None},
    "enforcement.bond_maturity_min_transactions":     {"min": 5,     "max": None},
    "enforcement.bond_maturity_min_age_days":         {"min": 7,     "max": None},
    # §BONDFILL-3 (2026-09-11) — the trust gate becomes RELATIVE, and maturity unlocks capital.
    # `bond_min_eigentrust_at_maturity` (floor 0.10) is RETIRED: an absolute threshold on a
    # NORMALISED vector cannot be met — on EU the whole vector sums to 1.0, the treasury holds
    # 99.67% of it, and the best real agent held 0.00028. Worse, every new agent SHRINKS every
    # existing share, so that gate got harder the more successful the network became. It was
    # also guarding a key NO CODE READ (the gate read `reputation_bond.min_eigentrust`, unbounded).
    "enforcement.bond_maturity_min_trust_percentile": {"min": 50,    "max": 95},
    # Evidence floor: distinct counterparties, owned by OTHER developers, who rated the agent
    # satisfactory. Ten settlements with one friend is not ten opinions.
    "enforcement.bond_maturity_min_rated_peers":      {"min": 3,     "max": 100},
    # 🔴 THE INVARIANT: max 80, so MATURED NEVER MEANS UNBONDED. There is always residual skin
    # in the game, and maturity can never be declared into a free pass. The resolver enforces
    # the ceiling at USE time as well, because an env knob does not pass through this table.
    "enforcement.bond_maturity_releases_percent":     {"min": 0,     "max": 80},
    "enforcement.offense_window_days":                {"min": 30,    "max": 365},
    "enforcement.frozen_balance_release_days":        {"min": 90,    "max": None},
    "reputation.eigentrust.convergence_epsilon_max":  {"min": None,  "max": 1e-4},
    "reputation.eigentrust.max_iterations_min":       {"min": 50,    "max": None},
    "reputation.eigentrust.cosine_similarity_threshold_min": {"min": 0.20, "max": None},
    "reputation.epoch_duration_hours":                {"min": 1,     "max": 24},
    "governance.standard_quorum_percent":             {"min": 5,     "max": 40},
    "governance.standard_pass_percent":               {"min": 40,    "max": 70},
    "governance.policy_change_quorum_percent":        {"min": 20,    "max": 50},
    "governance.policy_change_pass_percent":          {"min": 55,    "max": 80},
    "governance.min_stake_to_propose_avt":            {"min": 10,    "max": 10000},
    # §TRUSTPOLICY (2026-09-11) — a frame decides what it does about a peer it
    # distrusts, within bounds the network can state. The floor on
    # min_interactions is the important one: acting on a peer with almost no
    # evidence is how the Beta(1,1) prior (0.5 = "nothing observed") gets
    # mistaken for a bad reputation.
    "peer_trust.min_interactions":                   {"min": 5,     "max": 1000},
    "peer_trust.warn_below":                         {"min": 0.10,  "max": 0.95},
    "peer_trust.restrict_below":                     {"min": 0.10,  "max": 0.90},
    "peer_trust.suspend_below":                      {"min": 0.05,  "max": 0.80},
    "peer_trust.recover_margin":                     {"min": 0.01,  "max": 0.30},
}


# ── SEVERITY MAP ──────────────────────────────────────────────────────────────
# Maps each locked param to its drift response severity.

PARAM_SEVERITY: Dict[str, DriftSeverity] = {
    "supply_integrity.supply_invariant_check_enabled":         DriftSeverity.CRITICAL,
    "supply_integrity.auto_lockdown_on_invariant_breach":      DriftSeverity.CRITICAL,
    "supply_integrity.opa_minting_ban_for_federated_teg":      DriftSeverity.CRITICAL,
    "supply_integrity.eventstore_double_entry_validation":     DriftSeverity.CRITICAL,
    "supply_integrity.genesis_only_minting":                   DriftSeverity.CRITICAL,
    "supply_integrity.cryptographic_mint_signatures_required": DriftSeverity.CRITICAL,
    "transaction_fees.base_rate_percent":                      DriftSeverity.HIGH,
    "transaction_fees.max_rate_percent":                       DriftSeverity.HIGH,
    "transaction_fees.velocity_scaling_factor":                DriftSeverity.HIGH,
    "transaction_fees.destination":                            DriftSeverity.HIGH,
    "staking_rewards.max_apy_percent":                         DriftSeverity.HIGH,
    "staking_rewards.decay_steepness_k":                       DriftSeverity.MEDIUM,
    "staking_rewards.circuit_breaker_tvl_percent":             DriftSeverity.MEDIUM,
    "staking_rewards.reputation_floor_for_rewards":            DriftSeverity.MEDIUM,
    "staking_rewards.slashing_insurance_prohibited":           DriftSeverity.HIGH,
    "enforcement.force_unstake_enabled":                       DriftSeverity.HIGH,
    "enforcement.force_unstake_min_penalty_percent":           DriftSeverity.HIGH,
    "enforcement.fourth_offense_auto_suspend":                 DriftSeverity.HIGH,
    "enforcement.slashing_insurance":                          DriftSeverity.HIGH,
    "reputation.eigentrust.teleportation_alpha":               DriftSeverity.HIGH,
    "reputation.eigentrust.epoch_decay":                       DriftSeverity.HIGH,
    "reputation.eigentrust.volume_weight_exponent":            DriftSeverity.MEDIUM,
    "governance.max_lock_days":                                DriftSeverity.LOW,
    "governance.flexible_stake_ve_multiplier_max":             DriftSeverity.LOW,
}

# Grace periods in hours (0 = immediate quarantine)
GRACE_PERIOD_HOURS: Dict[DriftSeverity, int] = {
    DriftSeverity.CRITICAL: 0,
    DriftSeverity.HIGH:     48,
    DriftSeverity.MEDIUM:   168,   # 7 days
    DriftSeverity.LOW:      336,   # 14 days
}
