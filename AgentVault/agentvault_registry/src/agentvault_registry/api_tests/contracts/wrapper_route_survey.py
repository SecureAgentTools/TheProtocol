"""§MCPTEST30 (V0547) — the sweep's wrapper↔route check is the build's request survey, run sealed on the target.

Phase F.3 (check_wrapper_route_drift.py, removed here) fetched /openapi.json, which has answered 308 to
/api/v1/openapi.json since §pass52, so it never ran: round 14's strict run (2026-10-02) carried
wrapper_drift_measured=False while the tile read 0. Pointed at sbx-alpha's real schema it compared each wrapper's
DOCUMENTED parameters with its route's body model and reported 31 drifts, none of them a request a route refuses (the
agent_jwt the dispatcher pops, pass-through objects, names a wrapper maps such as memo -> message). Whether a route
refuses a tool is decided by the request the tool SENDS, which is what tests/mcp_request_survey.py measures for the
build gate (test_mcp_tool_requests_meet_their_routes.py): every tool called offline, its captured request put through
FastAPI's own path, query and body validation.

The sweep runs that survey in a child process on the target's own image, SEALED: an environment holding dummy
credentials and none of the node's (no database URL, key or secret reaches it), every socket connect refused and no
process started, so no tool can reach the node's database, Redis, SPIRE socket or a peer whatever its code does (the
survey's recorder answers httpx; the seal answers everything else). The verdict uses the gate's own rule, GATED and
KNOWN read from the gate file, so a run and the build agree by construction. An image that carries no survey reads
NOT MEASURED and says why. The survey's PEER_ROUTE class (a tool whose route authenticates only a federation peer, so
no MCP caller can succeed) is listed apart: reported, not counted.
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SURVEY = "mcp_request_survey.py"
GATE = "test_mcp_tool_requests_meet_their_routes.py"
SOURCE = "the request survey, sealed, on the target's own image"
TIMEOUT_S = 300
DETAILS_CAP = 25
REPORTED = ("PEER_ROUTE",)   # listed apart, never counted as drift

# Runs first in the child: every connect refused (TCP and unix alike: asyncio, asyncpg and redis all end in
# socket.connect), no process started (asyncio's subprocess transport starts its child through subprocess.Popen),
# then the survey as __main__ with the arguments that follow.
SEAL = (
    "import os, runpy, socket, subprocess, sys\n"
    "def _no_connect(*a, **k):\n"
    "    raise OSError('sealed: the request survey makes no connection')\n"
    "socket.socket.connect = _no_connect\n"
    "socket.socket.connect_ex = _no_connect\n"
    "socket.create_connection = _no_connect\n"
    "class _NoProcess(subprocess.Popen):\n"
    "    def __init__(self, *a, **k):\n"
    "        raise OSError('sealed: the request survey starts no process')\n"
    "subprocess.Popen = _NoProcess\n"
    "def _no_system(*a, **k):\n"
    "    raise OSError('sealed: the request survey starts no process')\n"
    "os.system = _no_system\n"
    "sys.argv = sys.argv[1:]\n"
    "runpy.run_path(sys.argv[0], run_name='__main__')\n"
)


def tests_dir() -> Path:
    """Where the image keeps its tests: /app/tests beside /app/src/agentvault_registry."""
    import agentvault_registry
    return Path(agentvault_registry.__file__).resolve().parents[2] / "tests"


def read_rule(gate: Path) -> Tuple[Tuple[str, ...], Dict[str, str]]:
    """GATED and KNOWN, read from the gate file's own top-level assignments (never imported: it is a pytest module)."""
    found: Dict[str, Any] = {}
    for node in ast.parse(gate.read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ("GATED", "KNOWN"):
            found[node.targets[0].id] = ast.literal_eval(node.value)
    if not isinstance(found.get("GATED"), tuple) or not isinstance(found.get("KNOWN"), dict):
        raise ValueError(f"{gate.name} names no GATED tuple and KNOWN map")
    return tuple(str(c) for c in found["GATED"]), {str(k): str(v) for k, v in found["KNOWN"].items()}


def sealed_env(src: Path, home: str) -> Dict[str, str]:
    """The child's whole environment: the interpreter's path and dummies, nothing of the node's."""
    return {
        "PATH": os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin",
        "HOME": home,
        "LANG": "C.UTF-8",
        "PYTHONPATH": str(src),
        "PYTHONDONTWRITEBYTECODE": "1",
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
        "API_KEY_SECRET": "dummy",
    }


def _controls_hold(controls: Any) -> bool:
    """The survey's own controls came out the way they are built (the gate asserts more; these two are what make a
    zero mean something: the instrument sees a route that does not exist, and passes a request that is fine)."""
    if not isinstance(controls, dict):
        return False
    no_route = controls.get("no_route") or []
    good = controls.get("good")
    return any(isinstance(x, (list, tuple)) and x and x[0] == "NO_ROUTE" for x in no_route) \
        and isinstance(good, list) and all(isinstance(x, (list, tuple)) and x and x[0] == "ADMIN_ROUTE" for x in good)


def verdict(survey: Dict[str, Any], gated: Tuple[str, ...], known: Dict[str, str]) -> Dict[str, Any]:
    """The gate's rule over a survey's output: a tool in a GATED class is drift unless KNOWN names it."""
    surfaces = survey.get("surfaces") if isinstance(survey, dict) else None
    if not isinstance(surfaces, dict) or not surfaces:
        return {"measured": False, "reason": "the survey answered no surface"}
    if not _controls_hold(survey.get("controls")):
        return {"measured": False, "reason": "the survey's own controls did not come out as built"}
    failing: Dict[str, Dict[str, Any]] = {}
    reported: Dict[str, Dict[str, Any]] = {}
    surveyed: set = set()
    tools = requests = 0
    for surface, s in sorted(surfaces.items()):
        if not isinstance(s, dict) or not s.get("tools") or not s.get("requests"):
            return {"measured": False, "reason": f"the {surface} surface was not surveyed (no tool or no request)"}
        tools += int(s["tools"])
        requests += int(s["requests"])
        if isinstance(s.get("surveyed"), list):
            surveyed.update(str(t) for t in s["surveyed"])
        for cls in gated:
            for tool, details in ((s.get("classes") or {}).get(cls) or {}).items():
                row = failing.setdefault(tool, {"tool": tool, "surface": surface, "classes": [], "detail": ""})
                if cls not in row["classes"]:
                    row["classes"].append(cls)
                if not row["detail"] and details:
                    row["detail"] = f"{cls}: {str(details[0])[:200]}"
        for cls in REPORTED:
            for tool, details in ((s.get("classes") or {}).get(cls) or {}).items():
                reported.setdefault(tool, {"tool": tool, "surface": surface, "class": cls,
                                           "detail": str((details or [""])[0])[:200]})
    drift = [failing[t] for t in sorted(failing) if t not in known]
    return {
        "measured": True,
        "reason": None,
        "drift": len(drift),
        "details": drift[:DETAILS_CAP],
        "known": [{"tool": t, "reason": known[t][:160]} for t in sorted(failing) if t in known],
        "peer_route": [reported[t] for t in sorted(reported)][:50],
        "surveyed": sorted(surveyed),
        "tools": tools,
        "requests": requests,
    }


async def run_survey(root: Optional[Path] = None, timeout: float = TIMEOUT_S) -> Dict[str, Any]:
    """Run the survey sealed in a child process and read it by the gate's rule. Never raises."""
    t0 = time.monotonic()
    try:
        root = Path(root) if root else tests_dir()
        script, gate = root / SURVEY, root / GATE
        if not script.is_file() or not gate.is_file():
            return {"measured": False, "reason": f"this image carries no request survey ({root.name}/{SURVEY})"}
        gated, known = read_rule(gate)
    except Exception as e:  # noqa: BLE001 — a reading, never a crash of the sweep
        return {"measured": False, "reason": f"the gate's rule could not be read ({type(e).__name__}: {str(e)[:120]})"}
    with tempfile.TemporaryDirectory(prefix="mcp-survey-") as d:
        out = Path(d) / "survey.json"
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", SEAL, str(script), "all", "--json", str(out),
                cwd=str(root), env=sealed_env(root.parent / "src", d), stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        except Exception as e:  # noqa: BLE001
            return {"measured": False, "reason": f"the survey could not start ({type(e).__name__}: {str(e)[:120]})"}
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"measured": False, "reason": f"the survey did not finish in {int(timeout)} s"}
        secs = round(time.monotonic() - t0, 1)
        if proc.returncode != 0 or not out.is_file():
            last = (err or b"").decode(errors="replace").strip().splitlines()[-1:] or [""]
            return {"measured": False, "seconds": secs,
                    "reason": f"the survey exited {proc.returncode} ({last[0][:160]})"}
        try:
            survey = json.loads(out.read_text())
        except Exception as e:  # noqa: BLE001
            return {"measured": False, "seconds": secs, "reason": f"the survey wrote no JSON ({type(e).__name__})"}
    result = verdict(survey, gated, known)
    result["seconds"] = secs
    return result


def flow_values(result: Dict[str, Any]) -> Dict[str, Any]:
    """The sweep's F.3 keys (the router, the history and the console read these names)."""
    measured = result.get("measured") is True
    return {
        "wrapper_drift": int(result.get("drift") or 0) if measured else 0,
        "wrapper_drift_details": list(result.get("details") or []) if measured else [],
        "wrapper_drift_measured": measured,
        "wrapper_drift_known": list(result.get("known") or []) if measured else [],
        "wrapper_peer_route": list(result.get("peer_route") or []) if measured else [],
        "wrapper_drift_surveyed": int(result.get("tools") or 0) if measured else 0,
        "wrapper_drift_surveyed_tools": list(result.get("surveyed") or []) if measured else [],
        "wrapper_drift_reason": None if measured else (result.get("reason") or "not measured"),
        "wrapper_drift_source": SOURCE,
        "wrapper_drift_seconds": result.get("seconds"),
    }
