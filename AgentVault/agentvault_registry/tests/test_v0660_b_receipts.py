"""V0660 (b): the quantum job receipt chain and the acceptance tests (services/quantum_receipts.py).

The chain links each step to the one before it by digest, from the submitted circuits to the verdict, and each step is
signed by its participant with the algorithm and the public key inside the signed bytes. An algorithm this code cannot
verify is refused, never passed. The verdict is recomputed from the evidence under the agreement made before the run:
rung 1 checks the answer (a factorisation, a satisfying assignment, an objective threshold), rung 2 applies hidden test
circuits or an independent repeat with the error rates the parties stated.

The module is byte for byte the SDK's theprotocol/quantum/receipts.py (its digest is pinned here and there), and it is
the ONE home of the receipt constants the registry card's quantum_workloads block and the agent card extension read.

RED on c533c1d11: the module does not exist; the card block named the algorithm EdDSA where the extension names Ed25519.
RED on 2217ebc44 (the second review): an agreement could not name the piece of work it settles, so the same agreement
text on two orders gave one digest; the agreement's `work` member and check_job(work=...) did not exist.
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import re

import pytest

from agentvault_registry.services import quantum_receipts as qr

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
# the bytes the SDK carries too (theprotocol-sdk/src/theprotocol/quantum/receipts.py); a change changes both pins
RECEIPTS_SHA256 = "1153cd71bcbffdd44680b443cb1a6933ffd2c7780f8488d0c9cbe752dca3c98d"

CLIENT = "did:theprotocol:client-0001"
PROVIDER = "did:theprotocol:provider-0001"
OTHER_PROVIDER = "did:theprotocol:provider-0002"
VERIFIER = "did:theprotocol:verifier-0001"


@pytest.fixture(scope="module")
def keys():
    return {d: qr.new_signing_key() for d in (CLIENT, PROVIDER, OTHER_PROVIDER, VERIFIER)}


def _ts(i: int) -> str:
    return f"2026-11-08T12:00:{i:02d}Z"


def _run(keys, agreement, *, counts, result=None, provider=PROVIDER, job="job-1", circuits_digest=None,
         backend_kind="simulator", shots=None):
    """A chain up to the run (and the reported result when one is given)."""
    shots = shots if shots is not None else sum(sum(d.values()) for d in counts["circuits"].values())
    cdig = circuits_digest or qr.digest_of({"circuits": ["OPENQASM 3; qubit[2] q;"]})
    chain = qr.append_step([], job=job, kind="circuit_submitted", participant=CLIENT, role="client", at=_ts(0),
                           body={"circuits_digest": cdig, "format": "openqasm3", "shots": shots,
                                 "acceptance_digest": qr.digest_of(agreement) if agreement else None},
                           private_key=keys[CLIENT])
    chain = qr.append_step(chain, kind="circuit_compiled", participant=provider, role="compiler", at=_ts(1),
                           body={"source_digest": cdig, "compiled_digest": qr.digest_of({"native": "cz,rx"}),
                                 "format": "openqasm3"}, private_key=keys[provider])
    chain = qr.append_step(chain, kind="backend_bound", participant=provider, role="provider", at=_ts(2),
                           body={"backend": "statevector-sim", "kind": backend_kind, "calibration_digest": None},
                           private_key=keys[provider])
    chain = qr.append_step(chain, kind="run_executed", participant=provider, role="provider", at=_ts(3),
                           body={"shots": shots, "counts_digest": qr.digest_of(counts)}, private_key=keys[provider])
    if result is not None:
        chain = qr.append_step(chain, kind="result_reported", participant=provider, role="provider", at=_ts(4),
                               body={"from_counts_digest": qr.digest_of(counts), "result_digest": qr.digest_of(result)},
                               private_key=keys[provider])
    return chain


def _verdict(keys, chain, agreement, evidence, passed, *, verifier=VERIFIER, template=None):
    return qr.append_step(chain, kind="verdict", participant=verifier, role="verifier", at=_ts(9), body={
        "template": template or agreement["template"], "rung": qr.TEMPLATES[agreement["template"]]["rung"],
        "passed": passed, "acceptance_digest": qr.digest_of(agreement), "evidence_digest": qr.digest_of(evidence),
        "false_accept_rate": agreement.get("false_accept_rate"),
        "false_reject_rate": agreement.get("false_reject_rate")}, private_key=keys[verifier])


COUNTS = {"circuits": {"main": {"0011": 900, "1100": 100}}}
FACTOR = {"template": "answer-check/v1.0", "problem": "factorisation", "params": {"n": "15"}, "verifier": VERIFIER}


def _factor_job(keys, factors, passed):
    result = {"factors": factors}
    chain = _run(keys, FACTOR, counts=COUNTS, result=result)
    evidence = {"result": result}
    return _verdict(keys, chain, FACTOR, evidence, passed), evidence


def _all_keys(keys):
    return {d: [qr.public_jwk(k)] for d, k in keys.items()}


# ── the module is the SDK's, byte for byte, and the one home of the constants ────────────────────────────────────────

def test_the_module_carries_the_pinned_bytes():
    raw = (_SRC / "services" / "quantum_receipts.py").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == RECEIPTS_SHA256
    # self-contained: only the standard library (and cryptography, imported where a signature is made or checked)
    text = raw.decode()
    assert "agentvault_registry" not in text.split('"""', 2)[2]
    assert not re.search(r"^from \.|^import \.", text, re.M)


def test_the_card_block_reads_its_constants_from_this_module():
    from agentvault_registry.services import quantum_workloads as qw
    assert qw.RECEIPT_SCHEMA_VERSION is qr.RECEIPT_SCHEMA_VERSION == "1.0"
    assert qw.RECEIPT_SIGNATURE_ALGORITHMS is qr.SIGNING_ALGORITHMS == ("Ed25519",)
    assert qw.ACCEPTANCE_RUNGS is qr.ACCEPTANCE_RUNGS == (1, 2)
    assert qw.METERING_CIRCUIT is qr.METERING_CIRCUIT


def test_the_names_are_the_extension_schemas_names():
    from agentvault_registry.services import quantum_agent_card as qac
    ev = qac.schema()["$defs"]["evidence"]["properties"]
    alg = re.compile(qac.schema()["$defs"]["signing_algorithm"]["pattern"])
    template = re.compile(ev["acceptance_tests"]["items"]["properties"]["template"]["pattern"])
    methods = ev["acceptance_tests"]["items"]["properties"]["method"]["enum"]
    version = re.compile(ev["receipt"]["properties"]["schema_version"]["pattern"])
    assert version.match(qr.RECEIPT_SCHEMA_VERSION)
    assert all(alg.match(a) for a in qr.SIGNING_ALGORITHMS)
    for name, t in qr.TEMPLATES.items():
        assert template.match(name) and t["method"] in methods and t["rung"] in qr.ACCEPTANCE_RUNGS
    assert re.match(qac.schema()["$defs"]["evidence"]["properties"]["metering_circuit"]["pattern"], qr.METERING_CIRCUIT)
    # the spec's own example offers two of these templates, with the rung and method the catalog gives them
    example = qac.schema()["examples"][0]["params"]["evidence"]
    for t in example["acceptance_tests"]:
        assert qr.TEMPLATES[t["template"]] == {"rung": t["rung"], "method": t["method"]}
    assert example["receipt"] == {"schema_version": qr.RECEIPT_SCHEMA_VERSION, "signing_algorithm": "Ed25519"}


# ── canonical JSON ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_canonical_json_is_sorted_compact_and_refuses_floats():
    assert qr.canonical({"b": 1, "a": [True, None, "x"]}) == b'{"a":[true,null,"x"],"b":1}'
    with pytest.raises(qr.ReceiptError, match="decimal string"):
        qr.canonical({"rate": 0.05})
    with pytest.raises(qr.ReceiptError, match="2\\^53"):
        qr.canonical({"n": 2 ** 60})
    with pytest.raises(qr.ReceiptError, match="ASCII"):
        qr.canonical({"é": 1})
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", qr.digest_of({}))


# ── the chain ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_whole_chain_verifies_and_names_its_head(keys):
    chain, _ev = _factor_job(keys, ["3", "5"], True)
    rep = qr.verify_chain(chain)
    assert rep.ok, rep.problems
    assert rep.steps == 6 and rep.job == "job-1" and rep.key_binding == "self_asserted"
    assert rep.head == qr.step_digest(chain[-1])
    assert [s["kind"] for s in chain] == list(qr.STEP_KINDS)
    pinned = qr.verify_chain(chain, keys=_all_keys(keys))
    assert pinned.ok and pinned.key_binding == "pinned"


def test_the_algorithm_and_the_key_are_inside_the_signed_bytes(keys):
    chain, _ev = _factor_job(keys, ["3", "5"], True)
    signed = qr.signed_bytes(chain[0])
    assert signed.startswith(qr.SIGNING_PREFIX)
    body = json.loads(signed[len(qr.SIGNING_PREFIX):])
    assert body["signature"] == {"algorithm": "Ed25519", "public_key": qr.public_jwk(keys[CLIENT])}
    assert "value" not in body["signature"]


@pytest.mark.parametrize("change,expect", [
    (lambda c: c[3]["body"].__setitem__("shots", 999), "signature does not verify"),
    (lambda c: c[2].__setitem__("prev", qr.digest_of({"x": 1})), "chain is broken"),
    (lambda c: c.__setitem__(slice(1, 3), [c[2], c[1]]), "in that order"),
    (lambda c: c.pop(), "ends with the verifier's verdict"),
    (lambda c: c[1].__setitem__("job", "job-2"), "names job"),
    (lambda c: c[4].__setitem__("role", "verifier"), "signed as provider or mitigator"),
])
def test_a_changed_chain_is_refused(keys, change, expect):
    chain, _ev = _factor_job(keys, ["3", "5"], True)
    bad = copy.deepcopy(chain)
    change(bad)
    rep = qr.verify_chain(bad)
    assert not rep.ok and any(expect in p for p in rep.problems), rep.problems


@pytest.mark.parametrize("algorithm", ["ML-DSA-65", "SLH-DSA-SHA2-128s", "Ed25519+ML-DSA-65", "ES256"])
def test_an_algorithm_this_verifier_cannot_check_is_refused_never_passed(keys, algorithm):
    chain, _ev = _factor_job(keys, ["3", "5"], True)
    bad = copy.deepcopy(chain)
    bad[-1]["signature"]["algorithm"] = algorithm
    rep = qr.verify_chain(bad)
    assert not rep.ok
    assert any(p.startswith("step 5 (verdict): algorithm_unsupported") and algorithm in p for p in rep.problems)
    with pytest.raises(qr.ReceiptError, match="signs with Ed25519"):
        qr.sign_step({"x": 1}, keys[CLIENT], algorithm)


def test_a_step_signed_with_a_key_its_participant_does_not_hold_is_refused(keys):
    stranger = qr.new_signing_key()
    chain = qr.append_step([], job="job-9", kind="circuit_submitted", participant=CLIENT, role="client", at=_ts(0),
                           body={"circuits_digest": qr.digest_of({"c": 1}), "format": "openqasm3", "shots": 10,
                                 "acceptance_digest": None}, private_key=stranger)
    assert qr.verify_chain(chain, require_verdict=False).ok             # whole, but self-asserted
    rep = qr.verify_chain(chain, keys=_all_keys(keys), require_verdict=False)
    assert any(p.startswith("participant_key_unknown") for p in rep.problems)


def test_the_steps_must_agree_with_each_other(keys):
    agreement = FACTOR
    chain = _run(keys, agreement, counts=COUNTS, result={"factors": ["3", "5"]})
    bad = qr.append_step(chain[:3], kind="run_executed", participant=PROVIDER, role="provider", at=_ts(3),
                         body={"shots": 7, "counts_digest": qr.digest_of(COUNTS)}, private_key=keys[PROVIDER])
    assert any("ran 7 shots" in p for p in qr.verify_chain(bad, require_verdict=False).problems)
    qpu = qr.append_step(chain[:2], kind="backend_bound", participant=PROVIDER, role="provider", at=_ts(2),
                         body={"backend": "ibm-x", "kind": "qpu", "calibration_digest": None},
                         private_key=keys[PROVIDER])
    assert any("calibration snapshot" in p for p in qr.verify_chain(qpu, require_verdict=False).problems)


# ── the agreement ────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("doc,expect", [
    ({"template": "answer-check/v2.0"}, "template: one of"),
    ({**FACTOR, "false_accept_rate": "0.01"}, "rung 1 check of the answer has no error rates"),
    ({"template": "test-circuits/v1.0", "params": {"tests_commitment": qr.digest_of({}), "test_count": 4,
                                                    "min_passed": 4, "min_success_fraction": "0.9"}},
     "false_accept_rate: a rung 2 test states it before the run"),
    ({"template": "test-circuits/v1.0", "false_accept_rate": 0.01, "false_reject_rate": "0.05",
      "params": {"tests_commitment": qr.digest_of({}), "test_count": 4, "min_passed": 5,
                 "min_success_fraction": "0.9"}}, "decimal string"),
    ({"template": "answer-check/v1.0", "problem": "factorisation", "params": {"n": "3"}}, "at least 4"),
    ({"template": "answer-check/v1.0", "problem": "assignment", "params": {"variables": 2, "clauses": [[1, 3]]}},
     "names a variable"),
    ({**FACTOR, "verifier": "nobody"}, "verifier: the DID"),
])
def test_an_agreement_that_cannot_settle_a_verdict_says_why(doc, expect):
    problems = qr.check_agreement(doc)
    assert any(expect in p for p in problems), problems


def test_a_valid_agreement_has_no_problems():
    assert qr.check_agreement(FACTOR) == []


# ── rung 1: check the answer ─────────────────────────────────────────────────────────────────────────────────────────

def test_rung_1_factorisation_passes_and_fails_on_the_answer(keys):
    chain, ev = _factor_job(keys, ["3", "5"], True)
    rep = qr.check_job(FACTOR, chain, ev)
    assert rep.ok and rep.passed is True, rep.problems
    v = rep.verdict()
    assert v["template"] == "answer-check/v1.0" and v["rung"] == 1 and v["head"] == qr.step_digest(chain[-1])
    assert set(v) >= {"acceptance_digest", "evidence_digest", "job", "steps"}
    # the ledger keeps hashes and verdicts: nothing of the circuits, the counts or the result
    assert '"15"' not in json.dumps(v) and '"factors"' not in json.dumps(v)
    wrong, ev2 = _factor_job(keys, ["1", "15"], False)
    rep2 = qr.check_job(FACTOR, wrong, ev2)
    assert rep2.ok and rep2.passed is False and "not a factorisation" in rep2.reason


def test_a_verifier_who_signs_the_wrong_verdict_is_refused(keys):
    lie, ev = _factor_job(keys, ["1", "15"], True)
    rep = qr.check_job(FACTOR, lie, ev)
    assert not rep.ok and any("the evidence gives passed=false" in p for p in rep.problems)


def test_an_answer_that_is_not_the_chains_result_is_refused(keys):
    chain, _ev = _factor_job(keys, ["3", "5"], True)
    rep = qr.check_job(FACTOR, chain, {"result": {"factors": ["5", "3"]}})
    assert not rep.ok and any("signed over other evidence" in p for p in rep.problems)


def test_a_run_not_bound_to_the_agreement_before_it_ran_is_refused(keys):
    result = {"factors": ["3", "5"]}
    chain = _run(keys, None, counts=COUNTS, result=result)
    chain = _verdict(keys, chain, FACTOR, {"result": result}, True)
    rep = qr.check_job(FACTOR, chain, {"result": result})
    assert not rep.ok and any("agreed before the run" in p or "other than the one" in p for p in rep.problems)


def test_the_named_verifier_signs_the_verdict(keys):
    result = {"factors": ["3", "5"]}
    chain = _run(keys, FACTOR, counts=COUNTS, result=result)
    chain = _verdict(keys, chain, FACTOR, {"result": result}, True, verifier=OTHER_PROVIDER)
    rep = qr.check_job(FACTOR, chain, {"result": result})
    assert not rep.ok and any("names did:theprotocol:verifier-0001 as its verifier" in p for p in rep.problems)


def test_rung_1_assignment_and_objective_threshold(keys):
    sat = {"template": "answer-check/v1.0", "problem": "assignment",
           "params": {"variables": 3, "clauses": [[1, -2], [2, 3], [-1, -3]]}}
    for assignment, passed in (([True, True, False], True), ([True, False, True], False)):
        result = {"assignment": assignment}
        chain = _verdict(keys, _run(keys, sat, counts=COUNTS, result=result), sat, {"result": result}, passed)
        rep = qr.check_job(sat, chain, {"result": result})
        assert rep.ok and rep.passed is passed, (rep.problems, rep.reason)
    qubo = {"template": "answer-check/v1.0", "problem": "objective_threshold",
            "params": {"matrix": [["-1", "2"], [0, "-1.5"]], "sense": "minimize", "threshold": "-1.5"}}
    for bits, passed in (("01", True), ("11", False)):
        result = {"bitstring": bits}
        chain = _verdict(keys, _run(keys, qubo, counts=COUNTS, result=result), qubo, {"result": result}, passed)
        rep = qr.check_job(qubo, chain, {"result": result})
        assert rep.ok and rep.passed is passed, (rep.problems, rep.reason)
    assert "the objective is -1.5" in qr.check_job(qubo, *_answer(keys, qubo, "01")).reason


def _answer(keys, agreement, bits):
    result = {"bitstring": bits}
    chain = _verdict(keys, _run(keys, agreement, counts=COUNTS, result=result), agreement, {"result": result}, True)
    return chain, {"result": result}


# ── rung 2: hidden test circuits and an independent repeat ───────────────────────────────────────────────────────────

TESTS = {"salt": "a1b2c3d4e5f6a7b8c9d0", "circuits": [{"id": "t1", "expected": "00"}, {"id": "t2", "expected": "11"}]}
HIDDEN = {"template": "test-circuits/v1.0", "false_accept_rate": "0.01", "false_reject_rate": "0.05",
          "params": {"tests_commitment": qr.digest_of(TESTS), "test_count": 2, "min_passed": 2,
                     "min_success_fraction": "0.9"}}


@pytest.mark.parametrize("t2,passed", [({"11": 95, "01": 5}, True), ({"11": 80, "01": 20}, False)])
def test_rung_2_hidden_test_circuits_apply_the_agreed_rule(keys, t2, passed):
    counts = {"circuits": {"main": {"0101": 100}, "t1": {"00": 99, "10": 1}, "t2": t2}}
    chain = _run(keys, HIDDEN, counts=counts)
    evidence = {"tests": TESTS, "counts": counts}
    rep = qr.check_job(HIDDEN, _verdict(keys, chain, HIDDEN, evidence, passed), evidence)
    assert rep.ok and rep.passed is passed, rep.problems
    assert rep.verdict()["false_accept_rate"] == "0.01" and rep.verdict()["false_reject_rate"] == "0.05"
    assert f"{2 if passed else 1} of 2 hidden test circuits" in rep.reason


def test_rung_2_tests_other_than_the_committed_ones_are_refused(keys):
    counts = {"circuits": {"t1": {"00": 100}, "t2": {"11": 100}}}
    swapped = {"salt": TESTS["salt"], "circuits": [{"id": "t1", "expected": "00"}, {"id": "t2", "expected": "00"}]}
    evidence = {"tests": swapped, "counts": counts}
    chain = _verdict(keys, _run(keys, HIDDEN, counts=counts), HIDDEN, evidence, True)
    rep = qr.check_job(HIDDEN, chain, evidence)
    assert not rep.ok and any("committed to" in p for p in rep.problems)


REPEAT = {"template": "independent-repeat/v1.0", "false_accept_rate": "0.02", "false_reject_rate": "0.02",
          "params": {"circuit": "main", "max_distance": "0.1", "min_shots": 100}}


@pytest.mark.parametrize("theirs,passed", [({"0011": 880, "1100": 120}, True), ({"0011": 500, "1100": 500}, False)])
def test_rung_2_an_independent_repeat_compares_the_two_runs(keys, theirs, passed):
    mine = COUNTS
    repeat_counts = {"circuits": {"main": theirs}}
    chain = _run(keys, REPEAT, counts=mine)
    repeat = _run(keys, None, counts=repeat_counts, provider=OTHER_PROVIDER, job="job-1-repeat")
    evidence = {"counts": mine, "repeat_chain": repeat, "repeat_counts": repeat_counts}
    rep = qr.check_job(REPEAT, _verdict(keys, chain, REPEAT, evidence, passed), evidence)
    assert rep.ok and rep.passed is passed, rep.problems
    assert "total variation distance" in rep.reason


def test_rung_2_a_repeat_at_the_same_provider_is_not_independent(keys):
    repeat_counts = {"circuits": {"main": {"0011": 900, "1100": 100}}}
    chain = _run(keys, REPEAT, counts=COUNTS)
    repeat = _run(keys, None, counts=repeat_counts, job="job-1-repeat")
    evidence = {"counts": COUNTS, "repeat_chain": repeat, "repeat_counts": repeat_counts}
    rep = qr.check_job(REPEAT, _verdict(keys, chain, REPEAT, evidence, True), evidence)
    assert not rep.ok and any("same provider" in p for p in rep.problems)


def test_the_agreement_pins_keys_and_a_pinned_check_refuses_others(keys):
    pinned = {**FACTOR, "participants": {CLIENT: qr.public_jwk(keys[CLIENT])}}
    result = {"factors": ["3", "5"]}
    chain = _verdict(keys, _run(keys, pinned, counts=COUNTS, result=result), pinned, {"result": result}, True)
    rep = qr.check_job(pinned, chain, {"result": result})
    assert not rep.ok and any("participant_key_unknown" in p for p in rep.problems)   # the provider is not pinned
    rep2 = qr.check_job(pinned, chain, {"result": result}, keys=_all_keys(keys))
    assert rep2.ok and rep2.passed and rep2.chain.key_binding == "pinned"


def test_the_signing_algorithm_has_the_name_the_proxy_reads():
    # V0660 (c)'s card generator (theprotocol/proxy/quantum/card.py) imports RECEIPT_SCHEMA_VERSION and
    # RECEIPT_SIGNING_ALGORITHM from this module and refuses by name without them (session-watch, room seq 2611)
    from agentvault_registry.services import quantum_receipts as qr
    assert qr.RECEIPT_SCHEMA_VERSION == "1.0"
    assert qr.RECEIPT_SIGNING_ALGORITHM == "Ed25519" and qr.RECEIPT_SIGNING_ALGORITHM in qr.SIGNING_ALGORITHMS


# ── the agreement names the piece of work it settles (the second review) ─────────────────────────────────────────────

WORK = {"rail": "guild_work_order", "ref": "gwo_" + "a" * 24}


@pytest.mark.parametrize("work", [WORK, {"rail": "contract_milestone", "ref": "ctr_" + "b" * 24, "seq": 3}])
def test_an_agreement_may_name_the_work_it_settles(work):
    assert qr.check_agreement({**FACTOR, "work": work}) == []


@pytest.mark.parametrize("work", [
    {"rail": "guild_work_order"},
    {"rail": "guild_work_order", "ref": "gwo_1", "seq": 0},
    {"rail": "guild_work_order", "ref": "gwo_1", "seq": True},
    {"rail": "guild_work_order", "ref": "gwo_1", "milestone": 1},
    {"rail": "guild_work_order", "ref": "has space"},
    "gwo_1",
])
def test_a_work_member_names_a_rail_a_ref_and_optionally_a_milestone(work):
    problems = qr.check_agreement({**FACTOR, "work": work})
    assert any(p.startswith("work:") for p in problems), problems


def test_a_job_checked_for_one_piece_of_work_refuses_an_agreement_for_another(keys):
    bound = {**FACTOR, "work": WORK}
    result = {"factors": ["3", "5"]}
    ev = {"result": result}
    chain = _verdict(keys, _run(keys, bound, counts=COUNTS, result=result), bound, ev, True)
    assert qr.check_job(bound, chain, ev, work=WORK).ok
    assert qr.check_job(bound, chain, ev).ok, "without work= the check is as before"
    rep = qr.check_job(bound, chain, ev, work={**WORK, "ref": "gwo_" + "c" * 24})
    assert not rep.ok and any("names other work" in p for p in rep.problems), rep.problems
    # the same text agreed for another order is another agreement: the chain names this one's digest only
    other = {**FACTOR, "work": {**WORK, "ref": "gwo_" + "c" * 24}}
    assert qr.digest_of(other) != qr.digest_of(bound)
    rep = qr.check_job(other, chain, ev, work=other["work"])
    assert not rep.ok and any("not submitted under this agreement" in p for p in rep.problems), rep.problems
    bare, bare_ev = _factor_job(keys, ["3", "5"], True)
    rep = qr.check_job(FACTOR, bare, bare_ev, work=WORK)
    assert not rep.ok and any("names no work" in p for p in rep.problems), rep.problems
