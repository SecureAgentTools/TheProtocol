"""V0666 layer C: each rule judged by the REAL Rego (gwo_bec4b18190831482a6463d46). A case it flags and one it passes for every
rule, from the same facts through the same builder the verifier runs (no literal input), and a control that breaks ONE fact of a
clean set and sees the alert.

The rules:
  iron_pairing           I1 of identity-fabric/policies/agentvault_invariants.rego: AGENT_RBAC_MODE enforce needs AGENT_DELEGATION_MODE enforce
  jurisdiction_coherent  I-J2 of agentvault_jurisdiction.rego: a feature the declared profile denies must not be switched on
  fiat_buy_only          verifier/policies/agentvault_verifier.rego: no fiat-out route in the node's API, every purchase an inflow, none an issuance
  merge_needs_the_record the same file: a merged change holds a passing checker record of the merged commit, a passed ballot (or the
                         bootstrap go), no veto, a closed veto window or the maintainer's go, the independent reviews, and only its paths
  deletion_on_schedule   the same file: an account whose deletion's cooling-off ended is anonymized within the grace

Skipped unless OPA_VERIFIER_BIN names an opa binary and OPA_VERIFIER_POLICY_DIR the stack's identity-fabric/policies directory
(the verifier's image mounts that directory read-only; one source for I1 and I-J2, never a copy). Skipped, never silently passed.
RED on d689b3b68: there is no verifier.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import pathlib

import pytest

BIN = os.environ.get("OPA_VERIFIER_BIN")
POLICY_DIR = os.environ.get("OPA_VERIFIER_POLICY_DIR")
if not (BIN and POLICY_DIR and os.path.exists(BIN) and os.path.isdir(POLICY_DIR)):
    pytest.skip("needs an opa binary (OPA_VERIFIER_BIN) and the stack's identity-fabric/policies (OPA_VERIFIER_POLICY_DIR). "
                "Skipped, never silently passed.", allow_module_level=True)

from agentvault_registry.verifier import evaluator, inputs, rules, runner  # noqa: E402
from tests._opa_verifier_facts import GOOD, NOW, deep  # noqa: E402

OWN = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "verifier" / "policies"
H = lambda n: dt.timedelta(hours=n)  # noqa: E731
D = lambda n: dt.timedelta(days=n)  # noqa: E731


@pytest.fixture(scope="module")
def opa():
    return evaluator.OpaEvaluator(BIN, [POLICY_DIR, str(OWN)])


def decide(opa, rule, facts):
    r = rules.RULES[rule]
    return asyncio.run(opa.decide(r.rego, r.build(facts)))


def mutate(rule, fn):
    f = deep(GOOD[rule])
    fn(f)
    return f


CASES = [
    # (rule, what is broken, the facts) -> every one is a violation; GOOD is the pass of each
    ("iron_pairing", "rbac enforce, delegation off", lambda f: f["env"].update(AGENT_DELEGATION_MODE="off")),
    ("iron_pairing", "rbac enforce, delegation shadow (unproven authority)", lambda f: f["env"].update(AGENT_DELEGATION_MODE="shadow")),
    ("jurisdiction_coherent", "profile denies exchange, the venue is on", lambda f: f["env"].update(EXCHANGE_ENABLED="true")),
    ("jurisdiction_coherent", "profile denies guild, guild is on", lambda f: f["profile"]["features"].update(guild=False)),
    ("fiat_buy_only", "a payout route exists", lambda f: f["paths"].append("/api/v1/fiat/payout")),
    ("fiat_buy_only", "a withdraw route exists", lambda f: f["paths"].append("/api/v1/fiat/withdraw/{id}")),
    ("fiat_buy_only", "a purchase that is not an inflow", lambda f: f.update(purchases_not_in=1)),
    ("fiat_buy_only", "a purchase that issued units", lambda f: f.update(purchases_issued=1)),
    ("merge_needs_the_record", "the checker's record failed", lambda f: f["change"]["acceptance"].update(ok=False)),
    ("merge_needs_the_record", "the record is of another commit", lambda f: f["change"]["acceptance"]["record"].update(commit="b" * 40)),
    ("merge_needs_the_record", "the record was not read from the checker", lambda f: f["change"]["acceptance"]["record"].update(read_from="caller")),
    ("merge_needs_the_record", "the ballot failed", lambda f: f["change"].update(proposal_status="FAILED")),
    ("merge_needs_the_record", "no ballot at all", lambda f: f["change"].update(proposal_status=None)),
    ("merge_needs_the_record", "vetoed", lambda f: f["change"].update(veto={"by": 1})),
    ("merge_needs_the_record", "merged inside the veto window without the go",
     lambda f: f["change"].update(passed_at=NOW - H(2))),
    ("merge_needs_the_record", "no independent review", lambda f: f["reviews"].clear()),
    ("merge_needs_the_record", "the only review is the proposer's own", lambda f: f["reviews"].__setitem__(0, {**f["reviews"][0], "reviewer_developer_id": 1})),
    ("merge_needs_the_record", "a review asks for changes", lambda f: f["reviews"].append({"reviewer_developer_id": 3, "verdict": "changes", "commit": "a" * 40, "at": 2.0})),
    ("merge_needs_the_record", "the approval is of an older commit", lambda f: f["reviews"].__setitem__(0, {**f["reviews"][0], "commit": "c" * 40})),
    ("merge_needs_the_record", "a path outside the declared paths was merged",
     lambda f: f["change"]["acceptance"]["record"].update(touched=["agentvault_registry/x.py", "agentvault_registry/security.py"])),
    ("merge_needs_the_record", "merged a different commit than the one voted", lambda f: f["change"]["merged"].update(commit="d" * 40)),
    ("deletion_on_schedule", "cooling-off ended long ago and the account is still pending",
     lambda f: f["account"].update(deletion_requested_at=NOW - D(40))),
]


@pytest.mark.parametrize("rule", sorted(GOOD))
def test_the_clean_facts_pass_every_rule(opa, rule):
    assert decide(opa, rule, deep(GOOD[rule])) is True


@pytest.mark.parametrize("rule,what,fn", CASES, ids=[f"{r}: {w}" for r, w, _ in CASES])
def test_each_broken_fact_is_flagged(opa, rule, what, fn):
    assert decide(opa, rule, mutate(rule, fn)) is False, what


def test_a_merge_inside_the_window_passes_with_the_maintainers_go_and_a_bootstrap_go_stands_for_a_ballot(opa):
    f = mutate("merge_needs_the_record", lambda f: f["change"].update(passed_at=NOW - H(2), go={"by": 9}))
    assert decide(opa, "merge_needs_the_record", f) is True
    f = mutate("merge_needs_the_record", lambda f: f["change"].update(proposal_status="FAILED", go={"by": 9, "bootstrap": {"members": 3}}))
    assert decide(opa, "merge_needs_the_record", f) is True
    f = mutate("merge_needs_the_record", lambda f: f["change"].update(proposal_status="FAILED", go={"by": 9}))
    assert decide(opa, "merge_needs_the_record", f) is False          # a go does not stand for a failed ballot unless it is the bootstrap's


def test_a_sensitive_change_needs_two_approvals_and_a_line_change_reads_its_own_ballot(opa):
    f = mutate("merge_needs_the_record", lambda f: f["change"].update(paths=["identity-fabric/x"], sensitive=True))
    f["change"]["acceptance"]["record"]["touched"] = ["identity-fabric/x"]
    assert decide(opa, "merge_needs_the_record", f) is False          # one approval, two needed
    f["reviews"].append({"reviewer_developer_id": 4, "verdict": "approve", "commit": "a" * 40, "at": 3.0})
    assert decide(opa, "merge_needs_the_record", f) is True
    line = mutate("merge_needs_the_record", lambda f: f["change"].update(
        code_distribution_id="cd1", proposal_status=None, ballot_result={"status": "PASSED"}))
    assert decide(opa, "merge_needs_the_record", line) is True
    line["change"]["ballot_result"] = {"status": "FAILED"}
    assert decide(opa, "merge_needs_the_record", line) is False


def test_a_pending_deletion_inside_its_cooling_off_and_a_finished_one_pass(opa):
    assert decide(opa, "deletion_on_schedule", mutate("deletion_on_schedule", lambda f: f["account"].update(
        deletion_requested_at=NOW - D(14) - H(1)))) is True           # due, inside the grace
    done = mutate("deletion_on_schedule", lambda f: f["account"].update(
        deletion_requested_at=NOW - D(40), deletion_status="anonymized", anonymized_at=NOW - D(20)))
    assert decide(opa, "deletion_on_schedule", done) is True


def test_a_rule_a_policy_dir_does_not_define_is_an_error_never_a_pass(opa):
    with pytest.raises(evaluator.EvaluationError):
        asyncio.run(opa.decide("agentvault/verifier/no_such_rule", {"x": 1}))


def test_the_control_one_broken_fact_of_a_clean_set_raises_the_alert_through_the_real_rego(opa, tmp_path):
    class Src:
        def __init__(self, broken):
            self.broken = broken

        def nodes(self):
            return ["eu-registry"]

        def now(self):
            return NOW

        def subjects(self, rule, node):
            f = deep(GOOD[rule])
            if self.broken and rule == "iron_pairing":
                f["env"]["AGENT_DELEGATION_MODE"] = "off"
            return [("cc1" if rule == "merge_needs_the_record" else "developer:7" if rule == "deletion_on_schedule" else node, f)]

    clean = asyncio.run(runner.run_once(Src(False), opa))
    assert sum(clean.violations.values()) == 0 and all(clean.subjects[r] == 1 for r in rules.RULES)
    broken = asyncio.run(runner.run_once(Src(True), opa, recorder=runner.Recorder(tmp_path / "f.jsonl")))
    assert broken.violations["iron_pairing"] == 1 and sum(broken.violations.values()) == 1
    assert 'opa_verifier_violations{rule="iron_pairing"} 1' in broken.metrics_text()
