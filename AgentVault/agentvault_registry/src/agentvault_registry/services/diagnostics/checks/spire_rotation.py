"""SPIRE SVID rotation check.

The cert-writer container refreshes /certs/svid.0.pem every ~5 min. Rather
than scrape logs, we check the file's mtime directly — if it's recent the
rotation pipeline is healthy.
"""

import time
from datetime import datetime, timezone

from ..probe import probe_failed
from ..schemas import CheckResult, RemediationHint

CHECK_ID = "spire-cert-rotation"
TITLE = "SPIRE cert rotation"
DESCRIPTION = "Verifies the SVID PEM file mtime is fresh — cert-writer should refresh ~every 5 min."
CATEGORY = "certs"
COST_MS = 200

# Try the canonical SPIRE bundle path first, then legacy/alt locations.
_CANDIDATE_PATHS = (
    "/certs/svid.0.pem",
    "/run/spire/agent/svid.0.pem",
    "/tmp/svid.0.pem",
)


def applies(target: dict) -> bool:
    return target.get("role") in ("mainframe", "operator")


async def run(target: dict, probe) -> CheckResult:
    started = time.monotonic()
    witness_role = target.get("svid_witness", "registry")
    container = target["containers"].get(witness_role) or target["containers"].get("registry")
    if not container:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="unknown",
            latency_ms=int((time.monotonic() - started) * 1000),
            summary=f"no {witness_role!r} container configured",
        )

    mtime: float | None = None
    used_path: str | None = None
    last_evidence = ""
    # §CCFIX: remember whether the PROBE failed (timeout/daemon error) as opposed to the file
    # genuinely not being there. Reporting "no SVID found" when docker exec merely timed out is
    # a false statement about a healthy target, and it is what made this check flap ok<->unknown.
    probe_broke = False
    for path in _CANDIDATE_PATHS:
        rc, out = await probe.exec_in(container, ["stat", "-c", "%Y", path], timeout=6)
        last_evidence = out
        if probe_failed(rc):
            probe_broke = True
        if rc == 0:
            try:
                mtime = float(out.strip())
                used_path = path
                break
            except ValueError:
                continue

    latency_ms = int((time.monotonic() - started) * 1000)

    if mtime is None:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="unknown",
            latency_ms=latency_ms,
            summary=(
                "probe could not read the SVID (docker exec timeout/error) — target state unknown"
                if probe_broke else "no SVID found at known paths"
            ),
            details={"paths_tried": list(_CANDIDATE_PATHS), "probe_failed": probe_broke},
            evidence=last_evidence[:512],
        )

    age_seconds = max(0, time.time() - mtime)
    age_minutes = int(age_seconds / 60)
    rotated_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    details = {
        "path": used_path,
        "rotated_at": rotated_at,
        "age_minutes": age_minutes,
    }

    if age_minutes > 120:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=latency_ms,
            summary=f"SVID stale: rotated {age_minutes} min ago (>120 threshold)",
            details=details,
            remediation=RemediationHint(
                action_id="manual-investigate",
                description="cert-writer is silent — inspect its container logs.",
                destructive=False,
            ),
        )
    if age_minutes > 30:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="warn",
            latency_ms=latency_ms,
            summary=f"SVID rotation slowing: {age_minutes} min since last refresh",
            details=details,
        )
    return CheckResult(
        check_id=CHECK_ID,
        target=target["operator_id"],
        status="ok",
        latency_ms=latency_ms,
        summary=f"refreshed {age_minutes} min ago",
        details=details,
    )
