"""Real v2.0.0 proofs for the flow_zkp_* flows (§ZKV2).

The v1.0.0 circuits are retired (their policy limits were private inputs that
nothing bound) and proof_of_reputation's Option B is input validation, never a
verified proof. A flow that needs a verified attestation therefore asks the
target registry for a real proof: POST /api/v1/admin/tutorial/generate-proof
proves any of the four v2.0.0 circuits with nargo and bb inside the registry,
with a random salt and a random label, so every call gives a new proof.

A proof names the agent that will submit it. generate-proof requires
agent_did, and the proof's reference (context, transaction_ref or window_ref)
is derive_reference(agent_did, label): the first 31 bytes of SHA-256 over
"tp.attestation.ref.v1|", the DID, "|" and the label. The answer's
public_inputs carry the label as reference_label. /attestations/submit derives
the reference again from the submitting agent's DID and that label: without a
label it answers 422, and a proof made for another agent is "failed". The
registry keeps one verified attestation per circuit and reference and per
proof bytes (409 for either again), and refuses a proof element that is not
below the field order. So a flow asks for a fresh proof, for the agent that
submits it, for every attestation it means to have verified.

The registry ships the reference strings bb needs to prove and verify all four
circuits with no network: agentvault_circuit_registry/crs/ holds the first
8,193 BN254 G1 points, the G2 point and the 65,537-point Grumpkin file
(grumpkin_g1.dat with grumpkin_size), pinned by SHA-256 in core/zkp_verifier.
A target whose crs/ is missing or does not match answers generate-proof with
503; make_proof reports any answer as it came.

Every call goes through multiframe_helpers.http_in_container (a curl inside the
target registry container), like the rest of the flows.
"""
from __future__ import annotations

import asyncio
import hashlib
import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from agentvault_registry.api_tests.multiframe_helpers import (
    exec_in_container,
    http_in_container,
)

FAIR_MARKUP = "fairMarkupPolicy/v2.0.0"
RESOURCE_USAGE = "accurateResourceUsagePolicy/v2.0.0"
FEE = "fairCrossRegistryFee/v2.0.0"
CONTENT_SAFETY = "contentSafetyAttestation/v2.0.0"
V2_CIRCUITS = (FAIR_MARKUP, RESOURCE_USAGE, FEE, CONTENT_SAFETY)
V1_CIRCUITS = tuple(cid.replace("/v2.0.0", "/v1.0.0") for cid in V2_CIRCUITS)
OPTION_B = "proof_of_reputation/v1.0"

# The public input each v2 proof carries its agent-bound reference in
# (core/zkp_verifier.REFERENCE_INPUTS).
REFERENCE_INPUT = {
    FAIR_MARKUP: "context",
    RESOURCE_USAGE: "transaction_ref",
    FEE: "window_ref",
    CONTENT_SAFETY: "window_ref",
}

# Order of the BN254 scalar field: a proof element at or above it is refused.
BN254_R = 21888242871839275222246405745257275088548364400416034343698204186575808495617

# Proving runs nargo and bb in the registry, two at a time (about half a second
# for fairMarkupPolicy on a quiet box once the reference strings are present);
# the bound is generous for a loaded box and a first download.
PROOF_TIMEOUT_S = 300
SUBMIT_TIMEOUT_S = 60


def status_of(code: str) -> int:
    """The HTTP status a flow row records (500 when curl reported none)."""
    return int(code) if (code or "").isdigit() else 500


def derive_reference(agent_did: str, label: str) -> int:
    """The reference the registry requires (core/zkp_verifier.derive_reference)."""
    digest = hashlib.sha256(b"tp.attestation.ref.v1|" + agent_did.encode() + b"|" + label.encode()).digest()
    return int.from_bytes(digest[:31], "big")


async def make_proof(
    container: str, dev_jwt: str, circuit_id: str, agent_did: str,
) -> Tuple[bool, Dict[str, Any], str]:
    """Ask the target registry for a fresh v2 proof for the agent `agent_did`.

    Gives (ok, body, http_code). ok means the answer names the circuit,
    carries proof bytes and public inputs with a reference_label, and its
    reference is derive_reference(agent_did, reference_label); body is the
    endpoint's answer: {circuit_id, proof_bytes_base64, public_inputs (with
    reference_label), public_outputs, generation_time_ms}.
    """
    ok, body, code = await http_in_container(
        container, "POST", "/api/v1/admin/tutorial/generate-proof",
        body={"circuit_id": circuit_id, "agent_did": agent_did}, jwt=dev_jwt, timeout=PROOF_TIMEOUT_S,
    )
    body = body if isinstance(body, dict) else {}
    inputs = body.get("public_inputs") if isinstance(body.get("public_inputs"), dict) else {}
    label = inputs.get("reference_label")
    ref_name = REFERENCE_INPUT.get(circuit_id)
    try:
        bound = (
            isinstance(label, str) and bool(label) and ref_name is not None
            and int(str(inputs.get(ref_name)), 0) == derive_reference(agent_did, label)
        )
    except (TypeError, ValueError):
        bound = False
    good = (
        ok
        and body.get("circuit_id") == circuit_id
        and bool(body.get("proof_bytes_base64"))
        and bool(inputs)
        and isinstance(body.get("public_outputs"), dict)
        and bound
    )
    return good, body, code


# Proves one tutorial statement inside the target registry container with a
# label the flow chooses (generate-proof always picks a random one), so a flow
# can make a second, different proof with the same circuit and reference.
# argv: circuit_id, agent_did, label. Prints one line: ZKV2PROOF <json>.
_PROVE_WITH_LABEL = r"""
import base64, json, os, secrets, shutil, subprocess, sys, tempfile
sys.path.insert(0, "/app/src")
from agentvault_registry.core import zkp_verifier as Z
circuit_id, agent_did, label = sys.argv[1], sys.argv[2], sys.argv[3]
specs = {
    "fairMarkupPolicy/v2.0.0": ("fair_markup", {"max_markup_bps": "2000", "offered_price": "720"},
                                "context", {"total_cost": "600"}),
    "accurateResourceUsagePolicy/v2.0.0": ("accurate_resource_usage",
                                           {"max_discrepancy_bps": "100", "reported_units": "1000"},
                                           "transaction_ref", {"logged_units": "1000"}),
}
package, public, ref_name, private = specs[circuit_id]
env = Z.bb_environment()
if env is None:
    print("ZKV2PROOF " + json.dumps({"error": "bb reference string missing"}))
    sys.exit(0)
public = dict(public)
public[ref_name] = str(Z.derive_reference(agent_did, label))
inputs = {**public, **private, "salt": str(secrets.randbits(248))}
src = Z._CIRCUIT_REGISTRY_ROOT / "policies" / circuit_id.split("/")[0] / "v2.0.0"
with tempfile.TemporaryDirectory(prefix="flow_proof_") as work:
    os.makedirs(os.path.join(work, "src"))
    shutil.copy(src / "Nargo.toml", os.path.join(work, "Nargo.toml"))
    shutil.copy(src / "src" / "main.nr", os.path.join(work, "src", "main.nr"))
    with open(os.path.join(work, "Prover.toml"), "w") as f:
        f.write("".join(f'{k} = "{v}"\n' for k, v in inputs.items()))
    run = lambda cmd: subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=300)
    r = run(["nargo", "execute", "witness"])
    if r.returncode != 0:
        print("ZKV2PROOF " + json.dumps({"error": "nargo execute: " + r.stderr[-300:]}))
        sys.exit(0)
    target = os.path.join(work, "target")
    with open(os.path.join(target, package + ".json")) as f:
        bytecode = base64.b64decode(json.load(f)["bytecode"])
    with open(os.path.join(target, package + ".bin"), "wb") as f:
        f.write(bytecode)
    os.makedirs(os.path.join(target, "proof"))
    r = run(["bb", "prove", "-s", "ultra_honk", "-b", os.path.join(target, package + ".bin"),
             "-w", os.path.join(target, "witness.gz"), "-o", os.path.join(target, "proof")])
    if r.returncode != 0:
        print("ZKV2PROOF " + json.dumps({"error": "bb prove: " + r.stderr[-300:]}))
        sys.exit(0)
    with open(os.path.join(target, "proof", "proof"), "rb") as f:
        proof = f.read()
public["reference_label"] = label
print("ZKV2PROOF " + json.dumps({"circuit_id": circuit_id,
                                 "proof_bytes_base64": base64.b64encode(proof).decode("ascii"),
                                 "public_inputs": public}))
"""


async def prove_with_label(
    container: str, circuit_id: str, agent_did: str, label: str,
) -> Tuple[bool, Dict[str, Any]]:
    """A new proof (fresh salt) for agent_did with the label given, made inside the
    target registry container with its own nargo, bb and reference strings.

    fairMarkupPolicy and accurateResourceUsagePolicy only, with the tutorial's
    figures. Gives (ok, body): body as make_proof's, or {"error": ...}.
    """
    rc, out = await asyncio.to_thread(
        exec_in_container, container,
        ["python", "-c", _PROVE_WITH_LABEL, circuit_id, agent_did, label], PROOF_TIMEOUT_S,
    )
    lines = [line for line in (out or "").splitlines() if line.startswith("ZKV2PROOF ")]
    if rc != 0 or not lines:
        return False, {"error": f"in-container prover rc={rc}: {(out or '')[-300:]}"}
    try:
        body = json.loads(lines[-1][len("ZKV2PROOF "):])
    except ValueError:
        return False, {"error": "in-container prover printed no JSON"}
    return bool(body.get("proof_bytes_base64")) and "error" not in body, body


def offset_element(proof_b64: str, index: int = -1) -> Optional[str]:
    """The proof with one 32-byte element (the last by default) raised by the field
    order: the same proof to a verifier that reduces modulo r, other bytes to a
    replay check. The registry must refuse it as non-canonical."""
    try:
        raw = bytearray(base64.b64decode(proof_b64))
    except Exception:
        return None
    if len(raw) < 4:
        return None
    n_fields = int.from_bytes(raw[:4], "big")
    if len(raw) != 4 + 32 * n_fields or n_fields == 0:
        return None
    i = index % n_fields
    start = 4 + 32 * i
    value = int.from_bytes(raw[start:start + 32], "big") + BN254_R
    if value >= 1 << 256:
        return None
    raw[start:start + 32] = value.to_bytes(32, "big")
    return base64.b64encode(bytes(raw)).decode("ascii")


def submission(circuit_id: str, proof: Dict[str, Any], public_inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The /attestations/submit body for a tutorial proof (its own inputs unless others are given)."""
    stated = proof.get("public_inputs") if public_inputs is None else public_inputs
    return {
        "circuit_id": circuit_id,
        "proof_data": {"proof_bytes": proof.get("proof_bytes_base64", ""), "format": "ultra_honk"},
        "public_inputs": dict(stated or {}),
    }


async def submit(container: str, agent_jwt: str, body: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
    """POST /api/v1/attestations/submit as the agent. Returns (ok, body, http_code)."""
    ok, resp, code = await http_in_container(
        container, "POST", "/api/v1/attestations/submit",
        body=body, jwt=agent_jwt, timeout=SUBMIT_TIMEOUT_S,
    )
    return ok, (resp if isinstance(resp, dict) else {}), code


async def prove_and_submit(
    container: str, dev_jwt: str, agent_jwt: str, circuit_id: str, agent_did: str,
) -> Dict[str, Any]:
    """Make a fresh proof for agent_did and submit it, as that agent (agent_jwt
    must be its token), under its own public inputs and reference_label.

    Returns {verified, attestation_id, proof, response, code, error}: verified
    is True only when the registry answered status "verified" with an id, and
    `error` says which half failed otherwise.
    """
    ok_p, proof, code_p = await make_proof(container, dev_jwt, circuit_id, agent_did)
    if not ok_p:
        detail = proof.get("detail") or proof.get("_raw") or proof
        return {
            "verified": False, "attestation_id": None, "proof": proof, "response": {},
            "code": code_p,
            "error": f"generate-proof failed (http={code_p}): {str(detail)[:200]}",
        }
    ok_s, resp, code_s = await submit(container, agent_jwt, submission(circuit_id, proof))
    verified = ok_s and resp.get("status") == "verified" and bool(resp.get("attestation_id"))
    return {
        "verified": verified,
        "attestation_id": resp.get("attestation_id"),
        "proof": proof,
        "response": resp,
        "code": code_s,
        "error": None if verified else (
            f"submit did not verify (http={code_s}, status={resp.get('status')}, "
            f"reason={str(resp.get('reason') or resp.get('detail'))[:200]})"
        ),
    }


def carried_matches(resp: Dict[str, Any], proof: Dict[str, Any]) -> bool:
    """Whether the submit answer's proof_public_values name the same numbers as the proof.

    proof_public_values are decimal strings; the tutorial answer gives the
    public inputs as decimal strings and the commitment as a decimal string.
    reference_label is not a value the proof carries and is left out.
    """
    carried = resp.get("proof_public_values") or {}
    inputs = {k: v for k, v in (proof.get("public_inputs") or {}).items() if k != "reference_label"}
    expected = {**inputs, **(proof.get("public_outputs") or {})}
    if not carried or not expected:
        return False
    try:
        return all(int(str(carried.get(k)), 0) == int(str(v), 0) for k, v in expected.items())
    except (TypeError, ValueError):
        return False


def proof_sha256(proof_b64: str) -> Optional[str]:
    """The sha256 the registry stores as proof_hash, from the base64 proof."""
    try:
        return hashlib.sha256(base64.b64decode(proof_b64)).hexdigest()
    except Exception:
        return None


async def fetch_size(container: str, path: str) -> Tuple[str, int]:
    """GET a binary route inside the container: (http_code, bytes received)."""
    script = (
        "curl -sS -o /dev/null -w '%{http_code} %{size_download}' "
        f"http://localhost:8000{path}"
    )
    rc, out = await asyncio.to_thread(exec_in_container, container, ["sh", "-c", script], 30)
    parts = (out or "").strip().split()
    if rc != 0 or len(parts) < 2:
        return "000", 0
    try:
        return parts[-2], int(float(parts[-1]))
    except ValueError:
        return parts[-2], 0


async def wait_out_utc_midnight(margin_s: int = 600) -> float:
    """Sleep past the next UTC midnight when it is less than margin_s away.

    The reputation point and the governance count are per UTC day; a flow that
    asserts "same day" must not straddle midnight. Returns the seconds slept.
    """
    now = datetime.now(timezone.utc)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    left = (midnight - now).total_seconds()
    if left >= margin_s:
        return 0.0
    await asyncio.sleep(left + 5)
    return left + 5
