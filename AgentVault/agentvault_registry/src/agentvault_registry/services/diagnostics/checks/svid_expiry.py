"""SVID expiry check.

Reads SVID PEM files from the registry container's /certs (or /tmp) volume
and inspects their notAfter timestamp. <30 min remaining → fail.
"""

import re
import time
from datetime import datetime, timezone

from ..probe import probe_failed
from ..schemas import CheckResult, RemediationHint

CHECK_ID = "svid-expiry"
TITLE = "SVID expiry"
DESCRIPTION = "Container SVIDs must have >30 min until expiry."
CATEGORY = "certs"
COST_MS = 700

# Months -> ints for openssl date parsing fallback
_MONTHS = {
    m: i + 1 for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    )
}

# openssl emits "notAfter=Apr 19 12:34:56 2026 GMT"
_OPENSSL_DATE_RE = re.compile(
    r"notAfter=([A-Za-z]+)\s+(\d+)\s+(\d+):(\d+):(\d+)\s+(\d+)"
)


def _parse_openssl_date(stdout: str) -> datetime | None:
    m = _OPENSSL_DATE_RE.search(stdout)
    if not m:
        return None
    month_name, day, hh, mm, ss, year = m.groups()
    if month_name not in _MONTHS:
        return None
    return datetime(
        year=int(year),
        month=_MONTHS[month_name],
        day=int(day),
        hour=int(hh),
        minute=int(mm),
        second=int(ss),
        tzinfo=timezone.utc,
    )


def applies(target: dict) -> bool:
    # V0562: this registry reads its own file; anyone else's SVID needs a container to read it in
    return bool(target.get("self")) or (target.get("role") in ("mainframe", "operator") and bool(target.get("containers")))


async def _read_in_container(target: dict, probe):
    """(notAfter, path, paths tried, evidence, probe_broke) read through docker exec in the target's witness container;
    paths tried is None (and evidence the sentence) when the target names no such container."""
    witness_role = target.get("svid_witness", "registry")
    container = target["containers"].get(witness_role) or target["containers"].get("registry")
    if not container:
        return None, None, None, f"no {witness_role!r} container configured", False

    # SPIRE bundles default to /certs/svid.0.pem; frame-B mounts at /run/spire,
    # legacy installs use /tmp.
    cert_paths_to_try = [
        "/certs/svid.0.pem",
        "/run/spire/agent/svid.0.pem",
        "/tmp/svid.0.pem",
    ]
    notAfter: datetime | None = None
    last_evidence = ""
    used_path: str | None = None
    # §CCFIX — see spire_rotation: a docker-exec timeout is NOT evidence that the SVID is absent.
    probe_broke = False
    for path in cert_paths_to_try:
        rc, stdout = await probe.exec_in(
            container,
            ["openssl", "x509", "-in", path, "-enddate", "-noout"],
            timeout=8,
        )
        last_evidence = stdout
        if probe_failed(rc):
            probe_broke = True
        if rc == 0:
            parsed = _parse_openssl_date(stdout)
            if parsed:
                notAfter = parsed
                used_path = path
                break

    return notAfter, used_path, cert_paths_to_try, last_evidence, probe_broke


async def run(target: dict, probe) -> CheckResult:
    started = time.monotonic()
    if target.get("self"):
        # §MCPTEST30 (V0562): this registry's own SVID, read from its own certificate directory (no docker exec: the
        # registry IS the process whose SVID this is, and frames without a Docker socket could never exec anyway)
        from agentvault_registry.services import trust_bundle
        used_path = trust_bundle.svid_path()
        cert_paths_to_try = [used_path]
        text, err = trust_bundle.read(used_path)
        notAfter = trust_bundle.leaf_not_after(text) if text else None
        last_evidence, probe_broke = err or "", False
    else:
        notAfter, used_path, cert_paths_to_try, last_evidence, probe_broke = await _read_in_container(target, probe)
        if cert_paths_to_try is None:
            return CheckResult(
                check_id=CHECK_ID,
                target=target["operator_id"],
                status="unknown",
                latency_ms=int((time.monotonic() - started) * 1000),
                summary=last_evidence,
            )
    latency_ms = int((time.monotonic() - started) * 1000)

    if not notAfter:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="unknown",
            latency_ms=latency_ms,
            summary=(
                "probe could not read the SVID (docker exec timeout/error) — target state unknown"
                if probe_broke else "no SVID found at known paths"
            ),
            details={"paths_tried": cert_paths_to_try, "probe_failed": probe_broke},
            evidence=last_evidence[:1024],
        )

    seconds_left = (notAfter - datetime.now(timezone.utc)).total_seconds()
    minutes_left = int(seconds_left / 60)
    details = {
        "path": used_path,
        "notAfter": notAfter.isoformat(),
        "minutes_remaining": minutes_left,
    }

    if minutes_left < 0:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=latency_ms,
            summary=f"SVID EXPIRED {abs(minutes_left)} min ago",
            details=details,
            evidence=last_evidence[:512],
            remediation=RemediationHint(
                action_id="manual-investigate",
                description="cert-writer is broken — manual SVID push needed.",
                destructive=False,
            ),
        )
    if minutes_left < 30:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=latency_ms,
            summary=f"SVID expires in {minutes_left} min (<30 threshold)",
            details=details,
            evidence=last_evidence[:512],
        )
    return CheckResult(
        check_id=CHECK_ID,
        target=target["operator_id"],
        status="ok",
        latency_ms=latency_ms,
        summary=f"SVID expires in {minutes_left} min",
        details=details,
    )
