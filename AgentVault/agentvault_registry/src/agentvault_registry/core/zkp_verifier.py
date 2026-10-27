"""
Zero-knowledge proof verifier.

Verifies UltraHonk proofs with the Barretenberg CLI (`bb`, installed in the
image) against the circuits in agentvault_circuit_registry/.

What a passing verification means for a v2.0.0 circuit:
  1. bb accepts the proof under the circuit's verification key;
  2. every public input the caller states equals the value the proof was
     made for. A bb 0.82.2 proof carries its public inputs (a 4-byte field
     count, then the public inputs in ABI order, then the circuit's public
     return value, then the proof proper); they are read back and compared,
     so a valid proof cannot be presented under other numbers;
  3. every policy limit in the proof is at least as strict as this
     registry's policy (metadata.json "Policy", overridable per registry
     with ZKP_POLICY_JSON);
  4. whatever the caller names in `expected` (an offer reference, a
     commitment a meter published) equals what the proof carries.

v1.0.0 circuits took their policy limits as private inputs that nothing
bound, so a v1 proof says nothing about the policy. They are refused unless
ZKP_ACCEPT_V1_CIRCUITS=true, kept only to re-read old attestations.

proof_of_reputation has no circuit keys yet. Its "Option B" path validates
the inputs and is reported as `not_a_proof`; it is never counted as a
verified proof.

Circuit registry: agentvault_circuit_registry/ (CIRCUIT_REGISTRY_PATH)
bb binary: /usr/local/bin/bb (BB_BINARY_PATH)
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Circuit registry root ──────────────────────────────────────────────────
# Preferred: CIRCUIT_REGISTRY_PATH env var (set in docker-compose.yml)
# Fallback: walk up from this file's location (parents[3] = /app in container)
_THIS_FILE = Path(__file__).resolve()
_CIRCUIT_REGISTRY_ROOT = Path(
    os.environ.get(
        "CIRCUIT_REGISTRY_PATH",
        str(_THIS_FILE.parents[3] / "agentvault_circuit_registry"),
    )
)

# ── bb binary path ─────────────────────────────────────────────────────────
_BB_BINARY = os.environ.get("BB_BINARY_PATH", "/usr/local/bin/bb")

# A real UltraHonk verification key is never smaller than this.
_MIN_VK_BYTES = 512

# Order of the BN254 scalar field: every public input is an element of it.
_BN254_R = 21888242871839275222246405745257275088548364400416034343698204186575808495617

# bb reads its reference string from $HOME/.bb-crs and downloads whatever is
# missing. agentvault_circuit_registry/crs/ ships, pinned here, the first
# 8,193 BN254 G1 points, the G2 point (Aztec Ignition) and the 65,537-point
# Grumpkin file bb loads before proving: enough to verify any proof and to
# prove every circuit of up to 8,192 gates (all four v2 circuits) without
# reaching the network. Without them bb 0.82.2 has nothing to verify
# against and exits on a segmentation fault; no registry had ever fetched them.
_CRS_FILES: Dict[str, str] = {
    "bn254_g1.dat": "ec2c34c509679e6152dee93f36f50d93def31809e1be0f0519036dcba8fdc2cb",
    "bn254_g2.dat": "01797bfc4de5a96f0e516a9ea4537d18786dc30cb991aca4274c95822b69c32f",
    "grumpkin_g1.dat": "d88e441db65412fe347b82e6d8e91e8223482dc1c380cd42d3feaa295dc95ec7",
    "grumpkin_size": "d57244ab10a76be13937db76648f504f437e6e0a7c310b4073d6c0bdce3c4ef5",
}

# ── v2.0.0 circuits: everything is read from the circuit's own files ──────
_V2_CIRCUITS = (
    "fairMarkupPolicy/v2.0.0",
    "accurateResourceUsagePolicy/v2.0.0",
    "fairCrossRegistryFee/v2.0.0",
    "contentSafetyAttestation/v2.0.0",
)

# ── v1.0.0 circuits (retired): public inputs in ABI order ─────────────────
_V1_CIRCUITS: Dict[str, Dict] = {
    "fairMarkupPolicy/v1.0.0": {
        "vk_path": "policies/fairMarkupPolicy/v1.0.0/verification_key.bin",
        "required_inputs": [
            "policy_parameters_hash",
            "self_attested_total_component_costs",
            "offered_price",
        ],
    },
    "accurateResourceUsagePolicy/v1.0.0": {
        "vk_path": "policies/accurateResourceUsagePolicy/v1.0.0/verification_key.bin",
        "required_inputs": [
            "policy_parameters_hash",
            "avtp_transaction_id",
            "reported_resource_units_used",
        ],
    },
    # Never given keys: listed so their ids resolve to a clear refusal.
    "fairCrossRegistryFee/v1.0.0": {
        "vk_path": "policies/fairCrossRegistryFee/v1.0.0/verification_key.bin",
        "required_inputs": [
            "policy_parameters_hash",
            "total_volume_transferred",
            "total_fees_collected",
        ],
    },
    "contentSafetyAttestation/v1.0.0": {
        "vk_path": "policies/contentSafetyAttestation/v1.0.0/verification_key.bin",
        "required_inputs": [
            "policy_parameters_hash",
            "time_window_hash",
            "total_samples",
            "min_rejection_count",
        ],
    },
}

# The public input that names what a proof is about (the offer, the
# transaction, the window). At submit the registry requires it to be
# derive_reference(<submitting agent DID>, <label>), so a proof names the
# agent that made it and cannot be presented under another agent's name;
# one verified attestation per circuit and reference.
REFERENCE_INPUTS: Dict[str, str] = {
    "fairMarkupPolicy/v2.0.0": "context",
    "accurateResourceUsagePolicy/v2.0.0": "transaction_ref",
    "fairCrossRegistryFee/v2.0.0": "window_ref",
    "contentSafetyAttestation/v2.0.0": "window_ref",
}

_REFERENCE_DOMAIN = b"tp.attestation.ref.v1|"


def derive_reference(agent_did: str, label: str) -> int:
    """The reference a v2 proof must carry for `agent_did` and `label`.

    The first 31 bytes of SHA-256("tp.attestation.ref.v1|" + agent DID + "|"
    + label), as a big-endian integer: always a field element, never chosen
    freely. The label names the offer, transaction or window (for example a
    quote id); a meter that publishes a log commitment derives the same
    reference from the agent DID and the transaction id.
    """
    digest = hashlib.sha256(_REFERENCE_DOMAIN + agent_did.encode() + b"|" + label.encode()).digest()
    return int.from_bytes(digest[:31], "big")


# Legacy and short circuit_id strings
_ALIASES: Dict[str, Optional[str]] = {
    "FAIR_MARKUP_POLICY_V1": "fairMarkupPolicy/v1.0.0",
    "PARU_V1": "accurateResourceUsagePolicy/v1.0.0",
    "FAIR_MARKUP_POLICY_V2": "fairMarkupPolicy/v2.0.0",
    "PARU_V2": "accurateResourceUsagePolicy/v2.0.0",
    "FAIR_CROSS_REGISTRY_FEE_V2": "fairCrossRegistryFee/v2.0.0",
    "CONTENT_SAFETY_ATTESTATION_V2": "contentSafetyAttestation/v2.0.0",
    # proof_of_reputation: Option B (input validation, not a proof)
    "ProofOfGoodReputation": None,
}

# ── Option B circuits: no keys, input validation only ──────────────────────
_OPTION_B_CIRCUITS = {"ProofOfGoodReputation", "proof_of_reputation/v1.0"}


@dataclass
class VerificationResult:
    """The outcome of one verification, with the reason it ended there.

    `verified` is True only when bb accepted the proof AND every check above
    passed. `status` is one of: verified, rejected, not_a_proof, error.
    `public_values` holds what the proof carries (inputs and outputs, as
    integers), filled once the proof has been read.
    """

    verified: bool
    status: str
    reason: str
    circuit_id: Optional[str] = None
    public_values: Dict[str, int] = field(default_factory=dict)


def _accept_v1() -> bool:
    return os.environ.get("ZKP_ACCEPT_V1_CIRCUITS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _resolve_circuit_id(circuit_id: str) -> Optional[str]:
    """Resolve an alias or canonical circuit id; None when unknown."""
    if circuit_id in _V2_CIRCUITS or circuit_id in _V1_CIRCUITS:
        return circuit_id
    if circuit_id in _OPTION_B_CIRCUITS:
        return circuit_id
    if circuit_id in _ALIASES:
        resolved = _ALIASES[circuit_id]
        # An alias that maps to None is an Option B circuit.
        return resolved if resolved is not None else circuit_id
    return None


def canonical_circuit_id(circuit_id: str) -> Optional[str]:
    """The canonical id for a circuit id or alias, or None when unknown."""
    return _resolve_circuit_id(circuit_id)


_v2_cache: Dict[str, Dict[str, Any]] = {}


def _load_v2(canonical_id: str) -> Dict[str, Any]:
    """Read a v2 circuit's metadata, ABI and key path (cached per process)."""
    if canonical_id in _v2_cache:
        return _v2_cache[canonical_id]
    name, version = canonical_id.split("/")
    cdir = _CIRCUIT_REGISTRY_ROOT / "policies" / name / version
    meta = json.loads((cdir / "metadata.json").read_text())
    artifact = json.loads((cdir / meta["Artifacts"]["circuit"]).read_text())
    abi = artifact["abi"]
    public = [p["name"] for p in abi["parameters"] if p["visibility"] == "public"]
    types = {p["name"]: p["type"] for p in abi["parameters"]}
    outputs = list(meta.get("PublicOutputs", {}).keys())
    ret = abi.get("return_type")
    n_out = 1 if ret and ret.get("visibility") == "public" else 0
    if len(outputs) != n_out or (ret and ret["abi_type"].get("kind") != "field"):
        raise ValueError(
            f"{canonical_id}: metadata names {len(outputs)} public outputs, "
            f"the circuit returns {n_out} field(s)"
        )
    for out in outputs:
        types[out] = {"kind": "field"}
    entry = {
        "vk": cdir / meta["Artifacts"]["verification_key"],
        "vk_sha256": meta["Artifacts"]["verification_key_sha256"],
        "public": public,
        "outputs": outputs,
        "types": types,
        "policy": meta.get("Policy", {}),
    }
    _v2_cache[canonical_id] = entry
    return entry


def _policy_overrides() -> Dict[str, Dict[str, int]]:
    """ZKP_POLICY_JSON: {"fairMarkupPolicy": {"max_markup_bps": 2500}, ...}.

    Raises ValueError when the variable is set but unreadable: a registry
    that meant to tighten its policy must not fall back to the defaults.
    """
    raw = os.environ.get("ZKP_POLICY_JSON", "").strip()
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("ZKP_POLICY_JSON must be a JSON object")
    out: Dict[str, Dict[str, int]] = {}
    for circuit, limits in data.items():
        if not isinstance(limits, dict):
            raise ValueError(f"ZKP_POLICY_JSON[{circuit!r}] must be an object")
        out[circuit] = {k: int(v) for k, v in limits.items()}
    return out


def _as_field(value: Any) -> Optional[int]:
    """A claimed public value as a field element; None when it is not one.

    Accepts ints, bools, decimal strings and 0x-hex strings. A value at or
    above the field order is refused rather than reduced, so two different
    claims can never name the same element.
    """
    if isinstance(value, bool):
        number = int(value)
    elif isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip()
        try:
            number = int(text, 16) if text.lower().startswith("0x") else int(text, 10)
        except ValueError:
            return None
    else:
        return None
    if number < 0 or number >= _BN254_R:
        return None
    return number


def _fits(abi_type: Dict[str, Any], number: int) -> bool:
    if abi_type.get("kind") == "integer":
        return number < (1 << int(abi_type.get("width", 254)))
    if abi_type.get("kind") == "boolean":
        return number in (0, 1)
    return True


def _proof_public_values(proof: bytes, count: int) -> Optional[List[int]]:
    """The first `count` public values a bb 0.82.2 proof carries.

    Layout: a 4-byte big-endian count of 32-byte field elements, then the
    elements, public values first. None when the bytes do not have that shape,
    or when any element is not a canonical field element: bb reduces every
    element modulo the field order on read, so x and x + r would verify alike
    and one proof could be resubmitted as hundreds of different byte strings.
    """
    if len(proof) < 4:
        return None
    n_fields = int.from_bytes(proof[:4], "big")
    if len(proof) != 4 + 32 * n_fields or n_fields <= count:
        return None
    elements = [int.from_bytes(proof[4 + 32 * i : 36 + 32 * i], "big") for i in range(n_fields)]
    if any(e >= _BN254_R for e in elements):
        return None
    return elements[:count]


_bb_home_ready: Optional[Path] = None


def _bb_home() -> Optional[Path]:
    """A HOME whose .bb-crs holds the pinned verification CRS; None if absent."""
    global _bb_home_ready
    if _bb_home_ready is not None:
        return _bb_home_ready
    home = Path(tempfile.gettempdir()) / "agentvault_bb_home"
    crs_dir = home / ".bb-crs"
    try:
        crs_dir.mkdir(parents=True, exist_ok=True)
        for fname, digest in _CRS_FILES.items():
            data = (_CIRCUIT_REGISTRY_ROOT / "crs" / fname).read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                logger.error("[ZKP] crs/%s does not match its pinned digest", fname)
                return None
            target = crs_dir / fname
            if not target.exists() or target.read_bytes() != data:
                # Write then rename: several workers may get here at once.
                tmp = crs_dir / f".{fname}.{os.getpid()}"
                tmp.write_bytes(data)
                os.replace(tmp, target)
    except OSError as exc:
        logger.error("[ZKP] cannot prepare the bb reference string: %s", exc)
        return None
    _bb_home_ready = home
    return home


def _verify_option_b(
    circuit_id: str,
    public_inputs: Dict[str, Any],
) -> VerificationResult:
    """proof_of_reputation: input validation only, never a verified proof.

    The registry database is the source of truth for reputation; this circuit
    has no keys, so there is nothing to verify cryptographically.
    """
    for name in ("reputation_threshold", "agent_did"):
        if name not in public_inputs:
            return VerificationResult(
                False, "rejected", f"missing public input '{name}'", circuit_id
            )
    try:
        threshold = int(public_inputs.get("reputation_threshold", 0))
    except (TypeError, ValueError):
        return VerificationResult(
            False, "rejected", "reputation_threshold is not a number", circuit_id
        )
    if threshold <= 0:
        return VerificationResult(
            False, "rejected", "reputation_threshold must be positive", circuit_id
        )
    return VerificationResult(
        False,
        "not_a_proof",
        "proof_of_reputation has no circuit keys; inputs are valid but nothing "
        "was proven (check the reputation against the registry instead)",
        circuit_id,
    )


async def _run_bb_verify(vk_path: Path, proof: bytes) -> VerificationResult:
    home = _bb_home()
    if home is None:
        return VerificationResult(False, "error", "bb reference string unavailable")
    if not Path(_BB_BINARY).exists():
        return VerificationResult(False, "error", f"bb binary not found at {_BB_BINARY}")
    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".proof", delete=False) as tmp:
            tmp.write(proof)
            tmp_path = tmp.name
        env = dict(os.environ, HOME=str(home))
        result = await asyncio.to_thread(
            subprocess.run,
            [_BB_BINARY, "verify", "-s", "ultra_honk", "-k", str(vk_path), "-p", tmp_path],
            capture_output=True,
            timeout=30,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return VerificationResult(False, "error", "bb verify timed out after 30s")
    except Exception as exc:  # pragma: no cover - logged and reported
        logger.error("[ZKP] bb verify failed to run: %s", exc, exc_info=True)
        return VerificationResult(False, "error", f"bb verify failed to run: {exc}")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    if result.returncode == 0:
        return VerificationResult(True, "verified", "bb accepted the proof")
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    if result.returncode < 0:
        return VerificationResult(
            False, "error", f"bb crashed (signal {-result.returncode}): {stderr[:200]}"
        )
    return VerificationResult(
        False, "rejected", f"bb rejected the proof (exit {result.returncode}): {stderr[:200]}"
    )


def bb_environment() -> Optional[Dict[str, str]]:
    """Environment for running bb with the pinned reference string, or None."""
    home = _bb_home()
    return None if home is None else dict(os.environ, HOME=str(home))


def proof_public_values(proof: bytes, circuit_id: str) -> Optional[Dict[str, int]]:
    """The public values a v2 proof carries, by name (None if unreadable)."""
    canonical_id = _resolve_circuit_id(circuit_id)
    if canonical_id not in _V2_CIRCUITS:
        return None
    spec = _load_v2(canonical_id)
    names = spec["public"] + spec["outputs"]
    values = _proof_public_values(proof, len(names))
    return None if values is None else dict(zip(names, values))


def circuit_spec(circuit_id: str) -> Optional[Dict[str, Any]]:
    """Public description of a v2 circuit: inputs, outputs and the policy in force."""
    canonical_id = _resolve_circuit_id(circuit_id)
    if canonical_id not in _V2_CIRCUITS:
        return None
    spec = _load_v2(canonical_id)
    described: Dict[str, Any] = {
        "public_inputs": list(spec["public"]),
        "public_outputs": list(spec["outputs"]),
    }
    try:
        overrides = _policy_overrides()
    except ValueError as exc:
        # Verification refuses every proof while the policy is unreadable;
        # the description says so instead of showing the defaults.
        described["policy"] = {}
        described["policy_error"] = f"ZKP_POLICY_JSON is unreadable: {exc}"
        return described
    name = canonical_id.split("/")[0]
    merged = {**overrides.get(name, {}), **overrides.get(canonical_id, {})}
    described["policy"] = {
        pname: {"rule": rule["rule"], "limit": int(merged.get(pname, rule["default"]))}
        for pname, rule in spec["policy"].items()
    }
    return described


def _decode_proof(proof_data: Dict[str, Any]) -> Optional[bytes]:
    proof_b64 = (proof_data or {}).get("proof_bytes")
    if not proof_b64:
        return None
    try:
        return base64.b64decode(proof_b64, validate=True)
    except Exception:
        return None


async def verify_proof_detailed(
    circuit_id: str,
    proof_data: Dict[str, Any],
    public_inputs: Dict[str, Any],
    expected: Optional[Dict[str, Any]] = None,
) -> VerificationResult:
    """Verify a proof and say why it passed or failed.

    proof_data: {"proof_bytes": "<base64 of the bb proof file>", "format": ...}
    public_inputs: the public values the caller states, by ABI name. For v2
        circuits every public input must be stated; a public output (the
        returned commitment) may be stated too.
    expected: values the caller requires the proof to carry, by name (for
        example {"context": offer_ref} or {"log_commitment": published}).
    """
    canonical_id = _resolve_circuit_id(circuit_id)
    if canonical_id is None:
        logger.error("[ZKP] Unknown circuit_id: %r", circuit_id)
        return VerificationResult(False, "rejected", f"unknown circuit_id {circuit_id!r}")

    if canonical_id in _OPTION_B_CIRCUITS:
        return _verify_option_b(canonical_id, public_inputs or {})

    proof = _decode_proof(proof_data)
    if proof is None:
        return VerificationResult(
            False, "rejected", "proof_data.proof_bytes is missing or not base64", canonical_id
        )
    public_inputs = public_inputs or {}

    if canonical_id in _V1_CIRCUITS:
        if not _accept_v1():
            return VerificationResult(
                False,
                "rejected",
                f"{canonical_id} is retired: its policy limits are private inputs "
                f"that nothing binds; prove with {canonical_id.split('/')[0]}/v2.0.0",
                canonical_id,
            )
        names = _V1_CIRCUITS[canonical_id]["required_inputs"]
        types: Dict[str, Dict[str, Any]] = {n: {"kind": "field"} for n in names}
        n_values = len(names)
        n_outputs = 0
        policy: Dict[str, Dict[str, Any]] = {}
        overrides: Dict[str, int] = {}
        vk_path = _CIRCUIT_REGISTRY_ROOT / _V1_CIRCUITS[canonical_id]["vk_path"]
        vk_digest = None
    else:
        try:
            spec = _load_v2(canonical_id)
            all_overrides = _policy_overrides()
        except (OSError, ValueError, KeyError) as exc:
            logger.error("[ZKP] %s: circuit or policy unreadable: %s", canonical_id, exc)
            return VerificationResult(False, "error", f"circuit or policy unreadable: {exc}", canonical_id)
        names = spec["public"] + spec["outputs"]
        types = spec["types"]
        n_values = len(names)
        n_outputs = len(spec["outputs"])
        policy = spec["policy"]
        name = canonical_id.split("/")[0]
        overrides = {**all_overrides.get(name, {}), **all_overrides.get(canonical_id, {})}
        vk_path = spec["vk"]
        vk_digest = spec["vk_sha256"]

    # 1. The proof's own public values.
    carried = _proof_public_values(proof, n_values)
    if carried is None:
        return VerificationResult(
            False, "rejected", "proof bytes do not have the bb proof layout (or carry a non-canonical element)", canonical_id
        )
    values = dict(zip(names, carried))
    result_base = dict(circuit_id=canonical_id, public_values=values)

    # 2. What the caller states must be what was proven.
    required = names[: len(names) - n_outputs]
    for pname in names:
        if pname not in public_inputs:
            if pname in required:
                return VerificationResult(False, "rejected", f"missing public input '{pname}'", **result_base)
            continue
        claimed = _as_field(public_inputs[pname])
        if claimed is None or not _fits(types.get(pname, {}), claimed):
            return VerificationResult(False, "rejected", f"public input '{pname}' is not a valid value", **result_base)
        if claimed != values[pname]:
            return VerificationResult(
                False, "rejected", f"public input '{pname}' differs from the value the proof was made for", **result_base
            )

    # 3. Policy limits must be at least as strict as this registry's.
    for pname, rule in policy.items():
        limit = int(overrides.get(pname, rule["default"]))
        got = values.get(pname)
        if got is None:
            return VerificationResult(False, "error", f"policy names unknown input '{pname}'", **result_base)
        if rule["rule"] == "at_most" and got > limit:
            return VerificationResult(
                False, "rejected", f"{pname}={got} is looser than this registry's policy ({limit})", **result_base
            )
        if rule["rule"] == "at_least" and got < limit:
            return VerificationResult(
                False, "rejected", f"{pname}={got} is looser than this registry's policy ({limit})", **result_base
            )

    # 4. Whatever the caller expects must be what the proof carries.
    for pname, want in (expected or {}).items():
        if pname not in values:
            return VerificationResult(False, "rejected", f"expected value names unknown input '{pname}'", **result_base)
        if _as_field(want) != values[pname]:
            return VerificationResult(
                False, "rejected", f"'{pname}' differs from the expected value", **result_base
            )

    # 5. The key, then bb.
    if not vk_path.exists() or vk_path.stat().st_size < _MIN_VK_BYTES:
        return VerificationResult(False, "error", f"verification key missing or too small: {vk_path}", **result_base)
    if vk_digest and hashlib.sha256(vk_path.read_bytes()).hexdigest() != vk_digest:
        return VerificationResult(False, "error", "verification key does not match its metadata digest", **result_base)
    outcome = await _run_bb_verify(vk_path, proof)
    outcome.circuit_id = canonical_id
    outcome.public_values = values
    if outcome.verified:
        logger.info("[ZKP] %s verified", canonical_id)
    else:
        logger.warning("[ZKP] %s not verified: %s", canonical_id, outcome.reason)
    return outcome


async def verify_proof(
    circuit_id: str,
    proof_data: Dict[str, Any],
    public_inputs: Dict[str, Any],
    expected: Optional[Dict[str, Any]] = None,
) -> bool:
    """True only when the proof verifies and every binding check passes."""
    result = await verify_proof_detailed(circuit_id, proof_data, public_inputs, expected)
    if not result.verified and result.status != "not_a_proof":
        logger.warning("[ZKP] %s: %s", circuit_id, result.reason)
    return result.verified


def get_supported_circuits() -> list[str]:
    """Circuit ids this registry verifies (retired v1 ids only when accepted)."""
    ids = list(_V2_CIRCUITS)
    if _accept_v1():
        ids += list(_V1_CIRCUITS)
    return ids + list(_OPTION_B_CIRCUITS)
