# GÖDEL FORGE — the Arena Constitution (DRAFT, 2026-07-19).
#
# NOT ENFORCED YET: OPA on frame-c remains Commander-held OFF (see docker-compose.frame-c.yml
# comments); Python (`forge_flags` + IRONKEY) stays authoritative. When the F2 ratchet lands
# (sidecar → OPA_ENABLED=true shadow → enforce), these rules can only TIGHTEN what Python
# already allows — never grant. The L3 story: an island operator publishes THEIR evolution
# rules by editing this file, not by forking the code. Default-deny, per house style.
package agentvault.forge

import future.keywords.if
import future.keywords.every

# ── eval_run_allow — may this agent trigger an eval run right now? ──────────
# input: {agent_did, target_did, suite_id, runs_last_hour, agent_status}
default eval_run_allow = false

eval_run_allow if {
    input.agent_status == "active"
    input.runs_last_hour < 12          # per-agent trigger budget (arena pacing)
}

# ── spawn_rate_allow — may this lineage create another variant? ───────────────
# input: {parent_did, org_id, spawns_last_hour, lineage_size}
default spawn_rate_allow = false

spawn_rate_allow if {
    input.spawns_last_hour < 20        # generation pacing per lineage
    input.lineage_size < 500           # hard population cap per org
}

# ── verifier_admission — may this agent serve on a code_patch quorum? ───────
# Batch 8 (2026-07-20): the floors are CONCRETE now, mirroring the enforced python policy
# (forge_flags): locked ≥ 100 frame-currency, reputation ≥ 0 (ratchets as the population
# matures), Ed25519-signed verdicts required, endpoint published on the agent's own card.
# input: {verifier_did, has_verify_grant, staked_balance, reputation_score, is_candidate,
#         signs_verdicts, has_card_endpoint}
default verifier_admission = false

verifier_admission if {
    input.has_verify_grant == true     # org-consent grant row (never role-derived)
    input.is_candidate == false        # never judge yourself
    input.staked_balance >= 100        # stake floor (mirrors FORGE_VERIFIER_MIN_STAKE=100)
    input.reputation_score >= 0        # reputation floor (mirrors FORGE_VERIFIER_MIN_REPUTATION)
    input.signs_verdicts == true       # Ed25519 co-sign required (FORGE_VERIFIER_REQUIRE_SIG)
    input.has_card_endpoint == true    # grader URL published as agent_host on the card
}

# ── quorum_composition — is this SELECTED pool lawfully diverse? ────────────
# A pool property, not a per-verifier one: no single controlling operator may hold enough
# seats to constitute a quorum majority (mirrors python's per-developer cap = quorum_m − 1).
# input: {quorum_m, operator_seat_counts: {"<dev_id>": n, ...}}
default quorum_composition = false

quorum_composition if {
    every _, n in input.operator_seat_counts { n < input.quorum_m }
}

# ── royalty_cap — is this royalty configuration lawful on this island? ──────
# input: {royalty_bps, fork_depth}
default royalty_cap = false

royalty_cap if {
    input.royalty_bps <= 500           # Commander-decided hard cap
    input.fork_depth <= 3              # carve depth cap
}
