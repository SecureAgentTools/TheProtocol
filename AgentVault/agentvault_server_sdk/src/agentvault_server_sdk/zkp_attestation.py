"""
ZKP attestation client for TheProtocol agent SDK (v2.0.0 circuits).

An agent proves a statement about its own figures on its own machine with
nargo and bb, and sends the registry only the proof and its public inputs.
The registry verifies the proof with POST /api/v1/attestations/submit.

The four v2.0.0 circuits and what each proof binds:

  fairMarkupPolicy/v2.0.0
      public:  max_markup_bps, offered_price, context (the offer reference)
      private: total_cost, salt
      outputs: cost_commitment = Poseidon2(DOMAIN, total_cost, salt)
      statement: offered_price * 10000 <= total_cost * (10000 + max_markup_bps)
  accurateResourceUsagePolicy/v2.0.0
      public:  max_discrepancy_bps, transaction_ref (the transaction reference), reported_units
      private: logged_units, salt
      outputs: log_commitment = Poseidon2(DOMAIN, transaction_ref, logged_units, salt)
      statement: |reported_units - logged_units| * 10000 <= logged_units * max_discrepancy_bps
  fairCrossRegistryFee/v2.0.0
      public:  max_fee_bps, window_ref (the window reference), total_volume, total_fees
      private: amounts[16], fees[16], salt (unused slots are zero)
      outputs: batch_commitment
      statement: every fees[i] * 10000 <= amounts[i] * max_fee_bps, and the sums match
  contentSafetyAttestation/v2.0.0
      public:  min_rejection_bps, window_ref (the window reference), total_samples (1..64)
      private: sample_hashes[64], rejected[64], salt (unused slots are zero / false)
      outputs: log_commitment
      statement: rejected * 10000 >= total_samples * min_rejection_bps

What a verified proof says, and what it does not:
  - The policy limit and the reference are public and bound to the proof; the
    registry refuses a limit looser than its own policy.
  - The private figure (a cost, a meter log, a fee batch, a moderation log) is
    bound to the returned commitment. The proof does NOT show the figure is
    true. The commitment lets an auditor ask the agent to open it (the figure
    and the salt), and a meter that published a log commitment beforehand lets
    a verifier compare it. No proof shows which model made a moderation decision.

The reference names the agent that made the proof. The registry requires a
v2 proof's reference to be derive_reference(<submitting agent DID>, <label>):
the first 31 bytes of SHA-256 over "tp.attestation.ref.v1|", the DID, "|" and
the label, as a big-endian number. The label (1 to 200 characters) is sent as
public_inputs["reference_label"], and a proof made for one agent is not
verified when another agent submits it. Every prove and attest call therefore
takes the agent DID; the label is the caller's offer, transaction or window id
as given, or a random "sdk-<16 hex>" when none is named. The registry keeps
one verified attestation per circuit and reference, and answers 409 to the
same proof or the same circuit and reference again.

Every proof also gets a fresh random salt. The client hands back the
commitment read from the proof, the reference, the label and the opening (the
private figure and the salt): keep the opening private, it is what an auditor
asks for.

bb reads its reference string (CRS) from $HOME/.bb-crs and downloads what it
is missing. bb prove reads two curves: bn254_g1.dat (the first 4,097 points
prove fairMarkupPolicy and accurateResourceUsagePolicy; fairCrossRegistryFee
and contentSafetyAttestation need 8,193) and grumpkin_g1.dat (bb 0.82.2 asks
for 65,537 points), plus bn254_g2.dat. An agent without network access needs
these files in place before its first proof: the registry's source ships them
in agentvault_circuit_registry/crs (bn254_g1.dat, bn254_g2.dat, grumpkin_g1.dat,
grumpkin_size), and copying them into $HOME/.bb-crs is enough. Pass bb_home to
point bb at another HOME.

Usage:
    client = ZKPAttestationClient(registry_url="https://registry.example.com", agent_jwt="eyJ...")
    await client.initialize()          # downloads the circuits once

    result = await client.attest_fair_markup(
        agent_did="did:theprotocol:...", total_cost=1000, offered_price=1200, context="quote-42")
    result["status"]                   # "verified"
    result["reference_label"]          # "quote-42"
    result["commitment"]               # {"cost_commitment": "0x..."}
    result["opening"]                  # {"total_cost": "1000", "salt": "0x..."}: keep private
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Union

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────

class ZKPError(Exception):
    """Base exception for all ZKP-related errors."""


class ZKPBinaryNotFoundError(ZKPError):
    """Raised when nargo or bb binary is not found at the expected path."""


class ZKPCircuitNotAvailableError(ZKPError):
    """Raised when a requested circuit is not available (unknown ID or download failure)."""


class ZKPProofGenerationError(ZKPError):
    """Raised when the inputs cannot satisfy the circuit, or nargo or bb fails."""


class ZKPAttestationError(ZKPError):
    """Raised when the registry does not verify an attestation.

    `response` holds the registry's answer when there was one (status, reason,
    proof_public_values).
    """

    def __init__(self, message: str, response: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.response = response


# ─────────────────────────────────────────────────────────────────────────────
# Known circuits: the client side of each circuit's ABI
# ─────────────────────────────────────────────────────────────────────────────

# Order of the BN254 scalar field: every public value is an element of it.
BN254_R = 21888242871839275222246405745257275088548364400416034343698204186575808495617

_U32 = (1 << 32) - 1
_U64 = (1 << 64) - 1


@dataclass(frozen=True)
class _CircuitMeta:
    """The client's view of one v2.0.0 circuit."""
    nargo_package_name: str        # name field in Nargo.toml
    public_input_keys: List[str]   # ABI order, as main.nr declares them
    private_input_keys: List[str]
    reference_key: str             # the public reference: derive_reference(agent DID, label)
    output_key: str                # the commitment the circuit outputs
    policy_key: str                # the policy limit the registry checks
    policy_default: int            # the shipped default (metadata.json "Policy")


_KNOWN_CIRCUITS: Dict[str, _CircuitMeta] = {
    "fairMarkupPolicy/v2.0.0": _CircuitMeta(
        nargo_package_name="fair_markup",
        public_input_keys=["max_markup_bps", "offered_price", "context"],
        private_input_keys=["total_cost", "salt"],
        reference_key="context",
        output_key="cost_commitment",
        policy_key="max_markup_bps",
        policy_default=3000,
    ),
    "accurateResourceUsagePolicy/v2.0.0": _CircuitMeta(
        nargo_package_name="accurate_resource_usage",
        public_input_keys=["max_discrepancy_bps", "transaction_ref", "reported_units"],
        private_input_keys=["logged_units", "salt"],
        reference_key="transaction_ref",
        output_key="log_commitment",
        policy_key="max_discrepancy_bps",
        policy_default=100,
    ),
    "fairCrossRegistryFee/v2.0.0": _CircuitMeta(
        nargo_package_name="fair_cross_registry_fee",
        public_input_keys=["max_fee_bps", "window_ref", "total_volume", "total_fees"],
        private_input_keys=["amounts", "fees", "salt"],
        reference_key="window_ref",
        output_key="batch_commitment",
        policy_key="max_fee_bps",
        policy_default=50,
    ),
    "contentSafetyAttestation/v2.0.0": _CircuitMeta(
        nargo_package_name="content_safety_attestation",
        public_input_keys=["min_rejection_bps", "window_ref", "total_samples"],
        private_input_keys=["sample_hashes", "rejected", "salt"],
        reference_key="window_ref",
        output_key="log_commitment",
        policy_key="min_rejection_bps",
        policy_default=9000,
    ),
}

FEE_BATCH_SLOTS = 16
SAFETY_LOG_SLOTS = 64


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers (no I/O): field values, Prover.toml, the proof's public values
# ─────────────────────────────────────────────────────────────────────────────

def random_salt() -> str:
    """A fresh 248-bit blinding value, as a 0x string."""
    return hex(secrets.randbits(248))


# The registry's rule (core/zkp_verifier.derive_reference); the two must agree
# byte for byte, or every proof this client makes is refused.
REFERENCE_DOMAIN = b"tp.attestation.ref.v1|"
MAX_REFERENCE_LABEL = 200


def derive_reference(agent_did: str, label: str) -> int:
    """The reference a v2 proof carries for `agent_did` and `label`.

    The first 31 bytes of SHA-256("tp.attestation.ref.v1|" + agent DID + "|"
    + label), as a big-endian integer: always a field element. The registry
    computes the same value from the submitting agent's DID and
    public_inputs["reference_label"] and refuses a proof that carries another.
    """
    digest = hashlib.sha256(REFERENCE_DOMAIN + agent_did.encode() + b"|" + label.encode()).digest()
    return int.from_bytes(digest[:31], "big")


def random_label() -> str:
    """A fresh label for a proof that names no offer, transaction or window."""
    return f"sdk-{secrets.token_hex(8)}"


def label_for(value: Union[int, str, None]) -> str:
    """The label for a proof: the caller's id as given, or a random one.

    An int is written in decimal. The registry takes 1 to 200 characters.
    """
    if value is None:
        return random_label()
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ZKPProofGenerationError("a reference label is a string (or an int, written in decimal)")
    label = str(value)
    if not 0 < len(label) <= MAX_REFERENCE_LABEL:
        raise ZKPProofGenerationError(f"a reference label is 1 to {MAX_REFERENCE_LABEL} characters")
    return label


def _agent_did(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("did:"):
        raise ZKPProofGenerationError(
            "agent_did is required (the submitting agent's DID): the proof's reference names it"
        )
    return value


def to_field(value: Union[int, str]) -> int:
    """A number as a field element: an int, a decimal string or a 0x string.

    It must be below the field order. Any other value is refused.
    """
    if isinstance(value, bool):
        raise ValueError("a boolean is not a field value")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"0[xX][0-9a-fA-F]+", text):
            number = int(text, 16)
        elif re.fullmatch(r"[0-9]+", text):
            number = int(text, 10)
        else:
            raise ValueError(f"not a decimal or 0x number: {value!r}")
    else:
        raise ValueError(f"cannot use {type(value).__name__} as a field value")
    if number < 0 or number >= BN254_R:
        raise ValueError("value is outside the BN254 scalar field")
    return number


def sample_hash(value: Union[int, str, bytes]) -> int:
    """A moderation sample as a field value for contentSafetyAttestation.

    An int is taken as the sample's hash (below the field order). A string or
    bytes is the sample itself: the first 248 bits of its SHA-256.
    """
    if isinstance(value, bool):
        raise ValueError("a boolean is not a sample")
    if isinstance(value, int):
        return to_field(value)
    if isinstance(value, str):
        value = value.encode("utf-8")
    if isinstance(value, (bytes, bytearray)):
        return int.from_bytes(hashlib.sha256(bytes(value)).digest(), "big") >> 8
    raise ValueError(f"cannot use {type(value).__name__} as a sample")


_TOML_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TOML_NUMBER = re.compile(r"(0[xX][0-9a-fA-F]+|[0-9]+)")


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if value < 0:
            raise ValueError("circuit inputs are unsigned")
        return f'"{value}"'
    if isinstance(value, str):
        if not _TOML_NUMBER.fullmatch(value):
            raise ValueError(f"not a decimal or 0x number: {value!r}")
        return f'"{value}"'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise ValueError(f"cannot write {type(value).__name__} into Prover.toml")


def render_prover_toml(inputs: Dict[str, Any]) -> str:
    """The Prover.toml nargo reads: one `name = value` line per input.

    Numbers are written as quoted decimal or 0x strings, booleans as true or
    false, arrays as lists. Anything else is refused, so no value can break
    out of its line.
    """
    lines = ["# Written by ZKPAttestationClient for one proof"]
    for key, value in inputs.items():
        if not _TOML_KEY.fullmatch(key):
            raise ValueError(f"not a circuit input name: {key!r}")
        lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


def read_public_values(proof: bytes, names: Sequence[str]) -> Dict[str, int]:
    """The public values a bb 0.82.2 proof carries, by name.

    Layout: a 4-byte big-endian count of 32-byte field elements, then the
    elements: the public inputs in ABI order, then the returned commitment,
    then the proof proper.
    """
    if len(proof) < 4:
        raise ZKPProofGenerationError("proof is too short to carry public values")
    n_fields = int.from_bytes(proof[:4], "big")
    if len(proof) != 4 + 32 * n_fields or n_fields <= len(names):
        raise ZKPProofGenerationError("proof bytes do not have the bb proof layout")
    return {
        name: int.from_bytes(proof[4 + 32 * i: 36 + 32 * i], "big")
        for i, name in enumerate(names)
    }


def _hex32(number: int) -> str:
    return "0x" + format(number, "064x")


def _limit(name: str, value: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > maximum:
        raise ZKPProofGenerationError(f"{name} must be an integer between 0 and {maximum}")
    return value


@dataclass
class ZKPProof:
    """One proof, with what it binds and how to open its commitment."""
    circuit_id: str
    proof_bytes: bytes
    public_inputs: Dict[str, str]          # what the registry is told, as strings, reference_label included
    public_outputs: Dict[str, str]         # the commitment, read from the proof (0x)
    opening: Dict[str, Any] = field(default_factory=dict)   # private figure(s) + salt: keep private

    @property
    def reference_label(self) -> Optional[str]:
        """The label the proof's reference was derived from."""
        return self.public_inputs.get("reference_label")

    @property
    def proof_data(self) -> Dict[str, str]:
        """proof_data as POST /api/v1/attestations/submit takes it."""
        return {"proof_bytes": base64.b64encode(self.proof_bytes).decode("ascii"), "format": "ultra_honk"}


# ─────────────────────────────────────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────────────────────────────────────

class ZKPAttestationClient:
    """
    Self-attestation client for SDK-based agents.

    The client manages:
      1. Circuit file caching (downloads source, Nargo.toml and bytecode once)
      2. Proof generation in a fresh temporary directory per proof
         (nargo execute, then bb prove; non-blocking via an executor)
      3. Attestation submission (POST /api/v1/attestations/submit)
      4. Periodic attestation loop (optional background task)
    """

    def __init__(
        self,
        registry_url: str,
        agent_jwt: str,
        *,
        circuit_base_dir: str = "/var/lib/zkp_circuits",
        bb_binary: str = "/usr/local/bin/bb",
        nargo_binary: str = "/usr/local/bin/nargo",
        request_timeout: int = 30,
        bb_home: Optional[str] = None,
    ) -> None:
        self.registry_url = registry_url.rstrip("/")
        self.agent_jwt = agent_jwt
        self.circuit_base_dir = Path(circuit_base_dir)
        self.bb_binary = bb_binary
        self.nargo_binary = nargo_binary
        self.request_timeout = request_timeout
        # bb reads its reference string from <HOME>/.bb-crs; None keeps this process's HOME.
        self.bb_home = bb_home

        # circuit_id -> resolved circuit directory (set by initialize())
        self._circuit_dirs: Dict[str, Path] = {}
        # circuit_id -> the registry's policy limit, read once from /metadata
        self._policy_limits: Dict[str, int] = {}

        # Background periodic attestation task handles
        self._periodic_tasks: List[asyncio.Task] = []

        self.circuit_base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "ZKPAttestationClient initialized. Registry: %s  Circuit cache: %s",
            self.registry_url,
            self.circuit_base_dir,
        )

    # ── Initialisation ────────────────────────────────────────────────────────

    async def initialize(self, circuit_ids: Optional[List[str]] = None) -> None:
        """
        Download and cache circuit files for the given circuit IDs.

        If circuit_ids is None, initialises ALL known circuits.
        Safe to call multiple times: already-cached circuits are skipped.

        Raises:
            ZKPBinaryNotFoundError: if nargo or bb is missing.
            ZKPCircuitNotAvailableError: if a circuit cannot be downloaded.
        """
        self._verify_binaries()

        if circuit_ids is None:
            circuit_ids = list(_KNOWN_CIRCUITS.keys())

        for cid in circuit_ids:
            if cid in self._circuit_dirs:
                logger.debug("Circuit '%s' already cached, skipping download.", cid)
                continue
            logger.info("Downloading circuit files for '%s' ...", cid)
            circuit_dir = await self._download_circuit(cid)
            self._circuit_dirs[cid] = circuit_dir
            logger.info("Circuit '%s' ready at %s", cid, circuit_dir)

    def _verify_binaries(self) -> None:
        """Raise ZKPBinaryNotFoundError if nargo or bb are not executable."""
        for binary, name in [(self.nargo_binary, "nargo"), (self.bb_binary, "bb")]:
            if not Path(binary).exists():
                raise ZKPBinaryNotFoundError(
                    f"{name} binary not found at '{binary}'. "
                    "Ensure the agent image was built with --enable-zkp."
                )

    @staticmethod
    def _meta(circuit_id: str) -> _CircuitMeta:
        meta = _KNOWN_CIRCUITS.get(circuit_id)
        if meta is None:
            raise ZKPCircuitNotAvailableError(
                f"Unknown circuit_id '{circuit_id}'. Known circuits: {list(_KNOWN_CIRCUITS)}"
            )
        return meta

    # ── Circuit download ──────────────────────────────────────────────────────

    async def _download_circuit(self, circuit_id: str) -> Path:
        """
        Download the bytecode, source and Nargo.toml from the registry into the
        cache. Proofs are made in temporary directories, never in the cache.
        """
        meta = self._meta(circuit_id)

        safe_name = circuit_id.replace("/", "_").replace("\\", "_")
        circuit_dir = self.circuit_base_dir / safe_name
        (circuit_dir / "src").mkdir(parents=True, exist_ok=True)

        loop = asyncio.get_running_loop()
        base = f"{self.registry_url}/api/v1/circuits/{circuit_id}"

        source_text = await loop.run_in_executor(None, self._http_get_text, f"{base}/source")
        nargo_text = await loop.run_in_executor(None, self._http_get_text, f"{base}/nargo-toml")
        acir_bytes = await loop.run_in_executor(None, self._http_get_bytes, f"{base}/acir")
        if f'name = "{meta.nargo_package_name}"' not in nargo_text:
            raise ZKPCircuitNotAvailableError(
                f"Nargo.toml for '{circuit_id}' does not name the package '{meta.nargo_package_name}'"
            )

        (circuit_dir / "src" / "main.nr").write_text(source_text, encoding="utf-8")
        (circuit_dir / "Nargo.toml").write_text(nargo_text, encoding="utf-8")
        (circuit_dir / f"{meta.nargo_package_name}.bin").write_bytes(acir_bytes)
        return circuit_dir

    def _http_get_text(self, url: str) -> str:
        """Synchronous HTTP GET -> text (runs in executor thread)."""
        return self._http_get_bytes(url).decode("utf-8")

    def _http_get_bytes(self, url: str) -> bytes:
        """Synchronous HTTP GET -> bytes (runs in executor thread)."""
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise ZKPCircuitNotAvailableError(f"HTTP {e.code} fetching {url}: {e.reason}") from e
        except Exception as e:
            raise ZKPCircuitNotAvailableError(f"Failed to fetch {url}: {e}") from e

    async def policy_limit(self, circuit_id: str) -> int:
        """This registry's policy limit for a circuit (GET /circuits/{id}/metadata).

        A proof made at this limit is the loosest the registry accepts. Falls
        back to the circuit's shipped default when the metadata cannot be read.
        """
        meta = self._meta(circuit_id)
        if circuit_id in self._policy_limits:
            return self._policy_limits[circuit_id]
        url = f"{self.registry_url}/api/v1/circuits/{circuit_id}/metadata"
        limit = meta.policy_default
        try:
            loop = asyncio.get_running_loop()
            body = json.loads(await loop.run_in_executor(None, self._http_get_text, url))
            limit = int(body["policy_in_force"][meta.policy_key]["limit"])
        except (ZKPCircuitNotAvailableError, ValueError, KeyError, TypeError) as exc:
            logger.warning(
                "Could not read the policy limit for '%s' (%s); using the shipped default %d",
                circuit_id, exc, limit,
            )
        self._policy_limits[circuit_id] = limit
        return limit

    # ── Proof generation ──────────────────────────────────────────────────────

    async def generate_proof(
        self,
        circuit_id: str,
        public_inputs: Dict[str, Any],
        private_inputs: Dict[str, Any],
        *,
        agent_did: str,
        reference_label: Optional[Union[int, str]] = None,
    ) -> ZKPProof:
        """
        Generate a proof for a v2.0.0 circuit, for the agent that will submit it.

        The reference (context, transaction_ref or window_ref) is
        derive_reference(agent_did, reference_label); leave it out of
        public_inputs. reference_label is the offer, transaction or window id
        as given, or a random "sdk-<16 hex>" when None. A missing salt is a
        fresh random value. Steps, in a fresh temporary directory:
          1. Write Prover.toml with the public and private inputs.
          2. `nargo execute witness` writes target/witness.gz.
          3. `bb prove -s ultra_honk` writes the proof.
          4. The public values the proof carries are read back: the inputs
             must be the ones given, and the commitment is handed back.

        Raises:
            ZKPCircuitNotAvailableError: circuit unknown or download failed.
            ZKPProofGenerationError: agent_did is missing, an input is missing,
                a reference is given that is not the derived one, or nargo or bb
                failed (nargo fails when the inputs do not satisfy the circuit).
        """
        meta = self._meta(circuit_id)
        did = _agent_did(agent_did)
        public = dict(public_inputs)
        if "reference_label" in public:
            stated_label = public.pop("reference_label")
            if reference_label is not None and str(reference_label) != str(stated_label):
                raise ZKPProofGenerationError("reference_label is given twice, with two values")
            reference_label = stated_label
        label = label_for(reference_label)
        derived = str(derive_reference(did, label))
        if meta.reference_key in public:
            try:
                stated = to_field(str(public[meta.reference_key]))
            except ValueError:
                stated = None
            if stated != int(derived):
                raise ZKPProofGenerationError(
                    f"'{meta.reference_key}' is derive_reference(agent_did, reference_label): pass the "
                    "offer, transaction or window id as reference_label instead of a reference"
                )
        public[meta.reference_key] = derived
        private = dict(private_inputs)
        private.setdefault("salt", random_salt())
        missing = [k for k in meta.public_input_keys if k not in public]
        missing += [k for k in meta.private_input_keys if k not in private]
        if missing:
            raise ZKPProofGenerationError(f"missing input(s) for '{circuit_id}': {missing}")
        unknown = set(public) - set(meta.public_input_keys)
        unknown |= set(private) - set(meta.private_input_keys)
        if unknown:
            raise ZKPProofGenerationError(f"unknown input(s) for '{circuit_id}': {sorted(unknown)}")
        if circuit_id not in self._circuit_dirs:
            await self.initialize([circuit_id])
        circuit_dir = self._circuit_dirs[circuit_id]
        ordered = {k: public[k] for k in meta.public_input_keys}
        ordered.update({k: private[k] for k in meta.private_input_keys})
        try:
            prover_toml = render_prover_toml(ordered)
        except ValueError as exc:
            raise ZKPProofGenerationError(f"input for '{circuit_id}' cannot be written: {exc}") from exc

        logger.info("Generating proof for circuit '%s' ...", circuit_id)
        loop = asyncio.get_running_loop()
        proof_bytes = await loop.run_in_executor(
            None, self._run_proof_subprocess, circuit_dir, meta, prover_toml
        )

        names = list(meta.public_input_keys) + [meta.output_key]
        carried = read_public_values(proof_bytes, names)
        for key in meta.public_input_keys:
            if carried[key] != to_field(str(public[key])):
                raise ZKPProofGenerationError(
                    f"the proof carries a different '{key}' than the one given; refusing to submit it"
                )
        logger.info("Proof generated for circuit '%s' (%d bytes)", circuit_id, len(proof_bytes))
        stated_inputs = {k: str(public[k]) for k in meta.public_input_keys}
        stated_inputs["reference_label"] = label
        return ZKPProof(
            circuit_id=circuit_id,
            proof_bytes=proof_bytes,
            public_inputs=stated_inputs,
            public_outputs={meta.output_key: _hex32(carried[meta.output_key])},
            opening={k: private[k] for k in meta.private_input_keys},
        )

    def _bb_env(self) -> Dict[str, str]:
        env = dict(os.environ)
        if self.bb_home:
            env["HOME"] = self.bb_home
        return env

    def _run_proof_subprocess(self, circuit_dir: Path, meta: _CircuitMeta, prover_toml: str) -> bytes:
        """
        Synchronous proof pipeline: nargo execute, then bb prove, in a
        temporary directory. Runs in a thread executor.
        """
        bytecode = circuit_dir / f"{meta.nargo_package_name}.bin"
        with tempfile.TemporaryDirectory(prefix="zkp_proof_") as work_dir:
            work = Path(work_dir)
            (work / "src").mkdir()
            shutil.copy(circuit_dir / "Nargo.toml", work / "Nargo.toml")
            shutil.copy(circuit_dir / "src" / "main.nr", work / "src" / "main.nr")
            (work / "Prover.toml").write_text(prover_toml, encoding="utf-8")

            # ── Step 1: nargo execute ─────────────────────────────────────────
            result = subprocess.run(
                [self.nargo_binary, "execute", "witness"],
                cwd=str(work), capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                raise ZKPProofGenerationError(
                    f"nargo execute failed for circuit '{meta.nargo_package_name}' "
                    f"(the inputs do not satisfy it, or nargo is broken).\n"
                    f"stdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
                )
            witness_path = work / "target" / "witness.gz"
            if not witness_path.exists():
                raise ZKPProofGenerationError(
                    f"nargo execute succeeded but the witness is not at {witness_path}"
                )

            # ── Step 2: bb prove ──────────────────────────────────────────────
            proof_out_dir = work / "target" / "proof_out"
            proof_out_dir.mkdir()
            result = subprocess.run(
                [
                    self.bb_binary, "prove", "-s", "ultra_honk",
                    "-b", str(bytecode),
                    "-w", str(witness_path),
                    "-o", str(proof_out_dir),
                ],
                cwd=str(work), capture_output=True, text=True, timeout=300, env=self._bb_env(),
            )
            if result.returncode != 0:
                raise ZKPProofGenerationError(
                    f"bb prove failed for circuit '{meta.nargo_package_name}' (exit {result.returncode}).\n"
                    f"stdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
                )
            proof_file = proof_out_dir / "proof"
            if not proof_file.exists():
                raise ZKPProofGenerationError(
                    f"bb prove succeeded but the proof file is not at {proof_file}"
                )
            return proof_file.read_bytes()

    # ── Submission ────────────────────────────────────────────────────────────

    async def submit_attestation(
        self,
        circuit_id: str,
        proof_bytes: Union[bytes, ZKPProof],
        public_inputs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Submit a proof to POST /api/v1/attestations/submit.

        Takes a ZKPProof (its own public inputs, reference_label included, are
        sent) or the raw proof bytes with every public input by name and the
        reference_label the reference was derived from. The registry verifies
        the proof only for the agent whose DID the reference was derived from.
        Gives back the registry's answer.

        Raises:
            ZKPAttestationError: reference_label is missing for a v2 circuit,
                the registry answered non-2xx (409: the same proof, or the same
                circuit and reference, was already attested), or it did not
                verify the proof (the registry's reason is in the message and
                in `.response`).
        """
        if isinstance(proof_bytes, ZKPProof):
            proof = proof_bytes
            raw = proof.proof_bytes
            stated = dict(proof.public_inputs)
        else:
            raw = proof_bytes
            stated = {k: str(v) for k, v in (public_inputs or {}).items()}
        if circuit_id in _KNOWN_CIRCUITS and not stated.get("reference_label"):
            raise ZKPAttestationError(
                "public_inputs.reference_label is required: the registry derives the proof's reference "
                "from the submitting agent's DID and this label"
            )

        payload = json.dumps({
            "circuit_id": circuit_id,
            "proof_data": {"proof_bytes": base64.b64encode(raw).decode("ascii"), "format": "ultra_honk"},
            "public_inputs": stated,
        }).encode("utf-8")

        url = f"{self.registry_url}/api/v1/attestations/submit"
        loop = asyncio.get_running_loop()
        response_data = await loop.run_in_executor(None, self._http_post_json, url, payload)

        status = response_data.get("status", "unknown")
        if status != "verified":
            reason = response_data.get("reason") or response_data.get("message", "")
            raise ZKPAttestationError(
                f"Attestation not verified by the registry: status={status} reason={reason}",
                response=response_data,
            )

        logger.info(
            "Attestation verified: circuit=%s attestation_id=%s reputation_delta=%s",
            circuit_id,
            response_data.get("attestation_id"),
            response_data.get("reputation_delta"),
        )
        return response_data

    def _http_post_json(self, url: str, payload: bytes) -> Dict[str, Any]:
        """Synchronous POST with JSON body + agent JWT auth (runs in executor)."""
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.agent_jwt}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise ZKPAttestationError(f"HTTP {e.code} submitting attestation: {body}") from e
        except Exception as e:
            raise ZKPAttestationError(f"Network error submitting attestation: {e}") from e

    async def prove_and_submit(
        self,
        circuit_id: str,
        public_inputs: Dict[str, Any],
        private_inputs: Dict[str, Any],
        *,
        agent_did: str,
        reference_label: Optional[Union[int, str]] = None,
    ) -> Dict[str, Any]:
        """Prove, submit, and give back the registry's answer with what the proof binds.

        agent_did is the agent that submits (this client's JWT must be that
        agent's); reference_label as in generate_proof.

        The result is the registry's answer plus:
          circuit_id, public_inputs (as sent),
          commitment: {name: 0x value} read from the proof (and checked against
              the registry's reading when it reports one),
          reference: {name: value}, reference_label: the label it was derived from,
          opening: the private figure(s) and the salt. Keep it private: it is
              what opens the commitment to an auditor.
        """
        proof = await self.generate_proof(
            circuit_id, public_inputs, private_inputs, agent_did=agent_did, reference_label=reference_label,
        )
        response = await self.submit_attestation(circuit_id, proof)
        meta = self._meta(circuit_id)
        reported = (response.get("proof_public_values") or {}).get(meta.output_key)
        ours = proof.public_outputs[meta.output_key]
        if reported is not None and to_field(str(reported)) != to_field(ours):
            raise ZKPAttestationError(
                f"the registry read a different {meta.output_key} than the proof carries",
                response=response,
            )
        result = dict(response)
        result.update(
            circuit_id=circuit_id,
            public_inputs=dict(proof.public_inputs),
            commitment=dict(proof.public_outputs),
            reference={meta.reference_key: proof.public_inputs[meta.reference_key]},
            reference_label=proof.reference_label,
            opening=dict(proof.opening),
        )
        return result

    # ── Convenience methods ───────────────────────────────────────────────────

    async def attest_fair_markup(
        self,
        *,
        agent_did: str,
        total_cost: int,
        offered_price: int,
        context: Union[int, str, None] = None,
        max_markup_bps: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Prove and submit fairMarkupPolicy/v2.0.0: the offered price is at most
        the cost plus the markup cap.

        Args:
            agent_did: The submitting agent's DID (required).
            total_cost: The cost (private; only its commitment leaves the agent).
            offered_price: The price offered (public), same unit as total_cost.
            context: The offer this proof is about, such as "quote-42": the
                reference_label as given (the public context is
                derive_reference(agent_did, context)). Random when omitted.
            max_markup_bps: The cap in basis points (public). Defaults to this
                registry's policy limit, the loosest it accepts.

        Constraint: offered_price * 10000 <= total_cost * (10000 + max_markup_bps).
        Result: as prove_and_submit (commitment: cost_commitment).
        """
        circuit_id = "fairMarkupPolicy/v2.0.0"
        if max_markup_bps is None:
            max_markup_bps = await self.policy_limit(circuit_id)
        _limit("max_markup_bps", max_markup_bps, _U32)
        _limit("total_cost", total_cost, _U64)
        _limit("offered_price", offered_price, _U64)
        if offered_price * 10000 > total_cost * (10000 + max_markup_bps):
            raise ZKPProofGenerationError(
                f"offered_price {offered_price} is above total_cost {total_cost} plus "
                f"{max_markup_bps} bps; no proof exists for these figures"
            )
        return await self.prove_and_submit(
            circuit_id,
            {"max_markup_bps": max_markup_bps, "offered_price": offered_price},
            {"total_cost": total_cost, "salt": random_salt()},
            agent_did=agent_did, reference_label=context,
        )

    async def attest_resource_usage(
        self,
        *,
        agent_did: str,
        reported_units: int,
        logged_units: int,
        transaction_ref: Union[int, str, None] = None,
        max_discrepancy_bps: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Prove and submit accurateResourceUsagePolicy/v2.0.0: the reported units
        are within the tolerance of the meter log.

        Args:
            agent_did: The submitting agent's DID (required).
            reported_units: Units reported to the counterparty (public).
            logged_units: Units in the meter log (private; only its commitment
                leaves the agent).
            transaction_ref: The transaction id: the reference_label as given
                (the public transaction_ref is derive_reference(agent_did,
                transaction_ref)). Random when omitted. A meter that publishes
                a log commitment derives the same reference from the agent DID
                and the transaction id.
            max_discrepancy_bps: Tolerance in basis points (public). Defaults to
                this registry's policy limit.

        Constraint: |reported_units - logged_units| * 10000 <= logged_units * max_discrepancy_bps.
        Result: as prove_and_submit (commitment: log_commitment).
        """
        circuit_id = "accurateResourceUsagePolicy/v2.0.0"
        if max_discrepancy_bps is None:
            max_discrepancy_bps = await self.policy_limit(circuit_id)
        _limit("max_discrepancy_bps", max_discrepancy_bps, _U32)
        _limit("reported_units", reported_units, _U64)
        _limit("logged_units", logged_units, _U64)
        if abs(reported_units - logged_units) * 10000 > logged_units * max_discrepancy_bps:
            raise ZKPProofGenerationError(
                f"reported_units {reported_units} is outside {max_discrepancy_bps} bps of "
                f"logged_units {logged_units}; no proof exists for these figures"
            )
        return await self.prove_and_submit(
            circuit_id,
            {"max_discrepancy_bps": max_discrepancy_bps, "reported_units": reported_units},
            {"logged_units": logged_units, "salt": random_salt()},
            agent_did=agent_did, reference_label=transaction_ref,
        )

    async def attest_cross_registry_fees(
        self,
        *,
        agent_did: str,
        amounts: Sequence[int],
        fees: Sequence[int],
        window_ref: Union[int, str, None] = None,
        max_fee_bps: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Prove and submit fairCrossRegistryFee/v2.0.0 for a batch of up to 16
        transfers: every fee is at most the cap, and the stated totals are the
        sums of the batch.

        Args:
            agent_did: The submitting agent's DID (required).
            amounts, fees: One entry per transfer (private; only the batch
                commitment and the totals leave the agent).
            window_ref: The window and batch id: the reference_label as given
                (the public window_ref is derived from it and agent_did).
                Random when omitted.
            max_fee_bps: Fee cap in basis points (public). Defaults to this
                registry's policy limit.

        bb needs 8,193 reference string points for this circuit.
        Result: as prove_and_submit (commitment: batch_commitment).
        """
        circuit_id = "fairCrossRegistryFee/v2.0.0"
        amounts = list(amounts)
        fees = list(fees)
        if not amounts or len(amounts) != len(fees) or len(amounts) > FEE_BATCH_SLOTS:
            raise ZKPProofGenerationError(
                f"amounts and fees must be the same length, 1 to {FEE_BATCH_SLOTS} transfers"
            )
        if max_fee_bps is None:
            max_fee_bps = await self.policy_limit(circuit_id)
        _limit("max_fee_bps", max_fee_bps, _U32)
        for i, (amount, fee) in enumerate(zip(amounts, fees)):
            _limit(f"amounts[{i}]", amount, _U64)
            _limit(f"fees[{i}]", fee, _U64)
            if fee * 10000 > amount * max_fee_bps:
                raise ZKPProofGenerationError(
                    f"transfer {i}: fee {fee} on {amount} is above {max_fee_bps} bps; no proof exists"
                )
        total_volume, total_fees = sum(amounts), sum(fees)
        _limit("total_volume", total_volume, _U64)
        _limit("total_fees", total_fees, _U64)
        pad = FEE_BATCH_SLOTS - len(amounts)
        return await self.prove_and_submit(
            circuit_id,
            {"max_fee_bps": max_fee_bps, "total_volume": total_volume, "total_fees": total_fees},
            {"amounts": amounts + [0] * pad, "fees": fees + [0] * pad, "salt": random_salt()},
            agent_did=agent_did, reference_label=window_ref,
        )

    async def attest_content_safety(
        self,
        *,
        agent_did: str,
        samples: Sequence[Union[int, str, bytes]],
        rejected: Sequence[bool],
        window_ref: Union[int, str, None] = None,
        min_rejection_bps: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Prove and submit contentSafetyAttestation/v2.0.0 for a window of 1 to 64
        moderated samples: the share the filter rejected is at least the minimum.

        Args:
            agent_did: The submitting agent's DID (required).
            samples: One entry per sample: its hash as a number, or the sample
                (str or bytes, hashed here). Private; only the log commitment
                leaves the agent.
            rejected: Whether the filter rejected each sample (private).
            window_ref: The window id: the reference_label as given (the
                public window_ref is derived from it and agent_did). Random
                when omitted.
            min_rejection_bps: Minimum rejected share in basis points (public).
                Defaults to this registry's policy limit.

        The proof binds the agent to the log it committed to. It does not show
        that the log is true or which model made the decisions.
        bb needs 8,193 reference string points for this circuit.
        Result: as prove_and_submit (commitment: log_commitment).
        """
        circuit_id = "contentSafetyAttestation/v2.0.0"
        hashes = [sample_hash(s) for s in samples]
        flags = [bool(r) for r in rejected]
        if not hashes or len(hashes) != len(flags) or len(hashes) > SAFETY_LOG_SLOTS:
            raise ZKPProofGenerationError(
                f"samples and rejected must be the same length, 1 to {SAFETY_LOG_SLOTS} samples"
            )
        if any(h == 0 for h in hashes):
            raise ZKPProofGenerationError("a sample hash must be non-zero")
        if min_rejection_bps is None:
            min_rejection_bps = await self.policy_limit(circuit_id)
        _limit("min_rejection_bps", min_rejection_bps, _U32)
        if sum(flags) * 10000 < len(flags) * min_rejection_bps:
            raise ZKPProofGenerationError(
                f"{sum(flags)} of {len(flags)} rejected is below {min_rejection_bps} bps; no proof exists"
            )
        pad = SAFETY_LOG_SLOTS - len(hashes)
        return await self.prove_and_submit(
            circuit_id,
            {"min_rejection_bps": min_rejection_bps, "total_samples": len(hashes)},
            {"sample_hashes": [str(h) for h in hashes] + ["0"] * pad,
             "rejected": flags + [False] * pad, "salt": random_salt()},
            agent_did=agent_did, reference_label=window_ref,
        )

    # ── Periodic attestation ──────────────────────────────────────────────────

    def start_periodic_attestation(
        self,
        interval_seconds: float,
        get_inputs_fn: Callable[[], Awaitable[Optional[Dict[str, Any]]]],
        circuit_id: str = "fairMarkupPolicy/v2.0.0",
        *,
        agent_did: str,
    ) -> asyncio.Task:
        """
        Start a background task that periodically proves and submits attestations.

        Args:
            interval_seconds: How often to attest (from registry enforcement policy).
            get_inputs_fn: Async callable returning {"public_inputs": {...}, "private_inputs": {...}}
                           and optionally "reference_label" (the window id), or None
                           to skip this cycle (e.g., no recent transactions).
                           The salt and the label may be left out: each cycle gets
                           a fresh random salt and label. The reference is always
                           derived from agent_did and the label.
            circuit_id: Which v2.0.0 circuit to use for periodic attestation.
            agent_did: The submitting agent's DID (required).

        Result:
            The asyncio.Task handle (call task.cancel() to stop).
        """
        self._meta(circuit_id)
        _agent_did(agent_did)

        async def _loop():
            logger.info(
                "Periodic attestation started: circuit=%s interval=%ds",
                circuit_id, interval_seconds,
            )
            while True:
                await asyncio.sleep(interval_seconds)
                try:
                    inputs = await get_inputs_fn()
                    if inputs is None:
                        logger.debug("Periodic attestation: get_inputs_fn returned None, skipping cycle.")
                        continue
                    result = await self.prove_and_submit(
                        circuit_id,
                        inputs["public_inputs"],
                        inputs["private_inputs"],
                        agent_did=agent_did,
                        reference_label=inputs.get("reference_label"),
                    )
                    logger.info("Periodic attestation submitted: %s", result.get("attestation_id"))
                except asyncio.CancelledError:
                    logger.info("Periodic attestation task cancelled.")
                    raise
                except Exception as exc:
                    logger.error("Periodic attestation cycle failed: %s", exc, exc_info=True)
                    # Continue running: a single failure must not stop the loop

        task = asyncio.create_task(_loop())
        self._periodic_tasks.append(task)
        return task

    async def shutdown(self) -> None:
        """Cancel all running periodic attestation tasks."""
        for task in self._periodic_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._periodic_tasks.clear()
        logger.info("ZKPAttestationClient shut down.")
