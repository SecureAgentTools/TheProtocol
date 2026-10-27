"""
Tutorial execution proxy — routes tutorial API calls to the sandbox stack.
Lightweight alternative to admin_api_test.py (which is 4,200+ lines of test infrastructure).
This endpoint is a clean passthrough: no FORCE handlers, no DYNAMIC_VALUES, no prereqs.

Endpoints:
  POST /admin/tutorial/execute        — Execute a single API call against sandbox
  POST /admin/tutorial/generate-proof  — Generate a real ZKP proof (nargo+bb), v2.0.0 circuits
  GET  /admin/tutorial/health          — Quick sandbox health check

Auth: developer JWT (intentional — dev-self-service for /tutorials hub).
The `/admin/tutorial` prefix is a cosmetic legacy misnomer — these are
NOT admin-only endpoints. Every authenticated developer needs them to
run the API tutorial flows. DO NOT add `require_admin_flag` here.
Tracking (RBAC §65, 2026-05-08): rename prefix to `/tutorial/*` in a
future PR — would require sweeping 6+ frontend call sites in
`views/Tutorials/services/tutorialApiService.ts`,
`views/Tutorials/data/{agentLifecycle,attestationsCompliance}.track.ts`,
and `assets/docs/oracle/10_zkp_attestation.md`. Deferred until those can
ship together to avoid in-flight tutorial-session breakage.
"""
from fastapi import APIRouter, Depends, Body, HTTPException, Security
from typing import Optional, Any, Dict
from agentvault_registry.core import zkp_verifier as _zkp
import httpx
import os
import time
import logging
import asyncio
import base64
import tempfile
import shutil
import json
import secrets
from agentvault_registry.security import get_current_developer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/tutorial")  # §pass56 PR-5: tags via main.py "Tutorial"

# Same env var as API Tester — routes to sandbox registry.
# §MCPTEST30 (2026-10-01): no literal default. "http://registry-test:8000" named Frame A's old sandbox, which no cloud
# operator has (both sandbox operators: unset, and the name does not resolve there): every tutorial call on an operator
# died on a connect error and answered 200 with status_code 0. Unset now means this registry has no tutorial sandbox,
# and the routes say so.
SANDBOX_URL = (os.environ.get("API_TEST_TARGET_URL") or "").rstrip("/")
NO_SANDBOX = ("No tutorial sandbox is configured on this registry (API_TEST_TARGET_URL is unset); the Tutorials run "
              "on a frame that has one")

# Endpoints requiring form-urlencoded instead of JSON
FORM_ENDPOINTS = {"/auth/login", "/auth/agent/token"}


@router.post("/execute")
async def execute_tutorial_call(
    request: dict = Body(...),
    developer=Security(get_current_developer),
):
    """
    Execute a single API call against the sandbox stack.

    Body:
      method: str          — HTTP method (GET, POST, PUT, DELETE)
      path: str            — API path (e.g. "/onboard/bootstrap/request-token")
      body: dict|null      — Request body (null for GET/DELETE)
      auth_token: str|null — Bearer/Bootstrap token to forward
      auth_type: str       — "developer"|"agent"|"bootstrap"|"admin"|"none"

    Returns:
      status_code: int
      response: any        — Parsed JSON response body
      response_time: float — Milliseconds
      error: str|null
    """
    if not SANDBOX_URL:
        raise HTTPException(status_code=503, detail=NO_SANDBOX)
    method = request.get("method", "GET").upper()
    path = request.get("path", "")
    body = request.get("body")
    auth_token = request.get("auth_token")
    auth_type = request.get("auth_type", "none")

    url = f"{SANDBOX_URL}/api/v1{path}"
    headers = {"Content-Type": "application/json"}

    # Set auth header based on type
    if auth_type in ("developer", "agent", "admin") and auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    elif auth_type == "bootstrap" and auth_token:
        headers["Bootstrap-Token"] = auth_token

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers)
            elif method == "DELETE":
                resp = await client.delete(url, headers=headers)
            elif path in FORM_ENDPOINTS:
                # Form-urlencoded for auth endpoints
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                resp = await client.post(url, data=body or {}, headers=headers)
            elif method == "POST":
                resp = await client.post(url, json=body, headers=headers)
            elif method == "PUT":
                resp = await client.put(url, json=body, headers=headers)
            elif method == "PATCH":
                resp = await client.patch(url, json=body, headers=headers)
            else:
                return {
                    "status_code": 0,
                    "response": None,
                    "response_time": 0,
                    "error": f"Unsupported method: {method}",
                }

        elapsed = (time.time() - start) * 1000
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = resp.text

        return {
            "status_code": resp.status_code,
            "response": resp_json,
            "response_time": round(elapsed, 1),
            "error": None,
        }
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        logger.error(f"Tutorial proxy error: {e}")
        return {
            "status_code": 0,
            "response": None,
            "response_time": round(elapsed, 1),
            "error": str(e),
        }


# ── ZKP Proof Generation for Tutorials ──────────────────────────────────
# v2.0.0 circuits, proven in a fresh temporary directory per request: the
# shared circuit registry is never written to. Every proof gets a random salt
# and reference, so two tutorial runs never produce the same proof (the
# registry accepts each proof once, routers/attestations.py).

# Proving is CPU work and any developer may ask: at most two at a time.
_TUTORIAL_PROVERS = asyncio.Semaphore(2)

TUTORIAL_CIRCUITS: Dict[str, Dict[str, Any]] = {
    "fairMarkupPolicy/v2.0.0": {
        "package": "fair_markup",
        # 20% markup on a cost of 600, under a 20% cap (the policy default is 30%).
        "public": {"max_markup_bps": "2000", "offered_price": "720"},
        "reference": "context",
        "private": {"total_cost": "600"},
    },
    "accurateResourceUsagePolicy/v2.0.0": {
        "package": "accurate_resource_usage",
        # 1,000 units reported against 1,000 logged, 1% tolerance.
        "public": {"max_discrepancy_bps": "100", "reported_units": "1000"},
        "reference": "transaction_ref",
        "private": {"logged_units": "1000"},
    },
    "fairCrossRegistryFee/v2.0.0": {
        "package": "fair_cross_registry_fee",
        # Two transfers at 0.5%, under the 0.5% cap.
        "public": {"max_fee_bps": "50", "total_volume": "30000", "total_fees": "150"},
        "reference": "window_ref",
        "private": {"amounts": ["10000", "20000"] + ["0"] * 14, "fees": ["50", "100"] + ["0"] * 14},
    },
    "contentSafetyAttestation/v2.0.0": {
        "package": "content_safety_attestation",
        # 9 of 10 samples rejected, at the 90% minimum.
        "public": {"min_rejection_bps": "9000", "total_samples": "10"},
        "reference": "window_ref",
        "private": {
            "sample_hashes": [str(i) for i in range(1, 11)] + ["0"] * 54,
            "rejected": [True] * 9 + [False] * 55,
        },
    },
}

# v1.0.0 ids still asked for by older clients: they get the v2.0.0 proof.
_TUTORIAL_ALIASES = {
    "fairMarkupPolicy/v1.0.0": "fairMarkupPolicy/v2.0.0",
    "accurateResourceUsagePolicy/v1.0.0": "accurateResourceUsagePolicy/v2.0.0",
}


def _toml_value(value: Any) -> str:
    """A Prover.toml value: strings quoted, booleans bare, lists as arrays."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return f'"{value}"'


async def _run(cmd: list, cwd: str, env: Dict[str, str], timeout: int, what: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    finally:
        # A timeout or a cancelled request must not leave nargo or bb running
        # after the semaphore is released and the directory removed.
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    if proc.returncode != 0:
        logger.error(f"[Tutorial ZKP] {what} failed: {stderr.decode(errors='replace')[:500]}")
        raise HTTPException(500, f"{what} failed: {stderr.decode(errors='replace')[:500]}")


@router.post("/generate-proof")
async def generate_zkp_proof(
    request: dict = Body(...),
    developer=Security(get_current_developer),
):
    """
    Generate a real UltraHonk proof for a tutorial circuit.

    Body:
      circuit_id: str  — one of the four v2.0.0 policy circuits (TUTORIAL_CIRCUITS);
                         the v1.0.0 ids are answered with the v2.0.0 proof
      agent_did: str   — the agent that will submit the proof: its reference is
                         derive_reference(agent_did, reference_label), and
                         /attestations/submit refuses it from any other agent

    Returns:
      circuit_id: str
      proof_bytes_base64: str  — base64 of the proof (submit to /attestations/submit)
      public_inputs: dict      — the public inputs and reference_label, as /attestations/submit takes them
      public_outputs: dict     — the commitment the circuit returns
      generation_time_ms: float
    """
    requested = request.get("circuit_id", "")
    circuit_id = _TUTORIAL_ALIASES.get(requested, requested)
    if circuit_id not in TUTORIAL_CIRCUITS:
        raise HTTPException(400, f"Unknown circuit: {requested}. Available: {list(TUTORIAL_CIRCUITS.keys())}")
    agent_did = request.get("agent_did")
    if not isinstance(agent_did, str) or not agent_did.startswith("did:"):
        raise HTTPException(400, "agent_did is required: the proof's reference names the agent that will submit it")

    spec = TUTORIAL_CIRCUITS[circuit_id]
    name = circuit_id.split("/")[0]
    package = spec["package"]
    source_dir = _zkp._CIRCUIT_REGISTRY_ROOT / "policies" / name / "v2.0.0"
    env = _zkp.bb_environment()
    if env is None:
        raise HTTPException(503, "Proving is unavailable on this server: the bb reference string is missing")

    label = f"tutorial-{secrets.token_hex(8)}"
    public_inputs = {**spec["public"], spec["reference"]: str(_zkp.derive_reference(agent_did, label))}
    prover_inputs = {**public_inputs, **spec["private"], "salt": str(secrets.randbits(248))}

    start = time.time()
    try:
        async with _TUTORIAL_PROVERS:
            with tempfile.TemporaryDirectory(prefix="tutorial_proof_") as work:
                os.makedirs(os.path.join(work, "src"))
                shutil.copy(source_dir / "Nargo.toml", os.path.join(work, "Nargo.toml"))
                shutil.copy(source_dir / "src" / "main.nr", os.path.join(work, "src", "main.nr"))
                with open(os.path.join(work, "Prover.toml"), "w") as f:
                    f.write("".join(f"{k} = {_toml_value(v)}\n" for k, v in prover_inputs.items()))

                await _run(["nargo", "execute", "witness"], work, env, 120, "nargo execute")
                target = os.path.join(work, "target")
                with open(os.path.join(target, f"{package}.json")) as f:
                    bytecode = base64.b64decode(json.load(f)["bytecode"])
                bytecode_path = os.path.join(target, f"{package}.bin")
                with open(bytecode_path, "wb") as f:
                    f.write(bytecode)
                proof_dir = os.path.join(target, "proof")
                os.makedirs(proof_dir)
                await _run(
                    ["bb", "prove", "-s", "ultra_honk", "-b", bytecode_path,
                     "-w", os.path.join(target, "witness.gz"), "-o", proof_dir],
                    work, env, 300, "bb prove",
                )
                with open(os.path.join(proof_dir, "proof"), "rb") as f:
                    proof_bytes = f.read()
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(504, "Proof generation timed out")
    except Exception as e:
        logger.error(f"[Tutorial ZKP] Proof generation failed: {e}")
        raise HTTPException(500, f"Proof generation failed: {e}")

    values = _zkp.proof_public_values(proof_bytes, circuit_id) or {}
    outputs = {k: str(v) for k, v in values.items() if k not in public_inputs}
    public_inputs["reference_label"] = label
    elapsed = (time.time() - start) * 1000
    logger.info(f"[Tutorial ZKP] Generated {circuit_id} proof: {len(proof_bytes)} bytes in {elapsed:.0f}ms")
    return {
        "circuit_id": circuit_id,
        "proof_bytes_base64": base64.b64encode(proof_bytes).decode("ascii"),
        "public_inputs": public_inputs,
        "public_outputs": outputs,
        "generation_time_ms": round(elapsed, 1),
    }


@router.get("/health")
async def tutorial_sandbox_health(developer=Security(get_current_developer)):
    """Quick sandbox health check for tutorial UI."""
    if not SANDBOX_URL:
        return {"healthy": False, "reason": NO_SANDBOX}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SANDBOX_URL}/health")
            return {"healthy": resp.status_code == 200, "sandbox_url": SANDBOX_URL}
    except Exception as e:
        return {"healthy": False, "error": str(e)}
