"""The SDK's v2 prover: the Prover.toml it writes, the public values it reads back, a real proof where nargo and bb exist.

The circuit legs need nargo 1.0.0-beta.3 and bb 0.82.2 (the registry image has both) and the circuit registry next to
this package; they skip elsewhere. Every other leg runs anywhere.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agentvault_server_sdk import zkp_attestation as Z

DID = "did:theprotocol:9f1c2b3a-4d5e-4f60-8a7b-1c2d3e4f5a6b"
OTHER_DID = "did:theprotocol:0000aaaa-bbbb-4ccc-8ddd-eeeeffff0000"

# Computed in the registry image with core.zkp_verifier.derive_reference: the
# SDK must derive the same reference, or the registry refuses every proof it makes.
REGISTRY_REFERENCES = [
    (DID, "quote-42", 273143511037100201787200210499531535107646453148744436308721275980945776431),
    (DID, "quote-43", 163813362012879529815250066226977910224252277202291972274706091876858723253),
    (OTHER_DID, "quote-42", 136782299512938503002719757591536335252326605152832797579025446545430977507),
    ("did:cos:453d4a48", "tx-\u00e9\u00fc-7", 48500548670621692660404224281283808926795607740120303195110567771455115826),
]


def _fake_proof(values):
    """Bytes with the bb 0.82.2 layout: a field count, the public values, then a body."""
    body = [0] * 8
    fields = list(values) + body
    return len(fields).to_bytes(4, "big") + b"".join(v.to_bytes(32, "big") for v in fields)


# ── Prover.toml ───────────────────────────────────────────────────────────

def test_prover_toml_writes_numbers_booleans_and_arrays():
    text = Z.render_prover_toml({
        "max_markup_bps": 3000,
        "context": "0x1234",
        "amounts": [10000, "20000", 0],
        "rejected": [True, False],
    })
    assert text.splitlines()[1:] == [
        'max_markup_bps = "3000"',
        'context = "0x1234"',
        'amounts = ["10000", "20000", "0"]',
        "rejected = [true, false]",
    ]


@pytest.mark.parametrize("bad", [
    {"total_cost": '1"\nsalt = "2'},       # a value cannot break out of its line
    {"total_cost": "quote-42"},            # only decimal or 0x numbers
    {"total_cost": -1},                    # inputs are unsigned
    {"total cost": "1"},                   # a key must be an input name
    {"total_cost": 1.5},
])
def test_prover_toml_refuses_what_could_change_its_meaning(bad):
    with pytest.raises(ValueError):
        Z.render_prover_toml(bad)


@pytest.mark.parametrize("did,label,expected", REGISTRY_REFERENCES)
def test_the_reference_is_the_registrys(did, label, expected):
    assert Z.derive_reference(did, label) == expected
    assert 0 < expected < 2 ** 248 < Z.BN254_R


def _registry_src():
    here = Path(__file__).resolve()
    for candidate in (here.parents[2] / "agentvault_registry" / "src", Path("/app/src")):
        if (candidate / "agentvault_registry" / "core" / "zkp_verifier.py").is_file():
            return candidate
    return None


@pytest.mark.skipif(_registry_src() is None, reason="needs the registry source next to this package")
def test_the_reference_matches_the_registry_function_itself():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_registry_zkp_verifier", _registry_src() / "agentvault_registry" / "core" / "zkp_verifier.py")
    registry = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(registry)
    except ImportError as exc:  # its imports may need the registry's dependencies
        pytest.skip(f"the registry module does not import here: {exc}")
    for did, label, _ in REGISTRY_REFERENCES + [(DID, "sdk-0123456789abcdef", None), (DID, "x" * 200, None)]:
        assert Z.derive_reference(did, label) == registry.derive_reference(did, label)


def test_labels_are_the_callers_id_as_given_or_random():
    assert Z.label_for("quote-42") == "quote-42"
    assert Z.label_for(7) == "7"
    first, second = Z.label_for(None), Z.label_for(None)
    assert first != second and first.startswith("sdk-") and len(first) == 20
    for bad in ("", "x" * 201, True, b"quote-42", 1.5):
        with pytest.raises(Z.ZKPProofGenerationError):
            Z.label_for(bad)


def test_field_values_are_numbers_only_and_samples_are_hashed():
    assert Z.to_field(7) == 7 and Z.to_field("0x10") == 16 and Z.to_field("16") == 16
    for bad in ("quote-42", b"16", Z.BN254_R, -1, True):
        with pytest.raises(ValueError):
            Z.to_field(bad)
    assert Z.sample_hash("hello") == Z.sample_hash(b"hello") < 2 ** 248
    assert Z.sample_hash(5) == 5


def test_public_values_are_read_in_order_and_a_wrong_layout_is_refused():
    raw = _fake_proof([1, 2, 3, 4])
    assert Z.read_public_values(raw, ["a", "b", "c", "out"]) == {"a": 1, "b": 2, "c": 3, "out": 4}
    with pytest.raises(Z.ZKPProofGenerationError):
        Z.read_public_values(raw[:-1], ["a"])


# ── generate_proof: what it writes, what it checks ───────────────────────────

def _offline_client(tmp_path, monkeypatch, carried=None):
    client = Z.ZKPAttestationClient("http://registry.invalid", "jwt", circuit_base_dir=str(tmp_path / "cache"))
    cid = "fairMarkupPolicy/v2.0.0"
    client._circuit_dirs[cid] = tmp_path / "cache" / "unused"
    seen = {}

    def fake_run(circuit_dir, meta, prover_toml):
        seen["toml"] = prover_toml
        lines = dict(line.split(" = ", 1) for line in prover_toml.splitlines()[1:])
        values = carried or [Z.to_field(lines[k].strip('"')) for k in meta.public_input_keys]
        return _fake_proof(values + [0xC0FFEE])

    monkeypatch.setattr(client, "_run_proof_subprocess", fake_run)
    return client, cid, seen


def test_the_prover_toml_has_every_input_in_abi_order_with_a_fresh_salt_and_label(tmp_path, monkeypatch):
    client, cid, seen = _offline_client(tmp_path, monkeypatch)
    proof = asyncio.run(client.generate_proof(cid, {"max_markup_bps": 2000, "offered_price": 720},
                                              {"total_cost": 600}, agent_did=DID))
    lines = seen["toml"].splitlines()[1:]
    assert [line.split(" = ")[0] for line in lines] == ["max_markup_bps", "offered_price", "context",
                                                        "total_cost", "salt"]
    assert lines[0] == 'max_markup_bps = "2000"' and lines[3] == 'total_cost = "600"'
    label = proof.public_inputs["reference_label"]
    assert label.startswith("sdk-") and proof.reference_label == label
    assert proof.public_inputs["context"] == lines[2].split(" = ")[1].strip('"') == str(Z.derive_reference(DID, label))
    assert "total_cost" not in proof.public_inputs                    # the cost stays private
    assert proof.public_outputs == {"cost_commitment": "0x" + format(0xC0FFEE, "064x")}
    assert proof.opening["total_cost"] == 600 and proof.opening["salt"].startswith("0x")
    assert proof.proof_data["format"] == "ultra_honk"
    assert base64.b64decode(proof.proof_data["proof_bytes"]) == proof.proof_bytes

    again = asyncio.run(client.generate_proof(cid, {"max_markup_bps": 2000, "offered_price": 720},
                                              {"total_cost": 600}, agent_did=DID))
    assert again.opening["salt"] != proof.opening["salt"]
    assert again.public_inputs["context"] != proof.public_inputs["context"]


def test_the_reference_comes_only_from_the_agent_did_and_the_label(tmp_path, monkeypatch):
    client, cid, seen = _offline_client(tmp_path, monkeypatch)
    public = {"max_markup_bps": 2000, "offered_price": 720}
    with pytest.raises(Z.ZKPProofGenerationError, match="agent_did"):
        asyncio.run(client.generate_proof(cid, public, {"total_cost": 600}, agent_did=""))
    with pytest.raises(TypeError):
        asyncio.run(client.generate_proof(cid, public, {"total_cost": 600}))
    with pytest.raises(Z.ZKPProofGenerationError, match="reference_label"):
        asyncio.run(client.generate_proof(cid, {**public, "context": 5}, {"total_cost": 600}, agent_did=DID))
    assert "toml" not in seen
    mine = asyncio.run(client.generate_proof(cid, public, {"total_cost": 600}, agent_did=DID,
                                             reference_label="quote-42"))
    theirs = asyncio.run(client.generate_proof(cid, public, {"total_cost": 600}, agent_did=OTHER_DID,
                                               reference_label="quote-42"))
    assert mine.public_inputs["context"] == str(REGISTRY_REFERENCES[0][2])
    assert theirs.public_inputs["context"] == str(REGISTRY_REFERENCES[2][2])
    # a label stated in the public inputs is the same as one passed by name
    stated = asyncio.run(client.generate_proof(cid, {**public, "reference_label": "quote-42"}, {"total_cost": 600},
                                               agent_did=DID))
    assert stated.public_inputs["context"] == mine.public_inputs["context"]


def test_a_proof_that_carries_other_inputs_is_refused(tmp_path, monkeypatch):
    client, cid, _ = _offline_client(tmp_path, monkeypatch,
                                     carried=[2000, 721, Z.derive_reference(DID, "quote-42")])
    with pytest.raises(Z.ZKPProofGenerationError, match="different 'offered_price'"):
        asyncio.run(client.generate_proof(cid, {"max_markup_bps": 2000, "offered_price": 720},
                                          {"total_cost": 600}, agent_did=DID, reference_label="quote-42"))


def test_missing_and_unknown_inputs_are_refused_before_proving(tmp_path, monkeypatch):
    client, cid, seen = _offline_client(tmp_path, monkeypatch)
    with pytest.raises(Z.ZKPProofGenerationError, match="missing"):
        asyncio.run(client.generate_proof(cid, {"max_markup_bps": 2000}, {"total_cost": 600}, agent_did=DID))
    with pytest.raises(Z.ZKPProofGenerationError, match="unknown"):
        asyncio.run(client.generate_proof(cid, {"max_markup_bps": 2000, "offered_price": 720},
                                          {"total_cost": 600, "markup": 20}, agent_did=DID))
    assert "toml" not in seen


def test_figures_no_proof_exists_for_are_refused_locally(tmp_path, monkeypatch):
    client, _, seen = _offline_client(tmp_path, monkeypatch)
    with pytest.raises(Z.ZKPProofGenerationError, match="no proof exists"):
        asyncio.run(client.attest_fair_markup(agent_did=DID, total_cost=1000, offered_price=1301,
                                              max_markup_bps=3000))
    with pytest.raises(Z.ZKPProofGenerationError, match="no proof exists"):
        asyncio.run(client.attest_resource_usage(agent_did=DID, reported_units=203, logged_units=200,
                                                 max_discrepancy_bps=100))
    assert "toml" not in seen


def test_a_registry_answer_that_is_not_verified_raises_with_the_reason(tmp_path, monkeypatch):
    client, cid, _ = _offline_client(tmp_path, monkeypatch)
    answer = {"status": "failed", "reason": "max_markup_bps=3500 is looser than this registry's policy (3000)"}
    monkeypatch.setattr(client, "_http_post_json", lambda url, payload: answer)
    with pytest.raises(Z.ZKPAttestationError, match="looser") as err:
        asyncio.run(client.submit_attestation(cid, b"\x00" * 4, {"reference_label": "quote-42"}))
    assert err.value.response == answer


def test_raw_bytes_without_a_reference_label_are_not_sent(tmp_path, monkeypatch):
    client, cid, _ = _offline_client(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr(client, "_http_post_json", lambda url, payload: sent.append(payload) or {})
    with pytest.raises(Z.ZKPAttestationError, match="reference_label"):
        asyncio.run(client.submit_attestation(cid, b"\x00" * 4, {"max_markup_bps": "3000"}))
    assert sent == []


def test_prove_and_submit_sends_the_dict_the_registry_takes_and_hands_back_the_commitment(tmp_path, monkeypatch):
    client, cid, _ = _offline_client(tmp_path, monkeypatch)
    sent = {}

    def fake_post(url, payload):
        sent.update(json.loads(payload))
        return {"status": "verified", "attestation_id": "a1", "reputation_delta": 1,
                "proof_public_values": {"cost_commitment": str(0xC0FFEE)}}

    monkeypatch.setattr(client, "_http_post_json", fake_post)
    result = asyncio.run(client.attest_fair_markup(agent_did=DID, total_cost=1000, offered_price=1200,
                                                   context="quote-42", max_markup_bps=3000))
    reference = str(REGISTRY_REFERENCES[0][2])
    assert set(sent) == {"circuit_id", "proof_data", "public_inputs"}
    assert sent["proof_data"]["format"] == "ultra_honk" and base64.b64decode(sent["proof_data"]["proof_bytes"])
    assert sent["public_inputs"] == {"max_markup_bps": "3000", "offered_price": "1200",
                                     "context": reference, "reference_label": "quote-42"}
    assert result["status"] == "verified" and result["commitment"] == {"cost_commitment": "0x" + format(0xC0FFEE, "064x")}
    assert result["reference"] == {"context": reference} and result["reference_label"] == "quote-42"
    assert result["opening"]["total_cost"] == 1000


# ── a real proof (nargo + bb + the circuit registry) ────────────────────────

def _registry_dir():
    here = Path(__file__).resolve()
    for candidate in (here.parents[2] / "agentvault_circuit_registry", Path("/app/agentvault_circuit_registry")):
        if (candidate / "policies").is_dir():
            return candidate
    return None


@pytest.mark.skipif(shutil.which("nargo") is None or shutil.which("bb") is None or _registry_dir() is None,
                    reason="needs nargo, bb and the circuit registry (the registry image has them)")
@pytest.mark.parametrize("cid", ["fairMarkupPolicy/v2.0.0", "accurateResourceUsagePolicy/v2.0.0"])
def test_a_real_proof_carries_its_inputs_and_bb_verifies_it(cid, tmp_path):
    src = _registry_dir() / "policies" / cid
    cache = tmp_path / "cache" / cid.replace("/", "_")
    (cache / "src").mkdir(parents=True)
    shutil.copy(src / "Nargo.toml", cache / "Nargo.toml")
    shutil.copy(src / "src" / "main.nr", cache / "src" / "main.nr")
    artifact = json.loads((src / "circuit.json").read_text())
    meta = Z._KNOWN_CIRCUITS[cid]
    (cache / f"{meta.nargo_package_name}.bin").write_bytes(base64.b64decode(artifact["bytecode"]))

    # The registry's shipped reference string, so the proof needs no network and no ~/.bb-crs.
    home = tmp_path / "bb_home"
    shutil.copytree(_registry_dir() / "crs", home / ".bb-crs")
    client = Z.ZKPAttestationClient("http://registry.invalid", "jwt", circuit_base_dir=str(tmp_path / "cache"),
                                    bb_binary=shutil.which("bb"), nargo_binary=shutil.which("nargo"),
                                    bb_home=str(home))
    client._circuit_dirs[cid] = cache
    if cid.startswith("fair"):
        proof = asyncio.run(client.generate_proof(cid, {"max_markup_bps": 2000, "offered_price": 720},
                                                  {"total_cost": 600}, agent_did=DID))
    else:
        proof = asyncio.run(client.generate_proof(cid, {"max_discrepancy_bps": 100, "reported_units": 1000},
                                                  {"logged_units": 1000}, agent_did=DID, reference_label="tx-1"))
    proof_file = tmp_path / "proof"
    proof_file.write_bytes(proof.proof_bytes)
    checked = subprocess.run([shutil.which("bb"), "verify", "-s", "ultra_honk", "-k", str(src / "verification_key.bin"),
                              "-p", str(proof_file)], capture_output=True, text=True, timeout=120,
                             env={**os.environ, "HOME": str(home)})
    assert checked.returncode == 0, checked.stderr[-1000:]
    assert proof.public_outputs[meta.output_key].startswith("0x")
    assert proof.public_inputs[meta.reference_key] == str(Z.derive_reference(DID, proof.reference_label))
