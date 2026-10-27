"""ZK attestations v2 (2026-10-13): a proof binds its public inputs, and its policy limits bind to this registry's policy.

v1.0.0 circuits took their policy limits (the markup cap, the usage tolerance, the fee cap) as private inputs that
nothing bound, so a prover could pick whatever fitted; and the verifier never compared the public inputs a caller
stated with the ones the proof was made for. These tests pin both fixes with real UltraHonk proofs
(tests/fixtures/zkp_v2_proofs.json, made with nargo 1.0.0-beta.3 and bb 0.82.2, the image's pair). The legs that run
bb or nargo skip where those are not installed; every binding leg runs everywhere.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from agentvault_registry.core import zkp_verifier as Z

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "zkp_v2_proofs.json").read_text())
V2 = sorted(FIXTURES)


def _registry_root() -> Path:
    here = Path(__file__).resolve()
    candidates = [Path(os.environ["CIRCUIT_REGISTRY_PATH"])] if os.environ.get("CIRCUIT_REGISTRY_PATH") else []
    candidates += [
        here.parents[1] / "agentvault_circuit_registry",      # tests copied beside the image's /app
        here.parents[2] / "agentvault_circuit_registry",      # the repository
        Path("/app/agentvault_circuit_registry"),             # the image, when the tests are mounted elsewhere (/w)
        Z._CIRCUIT_REGISTRY_ROOT,
    ]
    for candidate in candidates:
        if (candidate / "policies").is_dir() and (candidate / "crs").is_dir():
            return candidate
    pytest.skip("agentvault_circuit_registry (with its crs/) not found: set CIRCUIT_REGISTRY_PATH")


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    root = _registry_root()
    monkeypatch.setattr(Z, "_CIRCUIT_REGISTRY_ROOT", root)
    monkeypatch.setattr(Z, "_v2_cache", {})
    monkeypatch.setattr(Z, "_bb_home_ready", None)
    monkeypatch.delenv("ZKP_POLICY_JSON", raising=False)
    monkeypatch.delenv("ZKP_ACCEPT_V1_CIRCUITS", raising=False)
    return root


needs_bb = pytest.mark.skipif(not Path(Z._BB_BINARY).exists(), reason="bb is not installed here (the image has it)")
needs_nargo = pytest.mark.skipif(shutil.which("nargo") is None, reason="nargo is not installed here (the image has it)")


def _verify(cid, proof, stated, expected=None):
    return asyncio.run(Z.verify_proof_detailed(cid, proof, stated, expected))


def _case(cid):
    fixture = FIXTURES[cid]
    outputs = set(Z._load_v2(cid)["outputs"])
    stated = {k: v for k, v in fixture["public"].items() if k not in outputs}
    return {"proof_bytes": fixture["proof_bytes"]}, stated, dict(fixture["public"])


# ── what a proof carries, and what the caller states ─────────────────────────

@needs_bb
@pytest.mark.parametrize("cid", V2)
def test_a_real_proof_verifies_under_its_own_inputs(cid, monkeypatch):
    # The fee fixture was proven under a 1% cap; the shipped policy allows 0.5% (pinned in its own test below).
    monkeypatch.setenv("ZKP_POLICY_JSON", json.dumps({"fairCrossRegistryFee": {"max_fee_bps": 100}}))
    proof, stated, carried = _case(cid)
    result = _verify(cid, proof, stated)
    assert result.verified and result.status == "verified", result.reason
    assert result.public_values == {k: Z._as_field(v) for k, v in carried.items()}


@pytest.mark.parametrize("cid", V2)
def test_a_stated_input_that_differs_from_the_proof_is_refused(cid):
    proof, stated, _ = _case(cid)
    name = next(n for n in stated if n not in Z._load_v2(cid)["policy"])
    stated[name] = str(Z._as_field(stated[name]) + 1)
    result = _verify(cid, proof, stated)
    assert not result.verified
    assert result.reason == f"public input '{name}' differs from the value the proof was made for"


@pytest.mark.parametrize("cid", V2)
def test_every_public_input_must_be_stated(cid):
    proof, stated, _ = _case(cid)
    missing = sorted(stated)[0]
    del stated[missing]
    result = _verify(cid, proof, stated)
    assert not result.verified and result.reason == f"missing public input '{missing}'"


def test_a_stated_output_must_match_too():
    cid = "fairMarkupPolicy/v2.0.0"
    proof, stated, carried = _case(cid)
    stated["cost_commitment"] = "1"
    result = _verify(cid, proof, stated)
    assert not result.verified and "cost_commitment" in result.reason


def test_a_value_outside_its_type_or_the_field_is_refused():
    cid = "fairMarkupPolicy/v2.0.0"
    proof, stated, _ = _case(cid)
    too_wide = dict(stated, max_markup_bps=str(2 ** 32))
    assert _verify(cid, proof, too_wide).reason == "public input 'max_markup_bps' is not a valid value"
    beyond_field = dict(stated, context=str(Z._BN254_R + int(stated["context"])))   # never reduced into an alias
    assert _verify(cid, proof, beyond_field).reason == "public input 'context' is not a valid value"


def test_hex_and_decimal_claims_name_the_same_value():
    assert Z._as_field("0x1234") == Z._as_field("4660") == Z._as_field(4660) == 4660
    assert Z._as_field("-1") is None and Z._as_field(1.5) is None and Z._as_field("twelve") is None


def test_bytes_without_the_proof_layout_are_refused():
    cid = "accurateResourceUsagePolicy/v2.0.0"
    proof, stated, _ = _case(cid)
    raw = base64.b64decode(proof["proof_bytes"])
    for broken in (raw[:-1], raw[:100], b"\x00\x00\x00\x02" + b"\x00" * 64):
        result = _verify(cid, {"proof_bytes": base64.b64encode(broken).decode()}, stated)
        assert not result.verified and result.reason.startswith("proof bytes do not have the bb proof layout")
    assert _verify(cid, {"proof_bytes": "not base64!"}, stated).reason.startswith("proof_data.proof_bytes")


@pytest.mark.parametrize("index", [10, 300, 443])
def test_an_element_offset_by_the_field_order_is_refused(index):
    """bb reduces every element modulo r, so x + r would verify too: one proof, many byte strings."""
    cid = "fairMarkupPolicy/v2.0.0"
    proof, stated, _ = _case(cid)
    raw = bytearray(base64.b64decode(proof["proof_bytes"]))
    at = 4 + 32 * index
    raw[at:at + 32] = (int.from_bytes(raw[at:at + 32], "big") + Z._BN254_R).to_bytes(32, "big")
    result = _verify(cid, {"proof_bytes": base64.b64encode(bytes(raw)).decode()}, stated)
    assert not result.verified and "non-canonical" in result.reason


def test_the_reference_names_an_agent_and_a_label():
    a = Z.derive_reference("did:theprotocol:a", "quote-42")
    assert a == Z.derive_reference("did:theprotocol:a", "quote-42") and 0 < a < 2 ** 248 < Z._BN254_R
    assert a != Z.derive_reference("did:theprotocol:b", "quote-42") != Z.derive_reference("did:theprotocol:a", "quote-43")
    assert set(Z.REFERENCE_INPUTS) == set(Z._V2_CIRCUITS)
    for cid, name in Z.REFERENCE_INPUTS.items():
        assert name in Z._load_v2(cid)["public"]


@needs_bb
def test_a_tampered_proof_body_is_rejected_by_bb():
    cid = "fairMarkupPolicy/v2.0.0"
    proof, stated, _ = _case(cid)
    raw = bytearray(base64.b64decode(proof["proof_bytes"]))
    raw[4 + 32 * 10 + 7] ^= 0x01            # inside the proof proper, after the public values
    result = _verify(cid, {"proof_bytes": base64.b64encode(bytes(raw)).decode()}, stated)
    assert not result.verified and result.status in ("rejected", "error")


# ── policy limits ─────────────────────────────────────────────────────────

def test_a_cap_looser_than_this_registrys_policy_is_refused(monkeypatch):
    monkeypatch.setenv("ZKP_POLICY_JSON", json.dumps({"fairMarkupPolicy": {"max_markup_bps": 2500}}))
    cid = "fairMarkupPolicy/v2.0.0"
    proof, stated, _ = _case(cid)       # proven under a 30% cap
    result = _verify(cid, proof, stated)
    assert not result.verified
    assert result.reason == "max_markup_bps=3000 is looser than this registry's policy (2500)"


def test_a_minimum_lower_than_this_registrys_policy_is_refused(monkeypatch):
    monkeypatch.setenv("ZKP_POLICY_JSON", json.dumps({"contentSafetyAttestation/v2.0.0": {"min_rejection_bps": 9500}}))
    cid = "contentSafetyAttestation/v2.0.0"
    proof, stated, _ = _case(cid)       # proven at a 90% minimum
    result = _verify(cid, proof, stated)
    assert not result.verified
    assert result.reason == "min_rejection_bps=9000 is looser than this registry's policy (9500)"


def test_the_shipped_defaults_refuse_a_looser_fee_cap():
    cid = "fairCrossRegistryFee/v2.0.0"
    proof, stated, _ = _case(cid)       # proven under a 1% cap; the default policy is 0.5%
    result = _verify(cid, proof, stated)
    assert not result.verified and result.reason == "max_fee_bps=100 is looser than this registry's policy (50)"


@needs_bb
def test_a_stricter_limit_in_the_proof_passes(monkeypatch):
    monkeypatch.setenv("ZKP_POLICY_JSON", json.dumps({"fairMarkupPolicy": {"max_markup_bps": 3500}}))
    cid = "fairMarkupPolicy/v2.0.0"
    proof, stated, _ = _case(cid)       # proven under 30%, stricter than the 35% allowed
    assert _verify(cid, proof, stated).verified


def test_an_unreadable_policy_fails_closed(monkeypatch):
    monkeypatch.setenv("ZKP_POLICY_JSON", "{not json")
    cid = "fairMarkupPolicy/v2.0.0"
    proof, stated, _ = _case(cid)
    result = _verify(cid, proof, stated)
    assert not result.verified and result.status == "error" and "policy unreadable" in result.reason


# ── expected values ───────────────────────────────────────────────────────

def test_an_expected_reference_must_match():
    cid = "accurateResourceUsagePolicy/v2.0.0"
    proof, stated, _ = _case(cid)
    result = _verify(cid, proof, stated, expected={"transaction_ref": "999"})
    assert not result.verified and result.reason == "'transaction_ref' differs from the expected value"


@needs_bb
def test_a_published_commitment_matches():
    cid = "accurateResourceUsagePolicy/v2.0.0"
    proof, stated, carried = _case(cid)
    assert _verify(cid, proof, stated, expected={"log_commitment": carried["log_commitment"]}).verified


# ── retired and non-proof circuits ────────────────────────────────────────

@pytest.mark.parametrize("cid", ["fairMarkupPolicy/v1.0.0", "FAIR_MARKUP_POLICY_V1", "PARU_V1"])
def test_v1_is_retired_unless_accepted(cid):
    junk = {"proof_bytes": base64.b64encode(b"\x00" * 64).decode()}
    result = _verify(cid, junk, {})
    assert not result.verified and "is retired" in result.reason and "v2.0.0" in result.reason


def test_option_b_is_never_a_verified_proof():
    stated = {"reputation_threshold": 10, "agent_did": "did:theprotocol:x"}
    result = _verify("ProofOfGoodReputation", {}, stated)
    assert result.status == "not_a_proof" and not result.verified
    assert asyncio.run(Z.verify_proof("proof_of_reputation/v1.0", {}, stated)) is False


def test_unknown_circuits_are_refused():
    assert _verify("madeUp/v9", {"proof_bytes": "AAAA"}, {}).reason == "unknown circuit_id 'madeUp/v9'"


def test_supported_circuits_list_v2_and_hide_retired_v1(monkeypatch):
    assert set(Z._V2_CIRCUITS) <= set(Z.get_supported_circuits())
    assert "fairMarkupPolicy/v1.0.0" not in Z.get_supported_circuits()
    monkeypatch.setenv("ZKP_ACCEPT_V1_CIRCUITS", "true")
    assert "fairMarkupPolicy/v1.0.0" in Z.get_supported_circuits()


# ── what ships ───────────────────────────────────────────────────────────

def test_the_pinned_reference_string_is_what_ships(registry):
    for name, digest in Z._CRS_FILES.items():
        assert hashlib.sha256((registry / "crs" / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("cid", list(Z._V2_CIRCUITS))
def test_every_v2_circuit_ships_its_key_artifact_and_metadata(cid, registry):
    spec = Z._load_v2(cid)
    meta = json.loads((spec["vk"].parent / "metadata.json").read_text())
    assert hashlib.sha256(spec["vk"].read_bytes()).hexdigest() == meta["Artifacts"]["verification_key_sha256"]
    assert spec["public"] == list(meta["PublicInputs"])            # the ABI order is the metadata order
    assert len(spec["outputs"]) == 1 and set(spec["policy"]) <= set(spec["public"])
    for pname, rule in spec["policy"].items():
        assert rule["rule"] in ("at_most", "at_least") and isinstance(rule["default"], int)
    assert cid in FIXTURES


@needs_nargo
@pytest.mark.parametrize("cid", list(Z._V2_CIRCUITS))
def test_the_circuit_tests_pass_and_the_artifact_matches_the_source(cid, registry, tmp_path):
    name, version = cid.split("/")
    src = registry / "policies" / name / version
    shutil.copy(src / "Nargo.toml", tmp_path / "Nargo.toml")
    shutil.copytree(src / "src", tmp_path / "src")
    env = dict(os.environ, HOME=str(tmp_path))
    tests = subprocess.run(["nargo", "test"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    assert tests.returncode == 0, tests.stdout[-2000:] + tests.stderr[-2000:]
    built = subprocess.run(["nargo", "compile"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stderr[-2000:]
    compiled = json.loads(next((tmp_path / "target").glob("*.json")).read_text())
    shipped = json.loads((src / "circuit.json").read_text())
    assert compiled["bytecode"] == shipped["bytecode"], "circuit.json is stale: recompile and regenerate the key"
    assert compiled["abi"] == shipped["abi"]


# ── the circuits API ──────────────────────────────────────────────────────

@pytest.fixture()
def circuits_api(monkeypatch, registry):
    from agentvault_registry.routers import attestations as A
    monkeypatch.setattr(A, "_CIRCUIT_REGISTRY_BASE", registry / "policies")
    monkeypatch.setattr(A, "_CIRCUIT_FILE_MAP", {
        f"{name}/{version}": A._circuit_entry(name, version)
        for name in A._CIRCUIT_PACKAGES for version in ("v2.0.0", "v1.0.0")
    })
    return A


def test_the_list_marks_v2_active_and_v1_retired(circuits_api):
    rows = {r["circuit_id"]: r for r in asyncio.run(circuits_api.list_circuits())["circuits"]}
    for cid in Z._V2_CIRCUITS:
        row = rows[cid]
        assert row["status"] == "active" and row["acir_available"] is True
        assert row["vk_url"] == f"/api/v1/circuits/{cid}/vk" and row["policy"]
    v1 = rows["fairCrossRegistryFee/v1.0.0"]
    assert v1["status"] == "retired" and v1["superseded_by"] == "fairCrossRegistryFee/v2.0.0"
    assert v1["acir_available"] is False and "vk_url" not in v1


def test_acir_vk_and_metadata_are_served_for_v2(circuits_api, registry):
    cid = "fairMarkupPolicy/v2.0.0"
    acir = asyncio.run(circuits_api.get_circuit_acir(cid))
    shipped = json.loads((registry / "policies/fairMarkupPolicy/v2.0.0/circuit.json").read_text())
    assert acir.body == base64.b64decode(shipped["bytecode"]) and acir.body[:2] == b"\x1f\x8b"
    assert asyncio.run(circuits_api.get_circuit_vk(cid)).path.endswith("verification_key.bin")
    meta = asyncio.run(circuits_api.get_circuit_metadata(cid))
    assert meta["policy_in_force"] == {"max_markup_bps": {"rule": "at_most", "limit": 3000}}


def test_a_retired_circuit_points_to_its_successor(circuits_api):
    with pytest.raises(HTTPException) as e:
        asyncio.run(circuits_api.get_circuit_vk("fairMarkupPolicy/v1.0.0"))
    assert e.value.status_code == 404 and "fairMarkupPolicy/v2.0.0" in e.value.detail


# ── the tutorial prover, offline ──────────────────────────────────────────

@needs_bb
@needs_nargo
@pytest.mark.parametrize("cid", list(Z._V2_CIRCUITS))
def test_the_tutorial_prover_makes_proofs_the_verifier_accepts(cid, registry):
    """Run with no network, this also proves the shipped reference string is enough to prove every v2 circuit."""
    from agentvault_registry.routers import admin_tutorial as T
    did = "did:theprotocol:tutorial-agent"
    made = asyncio.run(T.generate_zkp_proof({"circuit_id": cid, "agent_did": did}, developer=None))
    assert made["circuit_id"] == cid
    ref = Z.REFERENCE_INPUTS[cid]
    label = made["public_inputs"]["reference_label"]
    assert made["public_inputs"][ref] == str(Z.derive_reference(did, label))
    bound = {ref: str(Z.derive_reference(did, label))}
    result = _verify(cid, {"proof_bytes": made["proof_bytes_base64"]}, made["public_inputs"], expected=bound)
    assert result.verified, result.reason
    assert {k: str(result.public_values[k]) for k in made["public_outputs"]} == made["public_outputs"]
    other = {ref: str(Z.derive_reference("did:theprotocol:someone-else", label))}
    assert not _verify(cid, {"proof_bytes": made["proof_bytes_base64"]}, made["public_inputs"], expected=other).verified
    again = asyncio.run(T.generate_zkp_proof({"circuit_id": cid, "agent_did": did}, developer=None))
    assert again["proof_bytes_base64"] != made["proof_bytes_base64"]   # a fresh salt and label every time


def test_the_tutorial_needs_the_agent_that_will_submit():
    from agentvault_registry.routers import admin_tutorial as T
    with pytest.raises(HTTPException) as e:
        asyncio.run(T.generate_zkp_proof({"circuit_id": "fairMarkupPolicy/v2.0.0"}, developer=None))
    assert e.value.status_code == 400 and "agent_did" in e.value.detail


def test_the_tutorial_answers_a_v1_id_with_the_v2_circuit():
    from agentvault_registry.routers import admin_tutorial as T
    assert T._TUTORIAL_ALIASES["fairMarkupPolicy/v1.0.0"] == "fairMarkupPolicy/v2.0.0"
    assert set(T.TUTORIAL_CIRCUITS) == set(Z._V2_CIRCUITS)
    assert T._toml_value(["1", "2"]) == '["1", "2"]' and T._toml_value([True, False]) == "[true, false]"
    assert T._toml_value("7") == '"7"'


def test_an_unreadable_policy_is_described_as_such(monkeypatch):
    monkeypatch.setenv("ZKP_POLICY_JSON", "{not json")
    described = Z.circuit_spec("fairMarkupPolicy/v2.0.0")
    assert described["policy"] == {} and described["policy_error"].startswith("ZKP_POLICY_JSON is unreadable")
