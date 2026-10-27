"""pgbouncer reachability (operator-only).

The cloud operator stack relies on Docker DNS to find pgbouncer — they don't
use the `extra_hosts` IP-pinning pattern. So this check just verifies the
pgbouncer container is up and reachable on its TCP listen port (6432 for
operator pgbouncers) from the registry.
"""

import time

from ..probe import probe_failed
from ..schemas import CheckResult, RemediationHint

CHECK_ID = "pgbouncer-reachable"
TITLE = "pgbouncer reachability"
DESCRIPTION = "Operator pgbouncer container must be running and reachable on port 6432 from the registry."
CATEGORY = "config"
COST_MS = 400

PGBOUNCER_PORT = 6432


def applies(target: dict) -> bool:
    containers = target.get("containers", {})
    return "pgbouncer" in containers and "registry" in containers


async def run(target: dict, probe) -> CheckResult:
    started = time.monotonic()
    pgbouncer = target["containers"]["pgbouncer"]
    registry = target["containers"]["registry"]

    if not await probe.container_exists(pgbouncer):
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=int((time.monotonic() - started) * 1000),
            summary=f"pgbouncer container {pgbouncer} not found",
        )

    pgbouncer_status = await probe.container_status(pgbouncer)
    if pgbouncer_status != "running":
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=int((time.monotonic() - started) * 1000),
            summary=f"pgbouncer container status: {pgbouncer_status}",
            details={"pgbouncer_status": pgbouncer_status},
            remediation=RemediationHint(
                action_id="manual-investigate",
                description="pgbouncer is not running — start it via docker-compose.",
                destructive=False,
            ),
        )

    # Brief TCP probe via bash's /dev/tcp from inside the registry container.
    # `timeout 1 bash -c 'echo > /dev/tcp/host/port'` returns 0 on connect,
    # non-zero otherwise. Cheap and avoids needing nc/curl in the image.
    rc, tcp_out = await probe.exec_in(
        registry,
        [
            "bash",
            "-c",
            f"timeout 2 bash -c 'echo > /dev/tcp/pgbouncer/{PGBOUNCER_PORT}' && echo OK || echo FAIL",
        ],
        timeout=8,
    )
    latency_ms = int((time.monotonic() - started) * 1000)

    details = {
        "pgbouncer_container": pgbouncer,
        "pgbouncer_status": pgbouncer_status,
        "tcp_probe": tcp_out.strip()[:64],
    }

    # §CCFIX: distinguish "pgbouncer refused the connection" from "we never got to ask".
    if probe_failed(rc):
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="unknown",
            latency_ms=latency_ms,
            summary="probe could not run the TCP check (timeout/exec error) — pgbouncer state unknown",
            details=details,
            evidence=tcp_out[:512],
        )

    if "OK" not in tcp_out:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="warn",
            latency_ms=latency_ms,
            summary=f"pgbouncer running but TCP {PGBOUNCER_PORT} probe failed",
            details=details,
            evidence=tcp_out[:512],
        )

    return CheckResult(
        check_id=CHECK_ID,
        target=target["operator_id"],
        status="ok",
        latency_ms=latency_ms,
        summary=f"pgbouncer running, TCP {PGBOUNCER_PORT} reachable from registry",
        details=details,
    )
