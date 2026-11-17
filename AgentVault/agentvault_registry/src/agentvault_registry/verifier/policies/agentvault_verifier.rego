# LAYER C OF THE OPA BACKSTOP: the independent verifier's own rules (V0666, gwo_bec4b18190831482a6463d46).
#
# I1 (flag pairing) and I-J2 (profile coherence) are judged by identity-fabric/policies, the one source of those two rules: the
# verifier loads that directory beside this file and never holds a copy. These three have no policy anywhere else, because the
# facts they judge are RECORDS (rows the registry wrote, a route list it serves), not a request.
#
# Every input is built by ONE shared builder from facts the verifier read itself (verifier/inputs.py); a test moves each fact
# and sees its input key move (no literal inputs). The rules detect: a verdict of false becomes a metric, a vmalert rule and a
# line in the findings file, and blocks nothing.
package agentvault.verifier

import rego.v1

# --- fiat is buy-only (I6's recorded form) ------------------------------------------------------------------------------------
# input: {out_routes: [paths of the node's API that pay fiat out], not_in: purchases that are not an inflow of EUR for units,
#         issued: purchases whose credit is an issuance in the ledger}
# I6 itself (agentvault_invariants.rego) asks for `custodial_balance`, a fact no record holds; this form asks only what is recorded.
default fiat_buy_only := false

fiat_buy_only if {
	count(input.out_routes) == 0
	input.not_in == 0
	input.issued == 0
}

# --- a code change merged only on the record -----------------------------------------------------------------------------------
# input: see verifier/inputs.py::merge_needs_the_record. The rule is the doctrine of sessionlogs2026/DESIGN_2026-11-15_OPA_BACKSTOP.md
# section 6, row 6: a change merges with its signed checker record, an independent review, a passed ballot (the bootstrap go stands
# for it only while the frame has few members), a veto window that ran without a veto or the maintainer's go, and only inside its
# paths. The merged commit is the voted commit is the checked commit.
default merge_needs_the_record := false

merge_needs_the_record if {
	input.acceptance_ok == true
	input.read_from_checker == true
	input.accepted_commit == input.voted_commit
	input.merged_commit == input.voted_commit
	input.veto_present == false
	ballot_stands
	window_closed_or_go
	input.approvals >= input.approvals_needed
	input.blockers == 0
	input.paths_outside_scope == 0
}

ballot_stands if input.ballot_passed == true

ballot_stands if input.bootstrap_go == true

window_closed_or_go if input.go_present == true

# passed_at null: the pass time is unknown, so the window cannot be counted (arithmetic on null is undefined: the rule is false)
window_closed_or_go if input.merged_at >= input.passed_at + input.window_seconds

# --- a deletion honoured on its schedule ----------------------------------------------------------------------------------------
# input: {pending, requested_at, cooling_off_seconds, grace_seconds, now}: an account still pending after its cooling-off AND one
# cycle of the anonymizer (the grace) is overdue.
default deletion_on_schedule := true

deletion_on_schedule := false if {
	input.pending == true
	input.now > input.requested_at + input.cooling_off_seconds + input.grace_seconds
}
