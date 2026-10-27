# CROSS-CUTTING SECURITY INVARIANTS (2026-07-28, frame-c shadow).
#
# WHY THIS FILE EXISTS.
# The three deployed policies (agentvault_admin / _developer / _agent) are verbatim
# restatements of the Python checks they mirror. Measured over 344,000 live decisions they
# have NEVER disagreed with Python once — not because the system is healthy, but because a
# policy that restates its subject is structurally incapable of disagreeing. Enforcing them
# would add zero security and put OPA latency on every authenticated request.
#
# These rules are different: every one of them encodes an invariant that NO single Python
# code path owns, because each spans two or more subsystems. That is the only thing OPA is
# uniquely good at, and it is where the value is. A rule belongs in this file only if it can
# produce a decision Python does not already make.
#
# Default-deny throughout, per house style. Shadow on frame-c; enforce is Commander-held.
# In enforce mode OPA returns `python AND opa` — these can only ever TIGHTEN, never grant.
package agentvault.invariants

import future.keywords.if

# ── I1: IRONKEY flag pairing ────────────────────────────────────────────────
# THE RULE THAT WOULD HAVE CAUGHT 2026-07-28.
# AGENT_RBAC_MODE and AGENT_DELEGATION_MODE are documented as independent, and in the ALLOW
# direction they are. In the DENY direction they are NOT. With rbac=enforce + delegation=off,
# `resolve_capability` is never consulted, so an agent whose authority arrives on an `att_`
# capability token is left with only its (correctly empty) role set and is denied everything.
#
# Observed live: forge-spawned children hold ZERO roles by design and carry `cicd.version` on
# a birth token (forge_harness_daemon.py:288 -> POST /agents/spawn, consumed via the
# X-Capability-Token header). Under rbac=shadow they logged
#   perm=cicd.version decision=DENY held=['enforcement.self','read.profile']
# on registry-a AND frame-b, while frame-c ran the identical forge under enforce with zero
# denials — for one reason only: frame-c had BOTH flags on. Same code, opposite outcome,
# purely from flag pairing.
#
# No Python function owns this; it spans two env flags, two subsystems and sixteen registries.
# input: {rbac_mode, delegation_mode}   values: off | shadow | enforce
default flag_pairing_ok = false

# rbac not enforcing => nothing can be wrongly denied, so any delegation mode is safe.
flag_pairing_ok if {
    input.rbac_mode != "enforce"
}

# rbac enforcing => delegation MUST also enforce, or capability-token authority vanishes.
# NOTE: enforce/shadow is deliberately NOT allowed. Shadow delegation resolves and logs but
# is not proven to EXTEND authority, and we do not ship on an unproven reading.
flag_pairing_ok if {
    input.rbac_mode == "enforce"
    input.delegation_mode == "enforce"
}

# ── I2: SPIFFE trust-domain binding ─────────────────────────────────────────
# A peer's mTLS identity must belong to the trust domain of the frame it claims to be.
# Python checks this piecemeal across the federation paths (and §PEERFIX 2026-07-26 showed
# what a single missed spelling costs: mainframe<->mainframe replication was dead, silently,
# because four lookups used exact-case `=`). As ONE policy it becomes a single auditable rule.
# mTLS authenticates the CHANNEL; this asserts the channel matches the claimed origin.
# input: {peer_spiffe_id, expected_trust_domain}
default trust_domain_bound = false

trust_domain_bound if {
    input.peer_spiffe_id != ""
    input.expected_trust_domain != ""
    startswith(lower(input.peer_spiffe_id), lower(sprintf("spiffe://%s/", [input.expected_trust_domain])))
}

# ── I3: admin blast radius ──────────────────────────────────────────────────
# `bulk_suspend` against 1,400 agents should not be one click away from one JWT. Python
# authorizes the ACTION (is_admin) but never the SCALE. This is a pure cross-cutting cap.
# input: {target_count, confirmed, is_admin}
default bulk_blast_radius_ok = false

bulk_blast_radius_ok if {
    input.is_admin == true
    input.target_count <= 50
}

# Above the cap an explicit second signal is required — scale becomes a deliberate act.
bulk_blast_radius_ok if {
    input.is_admin == true
    input.target_count > 50
    input.confirmed == true
}

# ── I4: global read-only / break-glass ──────────────────────────────────────
# One switch honored everywhere, so no money path has to implement its own. Reads always
# pass; writes pass only when read-only mode is off. Nothing in Python owns a global lever
# like this today — it would otherwise have to be threaded through every router.
# input: {readonly_mode, method}
default write_allowed = false

write_allowed if {
    input.method == "GET"
}

write_allowed if {
    input.method == "HEAD"
}

write_allowed if {
    input.readonly_mode == false
}

# ── I5: liability gate composition ──────────────────────────────────────────
# COCKPIT CARD (PART 15): when liability is ENFORCED and the action carries real money, a
# live mandate must back it. Python's `check_liability_gate` owns the per-contract decision;
# this owns the COMPOSITION — the fact that mode + value + mandate must be considered
# together. Deny-only and pre-escrow, so Δ-irrelevant by construction.
# input: {liability_mode, amount, threshold, has_live_mandate}
default liability_composition_ok = false

liability_composition_ok if {
    input.liability_mode != "enforce"
}

liability_composition_ok if {
    input.liability_mode == "enforce"
    input.amount <= input.threshold
}

liability_composition_ok if {
    input.liability_mode == "enforce"
    input.amount > input.threshold
    input.has_live_mandate == true
}

# ── aggregate ───────────────────────────────────────────────────────────────
# Convenience roll-up for callers that want one boolean. Absent sub-inputs default to their
# own default-false, so this is deliberately STRICT: a caller must supply what it asserts.
default all_ok = false

all_ok if {
    flag_pairing_ok
    trust_domain_bound
    bulk_blast_radius_ok
    write_allowed
    liability_composition_ok
}

# ═══════════════════════════════════════════════════════════════════════════
# BATCH 2 (2026-07-28) — regulatory + topology hard rules.
#
# These encode rules that today exist ONLY AS PROSE in PRODUCTION_DOCS and in the Commander's
# head. Prose cannot deny a request. Each is a documented "never", each spans subsystems, and
# each is cheap to state and expensive to violate.
# ═══════════════════════════════════════════════════════════════════════════

# ── I6: fiat is buy-only, and never issues ──────────────────────────────────
# Fiat_Rails_Strategy.md:111 "Buy-only: no fiat-out endpoint exists, ever. Commander hard rule
# (MiCA + BaFin trip-wire)" and :225 "No auto-mint on fiat purchase ... Commander explicitly
# rejected auto-mint." Today those are guaranteed only by nobody having written the endpoint.
# This makes the guarantee ACTIVE: if a fiat-out or auto-mint path is ever added by accident,
# refactor, or an over-eager agent, the policy denies it on arrival.
# A regulatory trip-wire should not depend on continued absence of code.
# input: {direction, mints_tokens, custodial_balance}
default fiat_flow_ok = false

fiat_flow_ok if {
    input.direction == "in"          # EUR -> AVT only. "out" has no legal path here.
    input.mints_tokens == false      # funded from the waterfall, never a fresh mint
    input.custodial_balance == false # we never hold customer fiat
}

# ── I7: issuing authority ─────────────────────────────────────────────────────
# PART 2: "minting is disabled in federated mode"; PART 5 FLOW 12 gates fiat genesis on
# FIAT_GENESIS_REGISTRY (NOT IS_CENTRAL_REGISTRY — a distinction that has already caused
# confusion). Issuance is the ONLY operation that can break Δ=0, the prime directive, so the
# authority to do it deserves a rule of its own rather than an env-var read scattered across
# call sites.
# input: {federated_mode, is_genesis_registry, actor_is_admin, via_mint_proxy}
default mint_allowed = false

mint_allowed if {
    input.federated_mode == false    # a federated registry may never mint, full stop
    input.is_genesis_registry == true
    input.actor_is_admin == true
    input.via_mint_proxy == true     # TEG mints, the registry mint-proxy emits (f037)
}

# ── I8: one settlement authority ───────────────────────────────────────────
# §XFRAME: "a contract lives on the frame holding its ESCROW — one settlement authority (two
# frames both able to release = a double-spend awaiting a partition)". Cross-frame replicas are
# read-only couriers: `actor_did` is the principal and must be party to THAT contract; mTLS
# authenticates the channel, never the actor.
# input: {escrow_frame, executing_frame, is_replica, actor_is_party}
default contract_settlement_ok = false

contract_settlement_ok if {
    input.is_replica == false                     # a replica may never settle
    input.escrow_frame == input.executing_frame   # settle only where the money is
    input.actor_is_party == true                  # courier != principal
}

# ── I9: revoked / quarantined peers carry no money ─────────────────────────
# Federation licences are revocable and revocation is meant to bite ("economic quarantine",
# PART 2). §HARDENING S4 wired revoked licences into the shared mTLS/secret auth gate, but the
# MONEY rails are a separate surface. A peer can be authenticated and still be untrusted: this
# separates "may connect" from "may move value", which is exactly the distinction a compliance
# regulator asks about.
# input: {peer_status, license_status, is_money_operation}
default peer_value_transfer_ok = false

peer_value_transfer_ok if {
    input.is_money_operation == false   # non-money federation traffic is out of scope here
}

# We ARE this peer's licensor and hold a record: it must say active.
peer_value_transfer_ok if {
    input.is_money_operation == true
    input.peer_status == "ACTIVE"       # PG enums are UPPERCASE (standing gotcha)
    input.license_known == true
    input.license_status == "active"
}

# We are NOT this peer's licensor, so we hold no record. CORRECTED 2026-07-28 after shadow
# mode caught this on REAL traffic: the first draft demanded `license_status == "active"`
# unconditionally, which is unsatisfiable for a foreign-frame peer — each frame licenses only
# its OWN operator family (frame-c holds rows for doha/telaviv/riyadh/abudhabi and nothing
# else), so enforcing that draft would have denied every legitimate C→A and C→B transfer.
# ABSENCE OF A RECORD IS NOT EVIDENCE OF REVOCATION. The teeth stay where we have standing:
# a record we DO hold that is revoked/suspended still fails every clause above.
peer_value_transfer_ok if {
    input.is_money_operation == true
    input.peer_status == "ACTIVE"
    input.license_known == false
}

# ── I10: venue halt is absolute ────────────────────────────────────────────
# AGORA has both a global halt and per-listing halt/delist. A halt exists for exactly the moment
# when something is going wrong, which is also the moment a retry loop or a worker is most likely
# to keep submitting. Making the halt a policy means every order path honours it identically,
# including any path added later that forgets to check.
# input: {global_halt, listing_status, action}
default venue_order_ok = false

venue_order_ok if {
    input.global_halt == false
    input.listing_status == "approved"
    input.action != "cancel"
}

# Cancels stay legal during a halt ON PURPOSE: a halt must let participants OUT of the book, or
# it becomes a trap that strands live orders behind a safety mechanism.
venue_order_ok if {
    input.action == "cancel"
}
