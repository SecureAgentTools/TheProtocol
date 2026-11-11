"""V0660 (b): the quantum job receipts and acceptance tests in the SDK, the offline verifier a buyer runs without a
registry.

theprotocol.quantum.receipts is byte for byte the registry's services/quantum_receipts.py (both pin its SHA-256): the
check a registry runs at its verify and release steps is the check a buyer runs here. `python -m
theprotocol.quantum.verify` runs it on three files and says passed, failed or refused.

RED on d5c6ed02e: theprotocol.quantum.receipts and theprotocol.quantum.verify do not exist.
RED on a4b172984 (the second review): an agreement could not name the piece of work it settles (`work`), and
check_job took no work= to hold it to; the same agreement text on two orders gave one digest.
"""
import copy
import hashlib
import json
import pathlib

import pytest

from theprotocol.quantum import receipts as qr
from theprotocol.quantum import verify as qv

PINNED = "1153cd71bcbffdd44680b443cb1a6933ffd2c7780f8488d0c9cbe752dca3c98d"
REGISTRY_COPY = (pathlib.Path(__file__).resolve().parents[2] / "AgentVault" / "agentvault_registry" / "src"
                 / "agentvault_registry" / "services" / "quantum_receipts.py")

CLIENT, PROVIDER, VERIFIER = "did:theprotocol:client-1", "did:theprotocol:provider-1", "did:theprotocol:verifier-1"
AGREEMENT = {"template": "answer-check/v1.0", "problem": "factorisation", "params": {"n": "35"}, "verifier": VERIFIER}


@pytest.fixture(scope="module")
def keys():
    return {d: qr.new_signing_key() for d in (CLIENT, PROVIDER, VERIFIER)}


def _job(keys, factors, passed):
    result, counts = {"factors": factors}, {"circuits": {"main": {"100011": 128}}}
    chain = qr.append_step([], job="job-sdk-1", kind="circuit_submitted", participant=CLIENT, role="client",
                           body={"circuits_digest": qr.digest_of({"c": 1}), "format": "openqasm3", "shots": 128,
                                 "acceptance_digest": qr.digest_of(AGREEMENT)}, private_key=keys[CLIENT])
    chain = qr.append_step(chain, kind="backend_bound", participant=PROVIDER, role="provider",
                           body={"backend": "statevector-32", "kind": "simulator", "calibration_digest": None},
                           private_key=keys[PROVIDER])
    chain = qr.append_step(chain, kind="run_executed", participant=PROVIDER, role="provider",
                           body={"shots": 128, "counts_digest": qr.digest_of(counts)}, private_key=keys[PROVIDER])
    chain = qr.append_step(chain, kind="result_reported", participant=PROVIDER, role="provider",
                           body={"from_counts_digest": qr.digest_of(counts), "result_digest": qr.digest_of(result)},
                           private_key=keys[PROVIDER])
    evidence = {"result": result}
    chain = qr.append_step(chain, kind="verdict", participant=VERIFIER, role="verifier", body={
        "template": "answer-check/v1.0", "rung": 1, "passed": passed, "acceptance_digest": qr.digest_of(AGREEMENT),
        "evidence_digest": qr.digest_of(evidence), "false_accept_rate": None, "false_reject_rate": None},
        private_key=keys[VERIFIER])
    return chain, evidence


def test_the_package_carries_the_registrys_bytes():
    raw = pathlib.Path(qr.__file__).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PINNED


def test_the_package_copy_is_the_registrys_where_it_is_checked_out():
    if not REGISTRY_COPY.exists():
        pytest.skip("the AgentVault checkout is not beside this SDK here; the digest pin above still holds the bytes")
    assert REGISTRY_COPY.read_bytes() == pathlib.Path(qr.__file__).read_bytes()


def test_the_constants_are_the_extensions_names():
    from theprotocol.quantum import load_schema
    ev = load_schema()["examples"][0]["params"]["evidence"]
    assert ev["receipt"] == {"schema_version": qr.RECEIPT_SCHEMA_VERSION, "signing_algorithm": "Ed25519"}
    for t in ev["acceptance_tests"]:
        assert qr.TEMPLATES[t["template"]] == {"rung": t["rung"], "method": t["method"]}
    assert ev["metering_circuit"] == qr.METERING_CIRCUIT


def test_a_chain_checks_offline_and_a_changed_one_does_not(keys):
    chain, evidence = _job(keys, ["5", "7"], True)
    rep = qr.check_job(AGREEMENT, chain, evidence)
    assert rep.ok and rep.passed is True and rep.chain.key_binding == "self_asserted"
    pinned = {d: [qr.public_jwk(k)] for d, k in keys.items()}
    assert qr.check_job(AGREEMENT, chain, evidence, keys=pinned).chain.key_binding == "pinned"
    bad = copy.deepcopy(chain)
    bad[2]["body"]["shots"] = 1
    assert not qr.check_job(AGREEMENT, bad, evidence).ok
    pq = copy.deepcopy(chain)
    pq[0]["signature"]["algorithm"] = "ML-DSA-65"
    rep = qr.check_job(AGREEMENT, pq, evidence)
    assert not rep.ok and any("algorithm_unsupported" in p for p in rep.problems)


@pytest.mark.parametrize("factors,passed,code", [(["5", "7"], True, 0), (["1", "35"], False, 1)])
def test_the_command_says_passed_or_failed(tmp_path, keys, capsys, factors, passed, code):
    chain, evidence = _job(keys, factors, passed)
    files = []
    for name, doc in (("agreement", AGREEMENT), ("chain", chain), ("evidence", evidence)):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(doc))
        files.append(str(p))
    keyfile = tmp_path / "keys.json"
    keyfile.write_text(json.dumps({d: qr.public_jwk(k) for d, k in keys.items()}))
    assert qv.main(files + ["--keys", str(keyfile)]) == code
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["verdict"]["passed"] is passed and out["chain"]["key_binding"] == "pinned"


def test_the_command_refuses_a_chain_it_cannot_check(tmp_path, keys, capsys):
    chain, evidence = _job(keys, ["5", "7"], True)
    paths = []
    for name, doc in (("agreement", AGREEMENT), ("chain", chain[:-1]), ("evidence", evidence)):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(doc))
        paths.append(str(p))
    assert qv.main(paths) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["verdict"] is None and out["problems"]


def test_the_package_exports_the_receipt_names():
    import theprotocol.quantum as q
    for name in ("RECEIPT_SCHEMA_VERSION", "SIGNING_ALGORITHMS", "TEMPLATES", "check_job", "verify_chain",
                 "check_agreement", "append_step", "digest_of"):
        assert name in q.__all__ and getattr(q, name) is getattr(qr, name)


def test_the_signing_algorithm_has_the_name_the_proxy_reads():
    # V0660 (c)'s card generator imports RECEIPT_SCHEMA_VERSION and RECEIPT_SIGNING_ALGORITHM from here (room seq 2611)
    from theprotocol.quantum import receipts as qr
    assert qr.RECEIPT_SCHEMA_VERSION == "1.0"
    assert qr.RECEIPT_SIGNING_ALGORITHM == "Ed25519" and qr.RECEIPT_SIGNING_ALGORITHM in qr.SIGNING_ALGORITHMS


def test_an_agreement_names_the_work_it_settles_and_a_check_holds_it_to_that_work(keys):
    work = {"rail": "guild_work_order", "ref": "gwo_" + "a" * 24}
    assert qr.check_agreement({**AGREEMENT, "work": work}) == []
    assert any(p.startswith("work:") for p in qr.check_agreement({**AGREEMENT, "work": {"rail": "x"}}))
    chain, evidence = _job(keys, ["5", "7"], True)          # run under the bare agreement
    assert qr.check_job(AGREEMENT, chain, evidence).ok
    rep = qr.check_job(AGREEMENT, chain, evidence, work=work)
    assert not rep.ok and any("names no work" in p for p in rep.problems), rep.problems
    other = {**AGREEMENT, "work": work}
    assert qr.digest_of(other) != qr.digest_of(AGREEMENT)
    rep = qr.check_job(other, chain, evidence, work={**work, "ref": "gwo_" + "b" * 24})
    assert not rep.ok and any("names other work" in p for p in rep.problems), rep.problems
