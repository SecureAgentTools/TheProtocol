# JURISDICTION PROFILES (2026-07-31, frame-c testbed).
#
# WHY THIS FILE EXISTS.
# Every risky surface on this platform is already flag-bound (AGORA, FX, Guild, Forge, fiat,
# cross-registry transfers). A jurisdiction profile is the OPERATOR'S declaration of which of
# those surfaces the law applicable to THEM permits on THEIR deployment. The registry enforces
# that declaration in Python (deny-only, pre-escrow, off the OPA critical path per §V0119);
# this policy exists for the three things Python cannot do:
#
#   1. Be the auditable artifact. A compliance claim that lives only in an if-statement is not
#      reviewable by an auditor. This file is.
#   2. Feed the enforce-impact simulator (/ui#/admin/opa). An operator can replay REAL captured
#      traffic against a candidate profile and see exactly what would start being denied BEFORE
#      arming it. That is the difference between a policy and a guess.
#   3. Hold the coherence rule (I-J2) that CAN disagree with reality: a deployment whose
#      declared profile denies a feature while that feature's live flag is still ON is
#      misconfigured, and no single Python path owns that comparison (it spans the profile
#      document, the flag store, and the signed registry card).
#
# WHAT THIS FILE IS NOT.
# It contains NO per-country legal conclusions, and it never will. Naming jurisdictions here
# would mean operators rely on OUR legal analysis, which is exactly the liability we are
# declining to take. The Provider ships mechanism; the operator declares the profile and
# warrants it fits their law (Federation Operator Terms § 4.4).
#
# Absent profile = unrestricted (allow), matching the Python evaluator: declaring a profile
# RESTRICTS, it never silently widens. Deny-only and pre-escrow, therefore Δ-irrelevant.
package agentvault.jurisdiction

import future.keywords.if
import future.keywords.in
import future.keywords.contains   # §MONITORING S0 (2026-09-28): a partial SET under Rego v1 says `contains`

# The closed feature vocabulary. Must stay in lockstep with
# services/jurisdiction.py::FEATURES — the E2E asserts both evaluators agree.
features := {"exchange", "fx", "guild", "forge", "fiat", "cross_transfer"}

# ── I-J1: feature permitted under the declared profile ──────────────────────
# input: {feature, amount?, profile: {name, version, features{}, limits{}} | null}
default jurisdiction_ok = false

# No profile declared => this deployment has declared no restriction => allow.
jurisdiction_ok if {
    not input.profile
}

jurisdiction_ok if {
    input.profile
    feature_allowed
    limit_ok
}

# A feature is allowed unless the profile explicitly says false. Omitted keys are allowed:
# the operator restricts what they name, and absent-profile already allows everything, so
# defaulting omissions to deny would make a partial declaration harsher than no declaration.
feature_allowed if {
    not denied_feature
}

denied_feature if {
    input.profile.features[input.feature] == false
}

# Limits apply per feature. Today only cross_transfer carries an amount ceiling.
default limit_ok = true

limit_ok = false if {
    input.feature == "cross_transfer"
    cap := input.profile.limits.max_transfer_amount
    is_number(cap)
    input.amount > cap
}

# Reason string for the decision ring / simulator output (human-readable, not a gate).
reason := "no_profile_declared" if { not input.profile }
reason := sprintf("feature_denied:%s", [input.feature]) if { denied_feature }
reason := sprintf("limit_exceeded:max_transfer_amount:%v", [input.profile.limits.max_transfer_amount]) if {
    input.profile
    not denied_feature
    not limit_ok
}
reason := "allowed" if {
    input.profile
    not denied_feature
    limit_ok
}

# ── I-J2: declared-vs-live coherence ────────────────────────────────────────
# THE RULE THAT CAN DISAGREE WITH REALITY, which is the only reason it earns its keep.
# A profile that denies `exchange` while the venue flag is still ON means the deployment is
# advertising a restriction its runtime does not implement: either the profile was declared
# and the flag never flipped, or a flag was re-enabled after the declaration. The signed
# registry card publishes the declaration to peers, so an incoherent deployment is publishing
# a claim it does not honour. That is a compliance defect, not a preference.
#
# input: {profile, live_flags: {exchange: bool, fx: bool, guild: bool, forge: bool, fiat: bool}}
default profile_coherent = true

profile_coherent = false if {
    some f
    features[f]
    input.profile.features[f] == false
    input.live_flags[f] == true
}

incoherent_features contains f if {
    features[f]
    input.profile.features[f] == false
    input.live_flags[f] == true
}
