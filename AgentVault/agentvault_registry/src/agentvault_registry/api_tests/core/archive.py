"""Run archive writer (AAA+ Phase V, 2026-05-21).

Each baseline / chained-frame / dual-frame run gets a timestamped folder under
/opt/theprotocol/backups_v2/api_tester_runs/<run_kind>/<YYYY-MM-DD_HHMMSS>/ with:

  - results.jsonl       — one JSON object per endpoint result
  - summary.json        — totals + run kind + metadata
  - timing.json         — per-endpoint timings
  - metadata.json       — env vars, container image hashes, sandbox state
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 2026-08-07 (§MCPTEST-FE): a run id / kind becomes a DIRECTORY NAME, so it is
# attacker-controlled path input. Whitelist, never blacklist, and re-check the
# resolved path is still under the root — a caller could otherwise publish a run
# named "../../etc" and write outside the archive.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

# §TESTERARCHIVE (2026-09-09) — the default must not name ANOTHER DEPLOYMENT'S PATH.
#
# It used to be "/opt/theprotocol/backups_v2/api_tester_runs", which is a HOST directory Frame A
# bind-mounts. Frame A also sets API_TESTER_ARCHIVE_ROOT explicitly, so Frame A was fine and the
# default was never exercised there. Any OTHER console fell through to it and tried to write a host
# path that does not exist inside its container: measured on EU, 300 of 300 publishes from a
# frontend run answered 500 "[Errno 13] Permission denied: '/opt/theprotocol'". The tests all RAN;
# only the history was lost, which is the half a person actually wanted.
#
# Same family as §CARDLINK's foreign catalog: a default that describes one deployment is a claim
# about every other one. /app/data is the registry's own writable volume on every frame, so the
# fallback now belongs to whoever is running. An operator wanting it elsewhere still sets the env.
ARCHIVE_ROOT = Path(os.environ.get(
    "API_TESTER_ARCHIVE_ROOT",
    "/app/data/api_tester_runs",
))


def new_run_dir(run_kind: str, started_at: Optional[datetime] = None) -> Path:
    """Allocate a fresh run directory under ARCHIVE_ROOT/<run_kind>/<timestamp>/."""
    ts = (started_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d_%H%M%S")
    p = ARCHIVE_ROOT / run_kind / ts
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_results(run_dir: Path, results: List[Dict[str, Any]]) -> Path:
    out = run_dir / "results.jsonl"
    with open(out, "w") as f:
        for r in results:
            f.write(json.dumps(r, default=str) + "\n")
    return out


def write_summary(run_dir: Path, summary: Dict[str, Any]) -> Path:
    out = run_dir / "summary.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    return out


def write_metadata(run_dir: Path, extra: Optional[Dict[str, Any]] = None) -> Path:
    """Capture environmental metadata: hostname, env vars, sandbox state."""
    meta: Dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "env": {
            k: v for k, v in os.environ.items()
            if k.startswith(("API_TEST_", "OPA_", "SANDBOX_", "ES_EVENT_", "FIAT_"))
        },
    }
    if extra:
        meta["extra"] = extra
    out = run_dir / "metadata.json"
    with open(out, "w") as f:
        json.dump(meta, f, indent=2, default=str)
    return out


def write_timing(run_dir: Path, results: List[Dict[str, Any]]) -> Path:
    """Per-endpoint timing summary + percentiles."""
    timings_ms = [
        r.get("responseTime") or r.get("response_time_ms") or 0
        for r in results
        if r.get("responseTime") is not None or r.get("response_time_ms") is not None
    ]
    timings_ms.sort()
    n = len(timings_ms)

    def pct(p: float) -> float:
        if not n:
            return 0.0
        idx = min(n - 1, int(n * p / 100))
        return timings_ms[idx]

    summary = {
        "endpoint_count": n,
        "p50_ms": pct(50),
        "p95_ms": pct(95),
        "p99_ms": pct(99),
        "max_ms": max(timings_ms) if timings_ms else 0,
        "total_ms": sum(timings_ms),
        "per_endpoint": [
            {
                "method": r.get("method"),
                "path": r.get("path"),
                "ms": r.get("responseTime") or r.get("response_time_ms"),
                "status": r.get("status_code"),
            }
            for r in results
            if r.get("responseTime") or r.get("response_time_ms")
        ],
    }
    out = run_dir / "timing.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    return out


def archive_run(
    run_kind: str,
    results: List[Dict[str, Any]],
    summary: Dict[str, Any],
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Path:
    """One-shot archive: writes results + summary + metadata + timing.

    Returns the run directory path.
    """
    rd = new_run_dir(run_kind)
    write_results(rd, results)
    write_summary(rd, summary)
    write_metadata(rd, extra_metadata)
    write_timing(rd, results)
    logger.info(f"Run archived: {rd}")
    return rd


def _safe_run_dir(run_kind: str, run_id: str) -> Path:
    """Resolve ARCHIVE_ROOT/<run_kind>/<run_id>, refusing anything that escapes."""
    for part in (run_kind, run_id):
        if not _SAFE_NAME_RE.match(part or ""):
            raise ValueError(f"unsafe archive path component: {part!r}")
    root = ARCHIVE_ROOT.resolve()
    p = (ARCHIVE_ROOT / run_kind / run_id).resolve()
    if root != p and root not in p.parents:
        raise ValueError("archive path escapes ARCHIVE_ROOT")
    return p


def _result_key(r: Dict[str, Any]) -> str:
    return f"{(r.get('method') or '').upper()} {r.get('path') or ''}"


def read_results(run_dir: Path) -> List[Dict[str, Any]]:
    f = run_dir / "results.jsonl"
    if not f.exists():
        return []
    out: List[Dict[str, Any]] = []
    with open(f) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def upsert_run(
    run_kind: str,
    run_id: str,
    results: List[Dict[str, Any]],
    summary: Dict[str, Any],
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Incrementally publish a run.

    The frontend runs the sweep client-side and publishes after each category,
    so a run is visible WHILE it is happening and survives the browser session
    that produced it. `results` is a DELTA — merged onto whatever the run
    already holds, keyed by "METHOD path", so a re-tested endpoint overwrites
    its old row instead of duplicating it.
    """
    rd = _safe_run_dir(run_kind, run_id)
    rd.mkdir(parents=True, exist_ok=True)

    merged: Dict[str, Dict[str, Any]] = {_result_key(r): r for r in read_results(rd)}
    for r in results:
        merged[_result_key(r)] = r
    all_results = list(merged.values())

    write_results(rd, all_results)
    write_summary(rd, {**summary, "run_kind": run_kind, "run_id": run_id,
                       "result_count": len(all_results),
                       "updated_at": datetime.now(timezone.utc).isoformat()})
    write_metadata(rd, extra_metadata)
    write_timing(rd, all_results)
    return {"run_dir": str(rd), "result_count": len(all_results)}


def latest_run(run_kind: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Newest run that has a summary, with its full result set."""
    runs = list_runs(run_kind=run_kind, limit=1)
    if not runs:
        return None
    rd = Path(runs[0]["run_dir"])
    return {
        "run_dir": str(rd),
        "summary": runs[0]["summary"],
        "results": read_results(rd),
    }


def list_runs(run_kind: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """List recent runs (newest first)."""
    if run_kind:
        base = ARCHIVE_ROOT / run_kind
        if not base.exists():
            return []
        dirs = sorted(base.iterdir(), reverse=True)
    else:
        if not ARCHIVE_ROOT.exists():
            return []
        dirs = []
        for kind_dir in ARCHIVE_ROOT.iterdir():
            if kind_dir.is_dir():
                for run_dir in kind_dir.iterdir():
                    if run_dir.is_dir():
                        dirs.append((run_dir.stat().st_mtime, run_dir, kind_dir.name))
        dirs.sort(reverse=True)
        dirs = [d for _, d, _ in dirs]

    out = []
    for d in dirs[:limit]:
        try:
            summary_file = d / "summary.json"
            if summary_file.exists():
                with open(summary_file) as f:
                    s = json.load(f)
                out.append({
                    "run_dir": str(d),
                    "summary": s,
                })
        except Exception as e:
            logger.warning(f"list_runs: skipping {d}: {e!r}")
    return out
