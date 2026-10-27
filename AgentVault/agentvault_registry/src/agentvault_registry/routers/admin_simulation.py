"""
Admin simulation management endpoints — EigenTrust Command Center backend.
Start/stop simulations, fetch agent balances across federation, bulk fund agents.
"""
import asyncio
import json
import logging
import os
import re
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

import httpx
from ..es_ssl_helper import get_httpx_verify
from fastapi import APIRouter, Depends, HTTPException, Body, Request, Security
from pydantic import BaseModel, Field

from agentvault_registry import security

logger = logging.getLogger(__name__)

def _require_simulation_enabled() -> None:
    """§EXCISION — the simulation console is Commander tooling, not an operator feature.

    It was gated ONLY by `admin_platform`, with no central-registry check, while
    hardcoding `REGISTRY_A_URL` and a Registry-A/Frame-B/Frame-C url_map. Cloud-ops
    share `agentvault_identity_network`, so `registry-a:8000` can resolve from one —
    an operator admin could drive or enumerate cluster registries from their own box.

    Dark by default (the `API_TEST_EXECUTION_ENABLED` precedent). Deliberately NOT
    gated on `IS_CENTRAL_REGISTRY`: the Hetzner frame sets that true.
    """
    if (os.getenv("ADMIN_SIMULATION_ENABLED") or "false").strip().lower() not in ("true", "1", "yes"):
        raise HTTPException(
            status_code=503,
            detail="Simulation console is not enabled on this registry.",
        )


router = APIRouter(
    prefix="/admin/simulation",
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "Admin — Simulation"
    dependencies=[
        Security(security.require_admin_flag("admin_platform")),
        Depends(_require_simulation_enabled),
    ],
)

# --- Config ---
SIM_SCRIPT = os.getenv("SIM_SCRIPT_PATH", "/opt/theprotocol/stack/Agentvault2/scripts/sim_eigentrust.py")
SIM_CREDENTIALS = os.getenv("SIM_CREDENTIALS_PATH", "/app/sim_credentials.json")
SIM_LOG_DIR = os.getenv("SIM_LOG_DIR", "/opt/theprotocol/stack/Agentvault2/sessionlogs2026")
REGISTRY_A_URL = os.getenv("REGISTRY_A_URL", "http://registry-a:8000")
REGISTRY_B_URL = os.getenv("REGISTRY_B_URL", "http://frame-b-registry:8000")
EVENT_STORE_URL = os.getenv("EVENT_STORE_URL", "http://event-store:8200")
EVENT_STORE_B_URL = os.getenv("FRAME_B_EVENT_STORE_URL", "http://frame-b-event-store:8200")
# Frame C (BVT) — §framec-sim 2026-06-06. registry-a is NOT host-networked and cannot
# reach frame-c by container name, so the Frame-C ES read uses the PUBLIC URL (system-CA,
# same as the tri-frame ledger). EVENT_STORE_C_URL is already exported on registry-a.
REGISTRY_C_URL = os.getenv("REGISTRY_C_URL", "https://sandbox-c.theprotocol.cloud")
EVENT_STORE_C_URL = os.getenv("EVENT_STORE_C_URL", "https://events-c.theprotocol.cloud")

# --- Cache ---
_agent_cache: Dict[str, Any] = {"agents": [], "ts": 0}
_AGENT_CACHE_TTL = 60
_url_map_cache: Dict[str, str] = {}
_url_map_ts: float = 0

# Track running sim
_sim_container_id: Optional[str] = None
_sim_start_time: Optional[float] = None
_sim_params: Dict[str, Any] = {}
SIM_CONTAINER_NAME = "eigentrust-sim"

# 2026-05-01: Phase 5 — instance cap bumped 8 → 16 for high-load sim crank.
_SIM_INSTANCE_CAP = int(os.getenv("SIM_INSTANCE_CAP", "16"))

# Docker socket path
DOCKER_SOCKET = "/var/run/docker.sock"

# ─── DEADMAN SWITCH ────────────────────────────────────────────────────────
# 2026-05-01: when the sim is cranked hard (e.g. 16 × 50 pairs), runaway risk
# becomes real. The deadman task runs alongside the sim, polls host health
# every 30 s, and auto-stops the sim if any threshold is breached for 2
# consecutive checks OR the absolute max-runtime ceiling is hit.
#
# Thresholds focus on what would actually destabilise the box (memory + swap
# + load) rather than soft signals. PgBouncer queue depth is an obvious
# next-iteration metric — see Phase 6 plan in mellow-shimmying-cherny.md.
_SIM_DEADMAN_ENABLED = os.getenv("SIM_DEADMAN_ENABLED", "true").lower() in ("true", "1", "yes")
_SIM_DEADMAN_CHECK_INTERVAL = int(os.getenv("SIM_DEADMAN_CHECK_INTERVAL_SEC", "30"))
_SIM_DEADMAN_CONSECUTIVE_BREACH = int(os.getenv("SIM_DEADMAN_CONSECUTIVE_BREACH", "2"))
_SIM_DEADMAN_MAX_RUNTIME_MIN = int(os.getenv("SIM_DEADMAN_MAX_RUNTIME_MIN", "90"))
# 24-thread box; baseline ~80 with sim running at 4×25; meltdown >200.
_SIM_DEADMAN_LOAD1M_MAX = float(os.getenv("SIM_DEADMAN_LOAD1M_MAX", "200"))
# 31 GiB swap total; current ~15 GiB; warn at 28.
_SIM_DEADMAN_SWAP_USED_GB_MAX = float(os.getenv("SIM_DEADMAN_SWAP_USED_GB_MAX", "28"))
# 125 GiB total; OOM territory < 5 GiB available.
_SIM_DEADMAN_MEM_AVAILABLE_GB_MIN = float(os.getenv("SIM_DEADMAN_MEM_AVAILABLE_GB_MIN", "5"))

_deadman_task: Optional[asyncio.Task] = None
_deadman_last_snap: Dict[str, Any] = {}
_deadman_breach_history: list = []  # bounded to last 20

# ─── Cross-worker shared state (2026-05-31) ────────────────────────────────
# The mainframe runs 32 uvicorn workers — separate processes inside ONE
# container, so they share the container filesystem but NOT memory. The
# module-level _sim_params / _deadman_* above are visible only to the worker
# that served /start; /status or /deadman-status answered by any OTHER worker
# returned empty params and — worse — could not show WHY the deadman tore a run
# down (it looked like the sim died silently). Persist run + deadman state to a
# shared JSON file so every worker reports a consistent picture and the
# deadman's stop-reason survives for the operator.
_STATE_FILE = os.getenv("SIM_STATE_FILE", "/tmp/sim_runtime_state.json")


def _read_state() -> Dict[str, Any]:
    try:
        with open(_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _write_state(patch: Dict[str, Any]) -> None:
    """Atomic, 1-level-deep merge into the shared sim state file (single writer
    at a time: the worker that owns the run/deadman)."""
    try:
        cur = _read_state()
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(cur.get(k), dict):
                cur[k] = {**cur[k], **v}
            else:
                cur[k] = v
        tmp = f"{_STATE_FILE}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(cur, f)
        os.replace(tmp, _STATE_FILE)
    except Exception as e:
        logger.debug("[SIM] state write failed: %s", e)


# --- Models ---
SimMode = Literal["mixed", "local-only", "cross-only", "cross-frame-only", "fx", "market", "delegation"]
SimBackendMode = Literal["mixed", "async", "2pc", "intra"]


class SimStartRequest(BaseModel):
    # 2026-05-31: `mode` was declared TWICE here (default "modern", then "mixed")
    # while the FE Control tab sent "modern"/"legacy" — values that never matched
    # the real path enum and were passed straight to the sim CLI (silent
    # garbage-in). Now a validated Literal: a bad value 422s instead of
    # corrupting the run, and the enum surfaces in the OpenAPI schema.
    mode: SimMode = "mixed"  # mixed | local-only | cross-only | cross-frame-only
    pairs: int = Field(15, ge=1, le=500)
    cycle_interval: int = Field(3, ge=0, le=3600)
    cycles: int = Field(100000, ge=0)
    raw: bool = False
    instances: int = Field(1, ge=1, le=16)  # runtime also clamps to SIM_INSTANCE_CAP
    concurrency: int = Field(40, ge=1, le=1000)  # max parallel transfers per instance
    metrics_jsonl: Optional[str] = None  # if set, write per-cycle JSONL inside container
    # Phase 10: backend for cross-registry fires — async (SF-4 reactor) | 2pc
    # (synchronous 2-phase commit) | intra (force same-registry, mode→local-only)
    # | mixed (randomize per cross fire across {async, 2pc}).
    backend_mode: SimBackendMode = "mixed"
    # rate_tps overrides cycle_interval: cycle_interval = pairs*instances/rate_tps
    # (e.g. rate_tps=1.0 → ~1 tx/s, for slow runs alongside canary).
    rate_tps: Optional[float] = Field(None, gt=0)
    # ── Dynamic auto-regulation (AIMD, 2026-06-06) ──────────────────────────
    # dynamic=True → the sim ignores fixed pairs/concurrency and self-adjusts
    # in-flight concurrency to hold target_settle_ms (the latency SLO), backing
    # off on errors — for sustained error-free runs with no manual tuning.
    dynamic: bool = False
    target_settle_ms: int = Field(5000, ge=200, le=120000)
    target_metric: Literal["p50", "p95", "avg"] = "p50"
    min_concurrency: int = Field(2, ge=1, le=1000)
    max_concurrency: int = Field(64, ge=1, le=1000)
    # ── Settlement-backlog backpressure (2026-06-13) ────────────────────────
    # dynamic market mode: HOLD new order creation while any venue's settlement
    # backlog (exchange overview settlement.pending) exceeds this cap; resume
    # under 0.8x. Keeps the sim from outrunning the AGORA settlement worker
    # (the I-X4 over-SLO class). 0 = disabled (unbounded, the prior behaviour).
    max_backlog: int = Field(0, ge=0, le=1000000)
    # ── Currency-balance anti-skew (market mode, 2026-06-13) ────────────────
    # The A/B(AVT) vs C(BVT) venue set is asymmetric (2 AVT venues, 1 BVT), so a
    # uniform per-venue pick gives the AVT currency ~2x the flow. 'currency'
    # (default) balances each CURRENCY equally (the single BVT venue gets as much
    # as both AVT venues combined, passport folded in); 'venue' = legacy uniform.
    venue_balance: str = Field("currency", pattern="^(currency|venue)$")
    # Fraction of market fires that are PASSPORT relays (foreign agent → frame-c BVT).
    passport_share: float = Field(0.18, ge=0.0, le=0.95)
    # ── §2026-07-19 IRONKEY sim options ─────────────────────────────────────
    # Desk model: a bounded pool of frame-c-mainframe parents each spawn ONE execution-clerk
    # sub-agent that places their market orders via X-Capability-Token (birth token). In market
    # mode it also folds a full delegation lifecycle + audit-self-check tick every N cycles.
    # Requires the frame-c IRONKEY flags live; degrades to direct trading elsewhere. Δ-neutral.
    spawn_subagents: bool = False
    # Optional cross-REGISTRY delegation leg (frame-c → doha peer) in the delegation battery.
    # Default OFF; does NOT require flipping any frame's flag.
    xreg_delegation: bool = False
    # ── §XREGMODE 2026-08-12 — "100% FOREIGN-FEDERATED" overlay ──────────────────────────────
    # spawn_frames: MAINFRAME frames whose parents get the authz.delegate grant so they spawn an
    #   execution-clerk under enforce. Default "C" (frame-c only, legacy); "A,B,C" spawns clerks on
    #   ALL THREE mainframes. Passed to the sim as SIM_SPAWN_FRAMES.
    # xreg_only: force EVERY clerk-routed market fire to a FOREIGN passport order (target venue !=
    #   sender's home registry) → 100% cross-registry order-flow via spawned sub-agents. Implies
    #   mode=market + spawn_subagents (forced in start_simulation). Passed as SIM_XREG_ONLY.
    # clerk_anchored: spawn the clerk WALLETLESS (draws its spend from the PARENT via §SPAWN-ANCHOR).
    #   Only the LOCAL legs are anchor-wired today (the passport funding leg is not), so leave OFF
    #   under xreg_only. Passed as SIM_CLERK_ANCHORED.
    spawn_frames: str = Field("C", pattern=r"^[ABCabc](,[ABCabc])*$")
    xreg_only: bool = False
    clerk_anchored: bool = False


class FundRequest(BaseModel):
    target_balance: float = 10000
    only_depleted: bool = False
    depleted_threshold: float = 100


# --- Helpers ---
def _load_credentials() -> Dict[str, List[Dict]]:
    path = Path(SIM_CREDENTIALS)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


async def _build_url_map() -> Dict[str, str]:
    global _url_map_cache, _url_map_ts
    if _url_map_cache and (time.time() - _url_map_ts) < 3600:
        return _url_map_cache

    url_map = {"Registry-A": REGISTRY_A_URL, "Frame-B-Sovereign": REGISTRY_B_URL, "Frame-C": REGISTRY_C_URL}
    try:
        async with httpx.AsyncClient(timeout=10, verify=get_httpx_verify()) as client:
            resp = await client.get(f"{REGISTRY_A_URL}/api/v1/agents/locations/trusted-registries")
            if resp.status_code == 200:
                data = resp.json()
                regs = data if isinstance(data, list) else data.get("registries", [])
                for reg in regs:
                    name = reg.get("name", "")
                    raw_url = reg.get("url") or reg.get("base_url") or ""
                    if name and raw_url:
                        parsed = urlparse(raw_url)
                        public_url = f"https://{parsed.hostname}"
                        url_map[name.replace(" ", "-")] = public_url
                        url_map[name] = public_url
    except Exception as e:
        logger.warning("[SIM] URL map build error: %s", e)

    _url_map_cache = url_map
    _url_map_ts = time.time()
    return url_map


async def _fetch_agent_balance(registry_url: str, client_id: str, client_secret: str) -> Optional[float]:
    try:
        async with httpx.AsyncClient(timeout=8, verify=False) as client:
            auth = await client.post(
                f"{registry_url}/api/v1/auth/agent/token",
                data={"username": client_id, "password": client_secret, "grant_type": "password"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if auth.status_code != 200:
                return None
            jwt = auth.json().get("access_token")
            bal = await client.get(
                f"{registry_url}/api/v1/teg/balance",
                headers={"Authorization": f"Bearer {jwt}"},
            )
            if bal.status_code == 200:
                return float(bal.json().get("balance", 0))
    except Exception:
        pass
    return None


# --- Docker helpers ---

async def _run_host_script(script_name: str, args: list = None, timeout_sec: int = 90) -> dict:
    """Run a Python script in a host-network container via Docker socket.
    Returns parsed JSON from stdout."""
    # Get registry image
    reg_info = await _docker_api("GET", "/containers/agentvault_registry_a/json")
    image = reg_info.get("Config", {}).get("Image", "agentvault2-registry-a")

    container_name = f"sim-helper-{int(time.time())}"
    cmd = ["python3", f"scripts/{script_name}"] + (args or [])

    body = {
        "Image": image,
        "Cmd": cmd,
        "WorkingDir": "/work",
        "User": "root",
        "HostConfig": {
            "NetworkMode": "host",
            "Binds": [
                "/opt/theprotocol/stack/Agentvault2:/work:rw",
                "/opt/theprotocol/stack/Agentvault2/theprotocol-sdk/src:/sdk:ro",
                "/tmp:/tmp",
            ],
        },
        "Env": ["PYTHONUNBUFFERED=1", "PYTHONPATH=/sdk"],
    }

    # Create + start
    create = await _docker_api("POST", f"/containers/create?name={container_name}", body)
    cid = create.get("Id", "")
    if not cid:
        return {"error": f"Failed to create container: {create}"}

    await _docker_api("POST", f"/containers/{cid}/start")

    # Wait for completion
    wait = await _docker_api("POST", f"/containers/{cid}/wait?t={timeout_sec}")

    # Get logs (stdout only)
    log_cmd = ["curl", "-s", "--unix-socket", DOCKER_SOCKET,
               f"http://localhost/v1.44/containers/{cid}/logs?stdout=true&stderr=false"]
    proc = await asyncio.create_subprocess_exec(
        *log_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()

    # Clean up container
    await _docker_api("DELETE", f"/containers/{container_name}?force=true")

    # Parse output — Docker log stream has 8-byte header per frame
    raw = stdout
    lines = []
    i = 0
    while i < len(raw):
        if i + 8 > len(raw):
            break
        size = int.from_bytes(raw[i+4:i+8], "big")
        if i + 8 + size > len(raw):
            lines.append(raw[i+8:].decode(errors="replace"))
            break
        lines.append(raw[i+8:i+8+size].decode(errors="replace"))
        i += 8 + size

    output = "".join(lines).strip()
    try:
        return json.loads(output)
    except Exception:
        return {"error": f"Failed to parse output", "raw": output[:500]}


async def _docker_api(method: str, path: str, body: dict = None) -> dict:
    """Call Docker Engine API via unix socket using curl subprocess."""
    cmd = ["curl", "-s", "--unix-socket", DOCKER_SOCKET, "-X", method,
           f"http://localhost/v1.44{path}"]
    if body:
        cmd.extend(["-H", "Content-Type: application/json", "-d", json.dumps(body)])
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        return json.loads(stdout.decode()) if stdout else {}
    except Exception:
        return {"raw": stdout.decode()[:500]}


# ─── Deadman switch helpers ────────────────────────────────────────────────

def _read_loadavg_1m() -> Optional[float]:
    try:
        with open("/proc/loadavg", "r") as f:
            return float(f.read().split()[0])
    except Exception:
        return None


def _read_meminfo() -> Dict[str, float]:
    """Return memory stats in GiB: total, available, swap_used."""
    out = {"total_gb": 0.0, "available_gb": 0.0, "swap_used_gb": 0.0}
    try:
        with open("/proc/meminfo", "r") as f:
            kv = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    kv[parts[0].rstrip(":")] = float(parts[1])  # kB
        out["total_gb"] = kv.get("MemTotal", 0) / 1024 / 1024
        out["available_gb"] = kv.get("MemAvailable", 0) / 1024 / 1024
        swap_total = kv.get("SwapTotal", 0)
        swap_free = kv.get("SwapFree", 0)
        out["swap_used_gb"] = max(0, swap_total - swap_free) / 1024 / 1024
    except Exception:
        pass
    return out


async def _capture_health_snapshot() -> Dict[str, Any]:
    snap = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "load1m": _read_loadavg_1m(),
    }
    snap.update(_read_meminfo())
    return snap


def _check_thresholds(snap: Dict[str, Any]) -> list:
    breached = []
    if snap.get("load1m") is not None and snap["load1m"] > _SIM_DEADMAN_LOAD1M_MAX:
        breached.append(f"load1m={snap['load1m']:.1f} > {_SIM_DEADMAN_LOAD1M_MAX}")
    if snap.get("swap_used_gb", 0) > _SIM_DEADMAN_SWAP_USED_GB_MAX:
        breached.append(f"swap_used_gb={snap['swap_used_gb']:.1f} > {_SIM_DEADMAN_SWAP_USED_GB_MAX}")
    if 0 < snap.get("available_gb", 99) < _SIM_DEADMAN_MEM_AVAILABLE_GB_MIN:
        breached.append(f"available_gb={snap['available_gb']:.1f} < {_SIM_DEADMAN_MEM_AVAILABLE_GB_MIN}")
    return breached


async def _stop_sim_internal(reason: str, details: Any = None):
    """Internal stop — same machinery as /stop, plus history append."""
    global _sim_start_time, _sim_params
    logger.warning(f"[SIM-DEADMAN] STOPPING sim: reason={reason} details={details}")
    stop_record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "details": details,
        "snap": dict(_deadman_last_snap),
    }
    _deadman_breach_history.append(stop_record)
    # Trim history to last 20
    while len(_deadman_breach_history) > 20:
        _deadman_breach_history.pop(0)
    # Persist the stop-reason cross-worker so an operator querying ANY worker can
    # see WHY the run ended (the gap that made a deadman-killed run look silent).
    _write_state({
        "params": {}, "started_at": None,
        "deadman": {"armed": False, "last_stop": stop_record,
                    "breach_history": list(_deadman_breach_history)},
    })
    # Stop containers
    for i in range(1, _SIM_INSTANCE_CAP + 1):
        name = f"eigentrust-sim-{i}"
        info = await _docker_api("GET", f"/containers/{name}/json")
        if info.get("State", {}).get("Running"):
            await _docker_api("POST", f"/containers/{name}/stop?t=3")
        await _docker_api("DELETE", f"/containers/{name}?force=true")
    await _docker_api("POST", f"/containers/{SIM_CONTAINER_NAME}/stop?t=3")
    await _docker_api("DELETE", f"/containers/{SIM_CONTAINER_NAME}?force=true")
    _sim_start_time = None
    _sim_params = {}


async def _deadman_loop():
    """Polls host health, auto-stops sim on threshold breach or max runtime."""
    global _deadman_last_snap
    breaches = 0
    started_at = time.time()
    logger.info(
        f"[SIM-DEADMAN] armed: interval={_SIM_DEADMAN_CHECK_INTERVAL}s "
        f"max_runtime={_SIM_DEADMAN_MAX_RUNTIME_MIN}min "
        f"thresholds=load1m<{_SIM_DEADMAN_LOAD1M_MAX} "
        f"swap_used_gb<{_SIM_DEADMAN_SWAP_USED_GB_MAX} "
        f"avail_gb>{_SIM_DEADMAN_MEM_AVAILABLE_GB_MIN}"
    )
    try:
        while True:
            await asyncio.sleep(_SIM_DEADMAN_CHECK_INTERVAL)
            elapsed_min = (time.time() - started_at) / 60
            if elapsed_min >= _SIM_DEADMAN_MAX_RUNTIME_MIN:
                await _stop_sim_internal(
                    reason="max_runtime",
                    details=f"elapsed_min={elapsed_min:.1f}",
                )
                return
            snap = await _capture_health_snapshot()
            _deadman_last_snap = snap
            breached = _check_thresholds(snap)
            _write_state({"deadman": {
                "armed": True, "heartbeat": time.time(), "last_snap": snap,
                "breach_history": list(_deadman_breach_history),
                "breaches_pending": breaches,
            }})
            if breached:
                breaches += 1
                logger.warning(
                    f"[SIM-DEADMAN] breach #{breaches}/{_SIM_DEADMAN_CONSECUTIVE_BREACH}: "
                    f"{breached} | snap={snap}"
                )
                if breaches >= _SIM_DEADMAN_CONSECUTIVE_BREACH:
                    await _stop_sim_internal(reason="threshold_breach", details=breached)
                    return
            else:
                breaches = 0
    except asyncio.CancelledError:
        logger.info("[SIM-DEADMAN] cancelled (manual stop)")
        raise
    except Exception as e:
        logger.error(f"[SIM-DEADMAN] loop crashed: {e}", exc_info=True)


@router.get("/status")
async def get_simulation_status():
    """Get current simulation state — checks all eigentrust-sim-* containers."""
    running_instances = 0
    container_ids = []

    # List all containers matching eigentrust-sim pattern
    containers = await _docker_api("GET", "/containers/json?all=true&filters=%7B%22name%22%3A%5B%22eigentrust-sim%22%5D%7D")
    if isinstance(containers, list):
        for c in containers:
            if c.get("State") == "running":
                running_instances += 1
                container_ids.append(c.get("Id", "")[:12])

    running = running_instances > 0
    state = _read_state()
    started_at = state.get("started_at") or _sim_start_time
    params = state.get("params") or _sim_params
    return {
        "running": running,
        "instances": running_instances,
        "container_ids": container_ids,
        "uptime_seconds": int(time.time() - started_at) if started_at and running else 0,
        "params": params if running else {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/start")
async def start_simulation(req: SimStartRequest):
    """Start N EigenTrust simulation instances in Docker containers with host networking."""
    global _sim_start_time, _sim_params

    # Check if already running
    status = await get_simulation_status()
    if status["running"]:
        raise HTTPException(409, detail=f"Simulation already running ({status['instances']} instances)")

    instances = max(1, min(_SIM_INSTANCE_CAP, req.instances))

    # Phase 10 (2026-05-04): rate_tps override. Compute cycle_interval from
    # target tps so callers can specify a slow pace without arithmetic.
    # Formula: cycle_interval_sec = pairs * instances / rate_tps
    # Example: pairs=5, instances=1, rate_tps=1.0 → cycle_interval=5s (1 tx/s).
    if req.rate_tps and req.rate_tps > 0:
        new_interval = max(1, int(req.pairs * instances / req.rate_tps))
        logger.info(
            "[SIM] rate_tps=%.2f override → cycle_interval=%ds (pairs=%d, instances=%d)",
            req.rate_tps, new_interval, req.pairs, instances,
        )
        req.cycle_interval = new_interval

    # Phase 10: backend_mode='intra' forces same-registry pairs only.
    if req.backend_mode == "intra" and req.mode != "local-only":
        logger.info(
            "[SIM] backend_mode='intra' → forcing path mode='local-only' (was '%s')",
            req.mode,
        )
        req.mode = "local-only"

    # Remove stale containers (cleanup loop covers the cap range)
    for i in range(1, _SIM_INSTANCE_CAP + 1):
        await _docker_api("DELETE", f"/containers/eigentrust-sim-{i}?force=true")
    await _docker_api("DELETE", f"/containers/{SIM_CONTAINER_NAME}?force=true")

    # §XREGMODE prereqs: xreg_only needs market mode + spawned clerks (the 100%-foreign passport
    # order-flow rides the execution-clerk). Force them so the operator only ticks one box. Also
    # default a settlement-backlog cap so a foreign-passport run cannot outrun cross-frame event
    # replication (the load lesson from the first at-scale run) — honoured only in dynamic mode.
    if req.xreg_only:
        req.mode = "market"
        req.spawn_subagents = True
        if req.max_backlog == 0:
            req.max_backlog = 30

    # Build command
    cmd = ["python3", "scripts/sim_eigentrust.py", "--daemon",
           "--cycles", str(req.cycles if req.cycles > 0 else 999999), "--pairs", str(req.pairs),
           "--cycle-interval", str(req.cycle_interval),
           "--mode", req.mode,
           "--concurrency", str(req.concurrency),
           "--backend-mode", req.backend_mode]
    if req.raw:
        cmd.append("--raw")
    if req.metrics_jsonl:
        cmd.extend(["--metrics-jsonl", req.metrics_jsonl])
    if req.dynamic:
        cmd.extend([
            "--dynamic",
            "--target-settle-ms", str(req.target_settle_ms),
            "--target-metric", req.target_metric,
            "--min-concurrency", str(req.min_concurrency),
            "--max-concurrency", str(req.max_concurrency),
        ])
        if req.max_backlog > 0:
            cmd.extend(["--max-backlog", str(req.max_backlog)])
    if req.mode == "market":
        # §V0073 anti-skew: balance order-flow across the asymmetric A/B(AVT) vs C(BVT)
        # venue set ('currency' = equal per currency, default; 'venue' = legacy uniform).
        cmd.extend(["--venue-balance", req.venue_balance,
                    "--passport-share", str(req.passport_share)])
    # §2026-07-19 IRONKEY: desk model (spawn clerks + fold a delegation/audit tick into market) and
    # the optional cross-registry leg. Both default OFF → the launch line is byte-identical when unset.
    if req.spawn_subagents:
        cmd.append("--spawn-subagents")
    if req.xreg_delegation:
        cmd.append("--xreg-delegation")

    # Get registry image name
    reg_info = await _docker_api("GET", "/containers/agentvault_registry_a/json")
    image = reg_info.get("Config", {}).get("Image", "agentvault2-registry-a")

    started = []
    for i in range(1, instances + 1):
        name = f"eigentrust-sim-{i}"
        create_body = {
            "Image": image,
            "Cmd": ["/bin/sh", "-c",
                    "mkdir -p /tmp/simwork/scripts /tmp/simwork/sessionlogs2026 && "
                    "cp /scripts/sim_eigentrust.py /tmp/simwork/scripts/ && "
                    "cp /scripts/sim_credentials.json /tmp/simwork/scripts/ && "
                    "ln -sf /sessionlogs /tmp/simwork/sessionlogs2026 2>/dev/null; "
                    "cd /tmp/simwork && " + " ".join(cmd)],
            "WorkingDir": "/tmp/simwork",
            "HostConfig": {
                "NetworkMode": "host",
                "Binds": [
                    "/opt/theprotocol/stack/Agentvault2/scripts:/scripts:ro",
                    "/opt/theprotocol/stack/Agentvault2/sessionlogs2026:/sessionlogs:rw",
                    "/opt/theprotocol/stack/Agentvault2/theprotocol-sdk/src:/sdk:ro",
                ],
            },
            "User": "root",
            "Env": [
                "PYTHONUNBUFFERED=1",
                "PYTHONPATH=/sdk:/tmp/simwork",
                # §XREGMODE knobs — the sim reads these at module load (os.getenv), so they must be
                # container env, not CLI args. Byte-inert defaults preserve legacy behaviour.
                f"SIM_SPAWN_FRAMES={req.spawn_frames.upper()}",
                f"SIM_XREG_ONLY={'1' if req.xreg_only else '0'}",
                f"SIM_CLERK_ANCHORED={'1' if req.clerk_anchored else '0'}",
            ],
        }

        result = await _docker_api("POST", f"/containers/create?name={name}", create_body)
        cid = result.get("Id", "")
        if cid:
            await _docker_api("POST", f"/containers/{cid}/start")
            started.append(cid[:12])

    if not started:
        # AAA+ (2026-06-06): never report a fake success. A failed Docker
        # create/start previously returned HTTP 200 with instances:0, so the FE
        # showed nothing ("Start does nothing"). Surface a real error instead.
        raise HTTPException(
            status_code=500,
            detail=("Failed to launch any simulation instances — Docker create/start "
                    "returned no container id. Check the docker socket mount, the "
                    "registry image, and scripts/sim_credentials.json."),
        )

    _sim_start_time = time.time()
    _sim_params = req.model_dump()
    _write_state({
        "params": _sim_params,
        "started_at": _sim_start_time,
        "deadman": {"armed": bool(_SIM_DEADMAN_ENABLED and started),
                    "heartbeat": time.time(), "last_snap": {},
                    "breach_history": [], "last_stop": None},
    })
    logger.info("[SIM] Started %d simulation instances: %s", len(started), started)

    # Arm the deadman switch (Phase 6, 2026-05-01) — auto-stops sim on host-
    # health breach or after max runtime. Cancelled by manual /stop.
    global _deadman_task, _deadman_breach_history, _deadman_last_snap
    if _SIM_DEADMAN_ENABLED and started:
        _deadman_breach_history = []
        _deadman_last_snap = {}
        if _deadman_task is None or _deadman_task.done():
            _deadman_task = asyncio.create_task(_deadman_loop())

    return {
        "status": "started",
        "instances": len(started),
        "container_ids": started,
        "params": _sim_params,
        "deadman_armed": _SIM_DEADMAN_ENABLED and bool(started),
    }


@router.post("/stop")
async def stop_simulation():
    """Stop all running simulation containers."""
    global _sim_start_time, _sim_params, _deadman_task

    # Cancel deadman first so it doesn't double-stop us
    if _deadman_task and not _deadman_task.done():
        _deadman_task.cancel()
        try:
            await _deadman_task
        except (asyncio.CancelledError, Exception):
            pass
    _deadman_task = None

    stopped = 0
    for i in range(1, _SIM_INSTANCE_CAP + 1):
        name = f"eigentrust-sim-{i}"
        info = await _docker_api("GET", f"/containers/{name}/json")
        if info.get("State", {}).get("Running"):
            await _docker_api("POST", f"/containers/{name}/stop?t=3")
            stopped += 1
        await _docker_api("DELETE", f"/containers/{name}?force=true")
    # Also clean legacy name
    await _docker_api("POST", f"/containers/{SIM_CONTAINER_NAME}/stop?t=3")
    await _docker_api("DELETE", f"/containers/{SIM_CONTAINER_NAME}?force=true")

    _sim_start_time = None
    _sim_params = {}
    _write_state({
        "params": {}, "started_at": None,
        "deadman": {"armed": False, "last_stop": {
            "ts": datetime.now(timezone.utc).isoformat(),
            "reason": "manual_stop", "details": None}},
    })
    return {"status": "stopped", "stopped_instances": stopped}


@router.get("/deadman-status")
async def get_deadman_status():
    """Phase 6 (2026-05-01): observability for the sim deadman switch.
    2026-05-31: reads cross-worker shared state so ANY worker reports the real
    armed-ness, last snapshot, breach history AND last stop-reason — previously
    only the worker that served /start knew, so a deadman-killed run looked silent.
    """
    state = _read_state()
    dm = state.get("deadman") if isinstance(state.get("deadman"), dict) else {}
    local_armed = _deadman_task is not None and not _deadman_task.done()
    hb = dm.get("heartbeat") or 0
    hb_fresh = bool(hb) and (time.time() - hb) < (_SIM_DEADMAN_CHECK_INTERVAL * 3)
    armed = bool(local_armed or (dm.get("armed") and hb_fresh))
    return {
        "armed": armed,
        "enabled_at_start": _SIM_DEADMAN_ENABLED,
        "thresholds": {
            "load1m_max": _SIM_DEADMAN_LOAD1M_MAX,
            "swap_used_gb_max": _SIM_DEADMAN_SWAP_USED_GB_MAX,
            "mem_available_gb_min": _SIM_DEADMAN_MEM_AVAILABLE_GB_MIN,
            "max_runtime_min": _SIM_DEADMAN_MAX_RUNTIME_MIN,
            "consecutive_breach": _SIM_DEADMAN_CONSECUTIVE_BREACH,
            "check_interval_sec": _SIM_DEADMAN_CHECK_INTERVAL,
        },
        "last_snapshot": dm.get("last_snap") or _deadman_last_snap,
        "breach_history": dm.get("breach_history") or list(_deadman_breach_history),
        "last_stop": dm.get("last_stop"),
        "instance_cap": _SIM_INSTANCE_CAP,
    }


# ─── Live telemetry parsing (2026-05-31) ───────────────────────────────────
# The sim's per-cycle metrics (throughput, success rate, per-path latency
# percentiles) were locked inside container stdout — the UI could only string-
# match log lines. Parse the CYCLE line into structured aggregate telemetry:
#   CYCLE 42 | 48ok 2fail (30L 12CR 6CF) | fees≈1.2 | <supply> | 2.3s ...
#            ... L=p50/12|p95/45|p99/89ms(n=30) CR=... CF=...
_CYCLE_RE = re.compile(
    r"CYCLE\s+(\d+)\s+\|\s+(\d+)ok\s+(\d+)fail\s+\((\d+)L\s+(\d+)CR\s+(\d+)CF\)"
)
_ELAPSED_RE = re.compile(r"\|\s+([\d.]+)s(?:\s|$|\|)")
_LAT_RE = re.compile(r"\b(L|CR|CF)=p50/(\d+)\|p95/(\d+)\|p99/(\d+)ms")
_LAT_LABELS = {"L": "local", "CR": "cross_reg", "CF": "cross_frame"}
# Dynamic auto-regulation telemetry embedded in the CYCLE line (2026-06-06):
#   ... | DYN conc=8 settle=4600 target=5000 err=0
_DYN_RE = re.compile(r"DYN conc=(\d+) settle=(\d+) target=(\d+) err=(\d+)")


async def _fetch_cycle_lines(name: str, tail: int = 8) -> List[str]:
    """Tail a sim container's logs, demux the docker stream, return CYCLE lines."""
    log_cmd = ["curl", "-s", "--unix-socket", DOCKER_SOCKET,
               f"http://localhost/v1.44/containers/{name}/logs?stdout=true&tail={tail}"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *log_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
    except Exception:
        return []
    raw, pos, out = stdout or b"", 0, []
    while pos + 8 <= len(raw):
        size = int.from_bytes(raw[pos + 4:pos + 8], "big")
        end = pos + 8 + size
        chunk = raw[pos + 8:end] if end <= len(raw) else raw[pos + 8:]
        line = chunk.decode(errors="replace").strip()
        if "CYCLE" in line:
            out.append(line)
        pos = end if end <= len(raw) else len(raw)
    return out


@router.get("/metrics")
async def get_simulation_metrics():
    """2026-05-31: structured live telemetry for the EigenTrust sim — parses each
    running instance's latest CYCLE line into aggregate throughput, success rate
    and per-path latency percentiles for the Telemetry panel."""
    empty = {"running": False, "instances": 0, "throughput_tps": 0.0, "ok": 0,
             "fail": 0, "fail_pct": 0.0, "paths": {}, "latency": {},
             "per_instance": [], "ts": datetime.now(timezone.utc).isoformat()}
    containers = await _docker_api(
        "GET", "/containers/json?filters=%7B%22name%22%3A%5B%22eigentrust-sim%22%5D%7D")
    running = []
    if isinstance(containers, list):
        for c in containers:
            if c.get("State") == "running":
                for n in c.get("Names", []):
                    running.append(n.strip("/"))
    if not running:
        return empty

    total_ok = total_fail = 0
    paths = {"local": 0, "cross_reg": 0, "cross_frame": 0}
    tps = 0.0
    lat_agg: Dict[str, Dict[str, list]] = {}
    per_instance = []
    dyn_seen = []  # dynamic auto-regulation telemetry per running instance

    for name in sorted(running):
        lines = await _fetch_cycle_lines(name)
        if not lines:
            continue
        last = lines[-1]
        m = _CYCLE_RE.search(last)
        if not m:
            continue
        cyc, ok, fail, lo, cr, cf = (int(x) for x in m.groups())
        em = _ELAPSED_RE.search(last)
        secs = float(em.group(1)) if em else 0.0
        total_ok += ok
        total_fail += fail
        paths["local"] += lo
        paths["cross_reg"] += cr
        paths["cross_frame"] += cf
        inst_tps = round(ok / secs, 2) if secs > 0 else 0.0
        tps += inst_tps
        lat = {}
        for tag, p50, p95, p99 in _LAT_RE.findall(last):
            key = _LAT_LABELS[tag]
            lat[key] = {"p50": int(p50), "p95": int(p95), "p99": int(p99)}
            agg = lat_agg.setdefault(key, {"p50": [], "p95": [], "p99": []})
            agg["p50"].append(int(p50))
            agg["p95"].append(int(p95))
            agg["p99"].append(int(p99))
        try:
            inst_num = int(name.split("-")[-1])
        except Exception:
            inst_num = 0
        inst_dyn = None
        dm = _DYN_RE.search(last)
        if dm:
            inst_dyn = {"concurrency": int(dm.group(1)), "settle_ms": int(dm.group(2)),
                        "target_settle_ms": int(dm.group(3)), "err_pct": int(dm.group(4))}
            dyn_seen.append(inst_dyn)
        per_instance.append({"instance": inst_num, "cycle": cyc, "ok": ok,
                             "fail": fail, "tps": inst_tps, "latency": lat, "dynamic": inst_dyn})

    def _avg(xs):
        return round(sum(xs) / len(xs)) if xs else 0
    latency = {k: {"p50": _avg(v["p50"]), "p95": _avg(v["p95"]), "p99": _avg(v["p99"])}
               for k, v in lat_agg.items()}
    total = total_ok + total_fail
    # Aggregate dynamic auto-regulation state (if any instance is running dynamic)
    if dyn_seen:
        dynamic_agg = {
            "enabled": True,
            "concurrency": round(sum(d["concurrency"] for d in dyn_seen) / len(dyn_seen)),
            "settle_ms": max(d["settle_ms"] for d in dyn_seen),
            "target_settle_ms": dyn_seen[0]["target_settle_ms"],
        }
    else:
        dynamic_agg = {"enabled": False}
    return {
        "running": True,
        "instances": len(running),
        "throughput_tps": round(tps, 2),
        "ok": total_ok,
        "fail": total_fail,
        "fail_pct": round(100 * total_fail / total, 1) if total else 0.0,
        "paths": paths,
        "latency": latency,
        "dynamic": dynamic_agg,
        "per_instance": sorted(per_instance, key=lambda x: x["instance"]),
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/logs")
async def get_simulation_logs(tail: int = 40):
    """Get recent log lines from all running sim instances."""
    all_lines = []

    # Only query containers that are actually running
    running = []
    containers = await _docker_api("GET", "/containers/json?filters=%7B%22name%22%3A%5B%22eigentrust-sim%22%5D%7D")
    if isinstance(containers, list):
        for c in containers:
            if c.get("State") == "running":
                for n in c.get("Names", []):
                    name = n.strip("/")
                    running.append(name)

    if not running:
        return {"lines": [], "total": 0}

    for name in running:
        i = int(name.split("-")[-1]) if name[-1].isdigit() else 1
        log_cmd = ["curl", "-s", "--unix-socket", DOCKER_SOCKET,
                   f"http://localhost/v1.44/containers/{name}/logs?stdout=true&stderr=true&tail={tail}"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *log_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
            if not stdout:
                continue
            # Parse Docker log stream (8-byte header per frame)
            raw = stdout
            pos = 0
            while pos < len(raw):
                if pos + 8 > len(raw):
                    break
                size = int.from_bytes(raw[pos+4:pos+8], "big")
                if pos + 8 + size > len(raw):
                    line = raw[pos+8:].decode(errors="replace").strip()
                    if line:
                        all_lines.append({"instance": i, "line": line})
                    break
                line = raw[pos+8:pos+8+size].decode(errors="replace").strip()
                if line:
                    all_lines.append({"instance": i, "line": line})
                pos += 8 + size
        except Exception:
            continue

    # 2026-06-20 multi-instance fix: the old `all_lines[-tail:]` sliced the LAST `tail`
    # of [sim-1's lines … sim-2's lines …] concatenated, so it returned only the
    # last-appended instance (the "log shows 1 instance" bug). Instead, each instance
    # already contributed its own last `tail` lines above; here we interleave them
    # CHRONOLOGICALLY by the sim's `[HH:MM:SS]` prefix (stable for ties / unstamped
    # banner lines) and cap the response at `tail` per running instance so EVERY
    # instance stays represented.
    def _ts_key(entry, idx):
        ln = entry["line"]
        if len(ln) >= 10 and ln[0] == "[" and ln[3] == ":" and ln[6] == ":" and ln[9] == "]":
            try:
                return (int(ln[1:3]) * 3600 + int(ln[4:6]) * 60 + int(ln[7:9]), idx)
            except ValueError:
                pass
        return (-1, idx)  # unstamped → keep stable relative order

    ordered = [e for _, e in sorted(enumerate(all_lines), key=lambda p: _ts_key(p[1], p[0]))]
    cap = max(tail, tail * len(running))
    return {
        "lines": ordered[-cap:],
        "total": len(all_lines),
        "instances": sorted({e["instance"] for e in all_lines}),
    }


@router.get("/agents")
async def get_simulation_agents():
    """Get all sim agents with live balances via host-network container."""
    global _agent_cache
    now = time.time()

    if _agent_cache["agents"] and (now - _agent_cache["ts"]) < _AGENT_CACHE_TTL:
        return {
            "registries": _agent_cache["agents"],
            "total_agents": sum(len(r.get("agents", [])) for r in _agent_cache["agents"]),
            "total_funded": sum(r.get("funded_count", 0) for r in _agent_cache["agents"]),
            "total_balance": sum(r.get("total_balance", 0) for r in _agent_cache["agents"]),
            "cached": True,
        }

    result = await _run_host_script("sim_balance_check.py")
    if "error" in result:
        # §pass73.3.21: the sim balance-check runs via a host-network script that
        # only exists on the mainframe/sandbox-A simulation host. On a node without
        # it (e.g. a consumer cloud-op) this is a node-capability gap → self-identifying
        # 503, not a 500 internal error.
        raise HTTPException(
            503,
            detail=f"Simulation balance-check unavailable on this node (host-script/sim subsystem not provisioned — e.g. a consumer cloud-op): {result.get('error', '')}",
        )

    registries = result.get("registries", [])
    # Sort by total_balance descending
    registries.sort(key=lambda r: r.get("total_balance", 0), reverse=True)
    _agent_cache = {"agents": registries, "ts": now}

    return {
        "registries": registries,
        "total_agents": result.get("total_agents", 0),
        "total_funded": result.get("total_funded", 0),
        "total_balance": result.get("total_balance", 0),
        "cached": False,
    }


@router.post("/fund")
async def fund_simulation_agents(req: FundRequest):
    """Top up sim agents on their home registries via host-network container."""
    args = ["--target", str(req.target_balance)]
    if req.only_depleted:
        args.extend(["--depleted-only", "--depleted-threshold", str(req.depleted_threshold)])

    result = await _run_host_script("sim_fund_agents.py", args, timeout_sec=600)
    if "error" in result and "funded_count" not in result:
        raise HTTPException(500, detail=result.get("error", "Funding failed"))

    # Invalidate balance cache
    _agent_cache["ts"] = 0

    return result


@router.post("/funding-preview")
async def funding_preview(req: FundRequest):
    """Preview funding: calculate needed amounts without transferring."""
    args = ["--preview", "--target", str(req.target_balance)]
    if req.only_depleted:
        args.extend(["--depleted-only", "--depleted-threshold", str(req.depleted_threshold)])

    result = await _run_host_script("sim_fund_agents.py", args, timeout_sec=120)
    return result



# §EXCISION — these two mint proxies used to hardcode the Commander's email and
# password. That is a code defect, not an excisable asset: the literal sat in
# src/ (and its .pyc) on every registry image, so dropping the scripts/ payload
# would have removed one of two copies and looked like a fix. Read from env,
# with NO default: an unset var must fail loudly, never fall back to a secret.
# PRODUCTION_DOCS/08_SECURITY/Private_Surface_Excision.md
def _sim_admin_email() -> str:
    v = os.getenv("SIM_PEER_ADMIN_EMAIL")
    if not v:
        raise HTTPException(503, detail="SIM_PEER_ADMIN_EMAIL is not configured on this registry")
    return v


def _sim_admin_password() -> str:
    v = os.getenv("SIM_PEER_ADMIN_PASSWORD")
    if not v:
        raise HTTPException(503, detail="SIM_PEER_ADMIN_PASSWORD is not configured on this registry")
    return v


@router.post("/mint-frame-b", summary="Simulation: issue units on the simulation's second frame (admin)")
async def mint_frame_b(request: Request):
    """Simulation tooling of the former network: issue `amount` units on the simulation's second frame (the registry
    `SIM_FRAME_B_INTERNAL_URL` names), signed in there as the simulation's administrator, through that registry's own
    POST /api/v1/teg/treasury/mint. Needs an admin token with the `admin_platform` flag, on a registry whose
    simulation console is on.

    \f
    Mint tokens on Frame B treasury.
    2026-08-17: this dialed localhost:8100, which is unreachable from registry-a's
    non-host-networked container (its frame-c sibling documents the same trap), so the
    endpoint had NEVER worked — every call died in httpx.ConnectError. registry-a is
    attached to frame_b_network (Build #6.1), so the frame-b registry is reachable
    directly by service name; no public round-trip needed."""
    import httpx as _httpx
    body = await request.json()
    amount = body.get("amount", "0")
    frame_b_base = os.getenv("SIM_FRAME_B_INTERNAL_URL", "http://frame-b-registry:8000").rstrip("/")
    # Login to Frame B as commander
    async with _httpx.AsyncClient(timeout=15) as client:
        login = await client.post(f"{frame_b_base}/api/v1/auth/login",
            data={"username": _sim_admin_email(), "password": _sim_admin_password()},
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        if login.status_code != 200:
            raise HTTPException(500, detail="Cannot login to Frame B")
        jwt_b = login.json()["access_token"]
        resp = await client.post(f"{frame_b_base}/api/v1/teg/treasury/mint",
            json={"amount": amount, "reason": "EigenTrust funding top-up (Frame B)"},
            headers={"Authorization": f"Bearer {jwt_b}"})
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, detail=resp.json().get("detail", "Issuance failed on Frame B"))
        return resp.json()


@router.post("/mint-frame-c", summary="Simulation: issue units on the simulation's third frame (admin)")
async def mint_frame_c(request: Request):
    """Simulation tooling of the former network: issue `amount` units on the simulation's third frame (the registry
    `REGISTRY_C_URL` names, the issuing authority of its cluster), signed in there as the simulation's administrator,
    through that registry's own POST /api/v1/teg/treasury/mint. Needs an admin token with the `admin_platform` flag,
    on a registry whose simulation console is on.

    \f
    Mint BVT on the Frame C mainframe treasury — the minting authority for the whole
    Frame-C cluster (ME-ops are federated and can't mint; they receive BVT via cross-TEG).
    §framec-sim. registry-a is NOT host-networked, so localhost:8101 is unreachable — use
    the public REGISTRY_C_URL (system-CA verified)."""
    import httpx as _httpx
    body = await request.json()
    amount = body.get("amount", "0")
    base = REGISTRY_C_URL.rstrip("/")
    async with _httpx.AsyncClient(timeout=20, verify=get_httpx_verify()) as client:
        login = await client.post(f"{base}/api/v1/auth/login",
            data={"username": _sim_admin_email(), "password": _sim_admin_password()},
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        if login.status_code != 200:
            raise HTTPException(500, detail="Cannot login to Frame C")
        jwt_c = login.json()["access_token"]
        resp = await client.post(f"{base}/api/v1/teg/treasury/mint",
            json={"amount": amount, "reason": "EigenTrust funding top-up (Frame C / BVT)"},
            headers={"Authorization": f"Bearer {jwt_c}"})
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, detail=resp.json().get("detail", "Issuance failed on Frame C"))
        return resp.json()


@router.get("/fund-status")
async def get_fund_status():
    """Get real-time funding progress from the progress log file."""
    import os
    # Helper container writes to /work (=/opt/theprotocol/stack/Agentvault2 on host)
    # Registry reads via /host-stack mount to same host path.
    progress_file = "/host-stack/Agentvault2/.sim_fund_progress.jsonl"
    if not os.path.exists(progress_file):
        return {"lines": [], "total": 0}
    try:
        with open(progress_file) as f:
            lines = []
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return {"lines": lines, "total": len(lines)}
    except Exception:
        return {"lines": [], "total": 0}




@router.get("/topology")
async def get_federation_topology():
    """Get BFS federation topology with edges for visualization."""
    # Try Boris's federation-map first (has complete BFS graph with edges)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            boris_resp = await client.get("http://boris-agent:8045/api/boris/federation-map")
            if boris_resp.status_code == 200:
                boris_data = boris_resp.json()
                registries = []
                frame_b_names = {"frame-b", "alpha-b", "beta-b", "gamma-b", "delta-b",
                                 "epsilon-b", "zeta-b", "eta-b", "theta-b", "iota-b", "kappa-b"}
                # Frame C (BVT) — mainframe + 4 ME ops. §framec-sim 2026-06-06.
                frame_c_names = {"frame-c", "telaviv", "riyadh", "abudhabi", "doha"}
                for reg in boris_data.get("registries", []):
                    name = reg.get("name", "")
                    reg_id = reg.get("id", name.replace(" ", "-").lower())
                    frame = reg.get("frame_origin", "A")
                    if frame == "A" and any(fb in reg_id.lower() for fb in frame_b_names):
                        frame = "B"
                    if any(fc in reg_id.lower() for fc in frame_c_names):
                        frame = "C"
                    registries.append({
                        "id": reg_id,
                        "name": name,
                        "url": reg.get("url", ""),
                        "frame": frame,
                        "hop_depth": reg.get("hop_depth", 0),
                        "agent_count": reg.get("agent_count", 0),
                        "is_healthy": reg.get("is_healthy", True),
                        "response_ms": reg.get("response_ms", 0),
                        "boris_score": reg.get("boris_score", 0),
                        "grade": reg.get("grade", ""),
                    })
                return {
                    "registries": registries,
                    "edges": boris_data.get("edges", []),
                }
    except Exception as e:
        logger.warning("[SIM] Boris federation-map unavailable: %s", e)

    # Fallback: trusted-registries without edges
    registries = []
    try:
        async with httpx.AsyncClient(timeout=10, verify=get_httpx_verify()) as client:
            resp = await client.get(f"{REGISTRY_A_URL}/api/v1/agents/locations/trusted-registries")
            if resp.status_code == 200:
                data = resp.json()
                regs = data if isinstance(data, list) else data.get("registries", [])
                for reg in regs:
                    registries.append({
                        "id": reg.get("name", "").replace(" ", "-").lower(),
                        "name": reg.get("name", ""),
                        "url": reg.get("url", ""),
                        "frame": ("C" if any(fc in reg.get("name", "").lower() for fc in ("frame-c", "telaviv", "riyadh", "abudhabi", "doha")) else ("B" if "frame-b" in reg.get("name", "").lower() else "A")),
                        "hop_depth": reg.get("hop", 0),
                    })
    except Exception as e:
        logger.warning("[SIM] Topology fetch error: %s", e)

    return {"registries": registries, "edges": []}


@router.get("/supply-audit")
async def get_supply_audit():
    """Get supply invariant delta from both frames."""
    results = {}
    for label, url in [("A", EVENT_STORE_URL), ("B", EVENT_STORE_B_URL), ("C", EVENT_STORE_C_URL)]:
        try:
            async with httpx.AsyncClient(timeout=10, verify=get_httpx_verify()) as client:
                resp = await client.get(f"{url}/api/v1/projections/supply-audit")
                if resp.status_code == 200:
                    data = resp.json()
                    results[label] = {
                        "delta": data.get("delta", data.get("supply_delta", 0)),
                        "status": data.get("status", "UNKNOWN"),
                        "total_issued": data.get("tokens_issued", 0),
                        "total_circulating": data.get("total_circulating", 0),
                    }
        except Exception:
            results[label] = {"delta": None, "status": "UNREACHABLE"}

    return results
