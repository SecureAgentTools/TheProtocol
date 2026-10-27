#!/usr/bin/env python3
"""
ZKP Trade Simulation Script — TheProtocol
==========================================
Simulates bilateral AVT transfers between Ramon and Percival (Registry A)
and generates real Zero-Knowledge Proofs attesting to fair pricing and
accurate resource reporting after each transfer leg.

Run INSIDE the registry-a container:
    docker exec -it agentvault_registry_a python /app/scripts/zkp_trade_simulation.py

Custom parameters:
    docker exec -it agentvault_registry_a python /app/scripts/zkp_trade_simulation.py \\
        --rounds 5 --amount 120 --registry http://localhost:8000

Agents (Registry A — already onboarded):
    Ramon:    did:cos:2758536e-c73e-bba3-4c96  /  agent-cd7dc78cd97fb7aa
    Percival: did:cos:c34f2070-4c1d-05bf-54c9  /  agent-90663061387409b6

Prerequisites (registry-a must be running):
    Both agents must have sufficient liquid balance.
    Verify with: GET /api/v1/teg/balance (agent JWT)

What this script proves (v2.0.0 circuits):
    For each transfer leg (A→B and B→A):
      1. fairMarkupPolicy/v2.0.0
         - Public:  max_markup_bps (3000, checked against the registry policy),
                    offered_price, context (derived from the sending agent's DID and the transfer)
         - Private: total_cost, salt; the proof outputs cost_commitment
         - Proves the price is at most the committed cost plus the cap
      2. accurateResourceUsagePolicy/v2.0.0
         - Public:  max_discrepancy_bps (100), transaction_ref, reported_units
         - Private: logged_units, salt; the proof outputs log_commitment
         - Proves the reported units are within 1% of the committed log
    The proofs bind the private figures to commitments; they do not show the
    figures are true (here they are simulated).

ZKP input derivation from real transaction data:
    offered_price     = transfer_amount          (public, from the transfer record)
    total_cost        = transfer_amount * 5 // 6 (private, a 20% markup)
    Constraint: offered_price * 10000 <= total_cost * (10000 + max_markup_bps)

    reported_units    = transfer_amount          (public)
    logged_units      = transfer_amount          (private, exact match)
    context, transaction_ref = derive_reference(<sending agent DID>, label)   (public)
        label "offer:<transaction id>" or "tx:<transaction id>", sent as
        public_inputs["reference_label"]; the registry derives the same value
        from the submitting agent's DID and refuses a proof made for another.
    Every proof gets a random salt. Proofs are made in a temporary directory.
"""

import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_REGISTRY_URL = "http://localhost:8000"
DEFAULT_ROUNDS       = 3
DEFAULT_AMOUNT       = 120   # divisible by 6 — required for 20% markup math

MAX_MARKUP_BPS       = 3000  # markup cap, basis points (the shipped policy allows at most 3000)
MAX_DISCREPANCY_BPS  = 100   # resource usage tolerance, basis points (policy: at most 100)

BB_BINARY    = os.environ.get("BB_BINARY",    "/usr/local/bin/bb")
NARGO_BINARY = os.environ.get("NARGO_BINARY", "/usr/local/bin/nargo")

# Production agents on Registry A
AGENT_RAMON = {
    "label":         "Ramon",
    "did":           os.environ.get("RAMON_DID",    "did:cos:2758536e-c73e-bba3-4c96"),
    "client_id":     os.environ.get("RAMON_ID",     "agent-cd7dc78cd97fb7aa"),
    "client_secret": os.environ.get("RAMON_SECRET", "cos_secret_8c4a05f409bfadd256309310368ee271917c8d89ca87b905fc52ff3ccfe840a6"),
}

AGENT_PERCIVAL = {
    "label":         "Percival",
    "did":           os.environ.get("PERCIVAL_DID",    "did:cos:c34f2070-4c1d-05bf-54c9"),
    "client_id":     os.environ.get("PERCIVAL_ID",     "agent-90663061387409b6"),
    "client_secret": os.environ.get("PERCIVAL_SECRET", "cos_secret_fa4c39ea6778a1d5190685c692a47df6948d0f8880185ab1f43a85e5ef8960ca"),
}

# Circuit registry (inside the registry container; CIRCUIT_REGISTRY_PATH overrides)
CIRCUIT_REGISTRY = Path(os.environ.get("CIRCUIT_REGISTRY_PATH", "/app/agentvault_circuit_registry")) / "policies"

CIRCUITS: Dict[str, Dict] = {
    "fairMarkupPolicy/v2.0.0": {
        "dir":  CIRCUIT_REGISTRY / "fairMarkupPolicy"           / "v2.0.0",
        "name": "fair_markup",
    },
    "accurateResourceUsagePolicy/v2.0.0": {
        "dir":  CIRCUIT_REGISTRY / "accurateResourceUsagePolicy" / "v2.0.0",
        "name": "accurate_resource_usage",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# HTTP helpers (stdlib — no external deps)
# ─────────────────────────────────────────────────────────────────────────────

def http_post_json(url: str, data: Dict, headers: Dict = {}) -> Dict:
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json", **headers
    }, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_form(url: str, form_data: str) -> Dict:
    payload = form_data.encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/x-www-form-urlencoded"
    }, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_get(url: str, headers: Dict = {}) -> Dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# Authentication (FLOW 4 — agent JWT via grant_type=password)
# ─────────────────────────────────────────────────────────────────────────────

def get_agent_jwt(registry_url: str, agent: Dict) -> str:
    data = (
        f"grant_type=password"
        f"&username={agent['client_id']}"
        f"&password={agent['client_secret']}"
    )
    resp = http_post_form(f"{registry_url}/api/v1/auth/agent/token", data)
    return resp["access_token"]


def get_agent_info(registry_url: str, agent_did: str, dev_jwt: str) -> Optional[Dict]:
    """Fetch agent info including reputation_score and liquid_balance via by-did endpoint."""
    try:
        return http_get(
            f"{registry_url}/api/v1/agents/by-did/{agent_did}",
            headers={"Authorization": f"Bearer {dev_jwt}"}
        )
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Transfer (FLOW 5)
# ─────────────────────────────────────────────────────────────────────────────

def execute_transfer(
    registry_url: str,
    sender_jwt: str,
    receiver_did: str,
    amount: int,
    message: str,
) -> Dict:
    return http_post_json(
        f"{registry_url}/api/v1/teg/transfer",
        data={"receiver_agent_id": receiver_did, "amount": str(amount), "message": message},
        headers={"Authorization": f"Bearer {sender_jwt}"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# ZKP input derivation from real transaction data (v2.0.0 circuits)
# ─────────────────────────────────────────────────────────────────────────────

def derive_reference(agent_did: str, label: str) -> str:
    """The reference the registry requires (core/zkp_verifier.derive_reference): the
    first 31 bytes of SHA-256("tp.attestation.ref.v1|" + agent DID + "|" + label)."""
    digest = hashlib.sha256(b"tp.attestation.ref.v1|" + agent_did.encode() + b"|" + label.encode()).digest()
    return str(int.from_bytes(digest[:31], "big"))


def derive_fair_markup_inputs(amount: int, tx_id_str: str, agent_did: str) -> Tuple[Dict, Dict]:
    """
    fairMarkupPolicy/v2.0.0 inputs from the actual transfer amount.

    Pricing model: the agent charges 20% above its cost.
      offered_price = amount                (public)
      total_cost    = amount * 5 // 6       (private: only its commitment is published)
      context       = derive_reference(agent_did, "offer:<tx id>")  (public, names the offer and the agent)
      max_markup_bps = MAX_MARKUP_BPS       (public, checked against the registry policy)

    Constraint: offered_price * 10000 <= total_cost * (10000 + max_markup_bps).
    """
    costs = amount * 5 // 6
    if amount * 10000 > costs * (10000 + MAX_MARKUP_BPS):
        raise ValueError(f"amount={amount} is above cost {costs} plus {MAX_MARKUP_BPS} bps")
    public = {
        "max_markup_bps": MAX_MARKUP_BPS,
        "offered_price":  amount,
        "context":        derive_reference(agent_did, f"offer:{tx_id_str}"),
        "reference_label": f"offer:{tx_id_str}",
    }
    private = {
        "total_cost": costs,
        "salt":       hex(secrets.randbits(248)),
    }
    return public, private


def derive_resource_usage_inputs(amount: int, tx_id_str: str, agent_did: str) -> Tuple[Dict, Dict]:
    """
    accurateResourceUsagePolicy/v2.0.0 inputs from the transfer.

    Resource model: resource_units == transfer_amount (exact 1:1 reporting).
    transaction_ref = derive_reference(agent_did, "tx:<tx id>") (public); the
    logged units stay private behind the log commitment.
    """
    public = {
        "max_discrepancy_bps": MAX_DISCREPANCY_BPS,
        "transaction_ref":     derive_reference(agent_did, f"tx:{tx_id_str}"),
        "reported_units":      amount,
        "reference_label":     f"tx:{tx_id_str}",
    }
    private = {
        "logged_units": amount,
        "salt":         hex(secrets.randbits(248)),
    }
    return public, private


# ─────────────────────────────────────────────────────────────────────────────
# ZKP proof generation: nargo execute, then bb prove, in a temporary directory
# (the circuit registry is never written to)
# ─────────────────────────────────────────────────────────────────────────────

def write_prover_toml(work_dir: Path, inputs: Dict) -> None:
    lines = ["# Generated for one proof"]
    for key, val in inputs.items():
        lines.append(f'{key} = "{val}"')
    (work_dir / "Prover.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(cmd: List[str], cwd: Path, what: str) -> None:
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"{what} failed:\n"
            f"STDOUT: {result.stdout[-2000:]}\n"
            f"STDERR: {result.stderr[-2000:]}"
        )


def generate_proof(
    circuit_id: str,
    public_inputs: Dict,
    private_inputs: Dict,
) -> Tuple[bytes, str]:
    """Prove in a fresh temporary directory; give back the proof bytes and the commitment it carries (0x)."""
    circuit = CIRCUITS[circuit_id]
    source = circuit["dir"]
    with tempfile.TemporaryDirectory(prefix="zkp_sim_") as tmp:
        work = Path(tmp)
        (work / "src").mkdir()
        shutil.copy(source / "Nargo.toml", work / "Nargo.toml")
        shutil.copy(source / "src" / "main.nr", work / "src" / "main.nr")
        circuit_inputs = {k: v for k, v in public_inputs.items() if k != "reference_label"}
        write_prover_toml(work, {**circuit_inputs, **private_inputs})
        _run([NARGO_BINARY, "execute", "witness"], work, "nargo execute")
        artifact = json.loads((source / "circuit.json").read_text())
        bytecode = work / f"{circuit['name']}.bin"
        bytecode.write_bytes(base64.b64decode(artifact["bytecode"]))
        out_dir = work / "proof_out"
        out_dir.mkdir()
        _run([BB_BINARY, "prove", "-s", "ultra_honk", "-b", str(bytecode),
              "-w", str(work / "target" / "witness.gz"), "-o", str(out_dir)], work, "bb prove")
        proof = (out_dir / "proof").read_bytes()
    # A bb 0.82.2 proof carries a 4-byte field count, the public inputs in ABI
    # order, then the commitment the circuit outputs.
    n_public = len([k for k in public_inputs if k != "reference_label"])
    if len(proof) < 4 + 32 * (n_public + 1):
        raise RuntimeError("proof is too short to carry its public values")
    commitment = proof[4 + 32 * n_public: 36 + 32 * n_public].hex()
    return proof, "0x" + commitment


# ─────────────────────────────────────────────────────────────────────────────
# Attestation submission
# ─────────────────────────────────────────────────────────────────────────────

def submit_attestation(
    registry_url: str,
    agent_jwt: str,
    circuit_id: str,
    proof_bytes: bytes,
    public_inputs: Dict,
) -> Dict:
    return http_post_json(
        f"{registry_url}/api/v1/attestations/submit",
        data={
            "circuit_id":    circuit_id,
            "proof_data":    {"proof_bytes": base64.b64encode(proof_bytes).decode("ascii"),
                              "format": "ultra_honk"},
            "public_inputs": {k: str(v) for k, v in public_inputs.items()},
        },
        headers={"Authorization": f"Bearer {agent_jwt}"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Single-agent attestation pair (both circuits, event-driven after transfer)
# ─────────────────────────────────────────────────────────────────────────────

def attest_agent(
    registry_url: str,
    agent: Dict,
    agent_jwt: str,
    transfer_amount: int,
    tx_id: str,
) -> Dict[str, Any]:
    label   = agent["label"]
    results = {}

    for circuit_id, derive_fn in [
        ("fairMarkupPolicy/v2.0.0",           lambda: derive_fair_markup_inputs(transfer_amount, tx_id, agent["did"])),
        ("accurateResourceUsagePolicy/v2.0.0", lambda: derive_resource_usage_inputs(transfer_amount, tx_id, agent["did"])),
    ]:
        short_name = circuit_id.split("/")[0]

        print(f"    [{label}] {short_name}: generating proof ...", end=" ", flush=True)
        t0 = time.time()
        pub, priv = derive_fn()
        try:
            proof_bytes, commitment = generate_proof(circuit_id, pub, priv)
        except Exception as e:
            print(f"FAILED\n      ERROR: {e}")
            results[short_name] = {"status": "proof_failed", "error": str(e)}
            continue
        gen_ms = int((time.time() - t0) * 1000)

        print(f"done ({gen_ms}ms, {len(proof_bytes)}B) → submitting ...", end=" ", flush=True)
        t0 = time.time()
        try:
            resp = submit_attestation(registry_url, agent_jwt, circuit_id, proof_bytes, pub)
        except Exception as e:
            print(f"SUBMIT FAILED\n      ERROR: {e}")
            results[short_name] = {"status": "submit_failed", "error": str(e)}
            continue
        sub_ms = int((time.time() - t0) * 1000)

        status     = resp.get("status", "?")
        attest_id  = resp.get("attestation_id") or "?"
        rep_delta  = resp.get("reputation_delta")
        id_short   = attest_id[:8] if attest_id != "?" else "?"
        print(
            f"[{status}]  "
            f"id={id_short}...  "
            f"rep_delta={rep_delta}  ({sub_ms}ms)"
        )
        if resp.get("status") != "verified" and resp.get("reason"):
            print(f"      reason: {resp['reason']}")
        resp["commitment"] = commitment
        results[short_name] = resp

    return results


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="ZKP Trade Simulation: bilateral transfers + real ZKP attestations"
    )
    p.add_argument("--rounds",   type=int,   default=DEFAULT_ROUNDS,
                   help=f"Trade rounds (Ramon→Percival + Percival→Ramon each). Default: {DEFAULT_ROUNDS}")
    p.add_argument("--amount",   type=int,   default=DEFAULT_AMOUNT,
                   help=f"AVT per transfer leg. Must be divisible by 6. Default: {DEFAULT_AMOUNT}")
    p.add_argument("--registry", type=str,   default=DEFAULT_REGISTRY_URL,
                   help=f"Registry URL. Default: {DEFAULT_REGISTRY_URL}")
    p.add_argument("--skip-zkp", action="store_true",
                   help="Skip ZKP generation — transfers only (fast smoke test)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.amount % 6 != 0:
        lo = (args.amount // 6) * 6
        hi = lo + 6
        print(f"ERROR: --amount must be divisible by 6. Got {args.amount}. Try {lo} or {hi}.")
        sys.exit(1)

    zkp_enabled = not args.skip_zkp

    print("=" * 70)
    print(" ZKP Trade Simulation — TheProtocol")
    print("=" * 70)
    print(f"  Registry : {args.registry}")
    print(f"  Rounds   : {args.rounds}  ({args.rounds * 2} total legs)")
    print(f"  Amount   : {args.amount} AVT per leg")
    print(f"  ZKP      : {'ENABLED (event-driven after each leg)' if zkp_enabled else 'DISABLED'}")
    print(f"  Agent A  : {AGENT_RAMON['label']}    {AGENT_RAMON['did']}")
    print(f"  Agent B  : {AGENT_PERCIVAL['label']} {AGENT_PERCIVAL['did']}")
    print()

    # ── Pre-flight checks ─────────────────────────────────────────────────────
    if zkp_enabled:
        for binary, name in [(NARGO_BINARY, "nargo"), (BB_BINARY, "bb")]:
            if not Path(binary).exists():
                print(f"ERROR: {name} not found at '{binary}'. Must run inside registry-a container.")
                sys.exit(1)
        for cid, c in CIRCUITS.items():
            artifact = c["dir"] / "circuit.json"
            if not artifact.exists():
                print(f"ERROR: compiled circuit missing for {cid}: {artifact}")
                print("       The v2.0.0 circuits ship their circuit.json; check CIRCUIT_REGISTRY_PATH.")
                sys.exit(1)
        print("Pre-flight: nargo OK, bb OK, compiled circuits present\n")

    # ── Authenticate ──────────────────────────────────────────────────────────
    print("Authenticating ...")
    try:
        jwt_r = get_agent_jwt(args.registry, AGENT_RAMON)
        jwt_p = get_agent_jwt(args.registry, AGENT_PERCIVAL)
        print(f"  Ramon    JWT: {jwt_r[:24]}...")
        print(f"  Percival JWT: {jwt_p[:24]}...")
    except Exception as e:
        print(f"ERROR: Authentication failed: {e}")
        print("Ensure both agents are funded and registry-a is running.")
        sys.exit(1)

    # ── Dev JWT for agent info queries (by-did endpoint needs dev auth) ──────
    dev_jwt = None
    try:
        dev_resp = http_post_form(
            f"{args.registry}/api/v1/auth/login",
            f"username=commander@theprotocol.cloud&password={os.environ.get('TP_ADMIN_PASSWORD', '')}"
        )
        dev_jwt = dev_resp.get("access_token")
    except Exception:
        pass  # non-fatal — balance/rep display will show ?

    # ── Initial balances + reputation ─────────────────────────────────────────
    info_r_start = get_agent_info(args.registry, AGENT_RAMON["did"], dev_jwt) if dev_jwt else None
    info_p_start = get_agent_info(args.registry, AGENT_PERCIVAL["did"], dev_jwt) if dev_jwt else None
    liquid_r = info_r_start.get("liquid_balance") if info_r_start else "?"
    liquid_p = info_p_start.get("liquid_balance") if info_p_start else "?"
    rep_r_start = info_r_start.get("reputation_score") if info_r_start else "?"
    rep_p_start = info_p_start.get("reputation_score") if info_p_start else "?"
    print(f"\nStarting balances:   Ramon={liquid_r} AVT  Percival={liquid_p} AVT")
    print(f"Starting reputation: Ramon={rep_r_start}  Percival={rep_p_start}\n")

    # ── Stats tracking ────────────────────────────────────────────────────────
    total_transfers   = 0
    total_proofs      = 0
    total_verified    = 0
    total_rep_delta_r = 0
    total_rep_delta_p = 0
    start_wall        = time.time()

    # ── Trade loop ────────────────────────────────────────────────────────────
    for rnd in range(1, args.rounds + 1):
        print(f"{'─' * 70}")
        print(f" Round {rnd}/{args.rounds}")
        print(f"{'─' * 70}")

        for sender, sender_jwt, receiver, receiver_jwt, rep_tracker in [
            (AGENT_RAMON,    jwt_r, AGENT_PERCIVAL, jwt_p, "r"),
            (AGENT_PERCIVAL, jwt_p, AGENT_RAMON,    jwt_r, "p"),
        ]:
            print(f"\n  {sender['label']} → {receiver['label']}  ({args.amount} AVT)")

            # Transfer
            t0 = time.time()
            try:
                tx_resp = execute_transfer(
                    args.registry,
                    sender_jwt,
                    receiver["did"],
                    args.amount,
                    f"ZKP sim round {rnd}",
                )
                tx_id = tx_resp.get("transaction_id", f"sim-{rnd}-{sender['label']}")
                tx_ms = int((time.time() - t0) * 1000)
                total_transfers += 1
                print(f"  Transfer OK: tx_id={tx_id}  ({tx_ms}ms)")
            except Exception as e:
                print(f"  Transfer FAILED: {e}")
                print("  → Skipping ZKP for this leg.")
                continue

            # ZKP attestation (event-driven — fires immediately after transfer)
            if zkp_enabled:
                attest_results = attest_agent(
                    args.registry,
                    sender,
                    sender_jwt,
                    args.amount,
                    tx_id,
                )
                for circuit_short, resp in attest_results.items():
                    total_proofs += 1
                    if resp.get("status") == "verified":
                        total_verified += 1
                        delta = resp.get("reputation_delta") or 0
                        if rep_tracker == "r":
                            total_rep_delta_r += delta
                        else:
                            total_rep_delta_p += delta

        print()

    # ── Final balances ────────────────────────────────────────────────────────
    elapsed = time.time() - start_wall
    info_r_end = get_agent_info(args.registry, AGENT_RAMON["did"], dev_jwt) if dev_jwt else None
    info_p_end = get_agent_info(args.registry, AGENT_PERCIVAL["did"], dev_jwt) if dev_jwt else None
    liquid_r_end = info_r_end.get("liquid_balance") if info_r_end else "?"
    liquid_p_end = info_p_end.get("liquid_balance") if info_p_end else "?"
    rep_r_end = info_r_end.get("reputation_score") if info_r_end else "?"
    rep_p_end = info_p_end.get("reputation_score") if info_p_end else "?"

    print("=" * 70)
    print(" SIMULATION COMPLETE")
    print("=" * 70)
    print(f"  Elapsed:          {elapsed:.1f}s")
    print(f"  Transfers:        {total_transfers}")
    if zkp_enabled:
        print(f"  Proofs generated: {total_proofs}")
        print(f"  Proofs verified:  {total_verified}/{total_proofs}")
    print()
    print(f"  Ramon    balance:    {liquid_r} → {liquid_r_end} AVT")
    print(f"  Percival balance:    {liquid_p} → {liquid_p_end} AVT")
    if zkp_enabled:
        print(f"  Ramon    rep delta: +{total_rep_delta_r}")
        print(f"  Percival rep delta: +{total_rep_delta_p}")
        print(f"  Ramon    rep:       {rep_r_start} → {rep_r_end}")
        print(f"  Percival rep:       {rep_p_start} → {rep_p_end}")
    print("=" * 70)

    if zkp_enabled and total_verified < total_proofs:
        sys.exit(1)


if __name__ == "__main__":
    main()
