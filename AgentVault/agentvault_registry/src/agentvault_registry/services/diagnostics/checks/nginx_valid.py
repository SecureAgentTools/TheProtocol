"""nginx configuration validity check (operator only).

Runs `nginx -t` inside the operator's nginx-federation container. Non-zero
exit → fail. Frame A's federation is fronted by host nginx (out of scope).
"""

import time

from ..probe import probe_failed
from ..schemas import CheckResult, RemediationHint

CHECK_ID = "nginx-config-valid"
TITLE = "nginx config validity"
DESCRIPTION = "Runs `nginx -t` against the operator's nginx-federation container."
CATEGORY = "config"
COST_MS = 400


def applies(target: dict) -> bool:
    return "nginx_federation" in target.get("containers", {})


async def run(target: dict, probe) -> CheckResult:
    started = time.monotonic()
    container = target["containers"]["nginx_federation"]

    exit_code, output = await probe.exec_in(container, ["nginx", "-t"], timeout=8)
    latency_ms = int((time.monotonic() - started) * 1000)

    summary = output.strip().splitlines()[-1] if output.strip() else "(no output)"
    details = {"exit_code": exit_code, "container": container}

    # §CCFIX: a docker-exec timeout/daemon error is NOT a broken nginx config. Reporting
    # `fail` for it accused three healthy operators of invalid config and made this check
    # flap fail<->ok. Probe failure is `unknown` — we did not learn anything about nginx.
    if probe_failed(exit_code):
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="unknown",
            latency_ms=latency_ms,
            summary="probe could not run `nginx -t` (timeout/exec error) — config state unknown",
            details=details,
            evidence=output[-512:],
        )

    if exit_code != 0:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=latency_ms,
            summary=summary[:160],
            details=details,
            evidence=output[-1024:],
            remediation=RemediationHint(
                action_id="manual-investigate",
                description="Operator nginx-federation config rejected — fix before reload.",
                destructive=False,
            ),
        )
    return CheckResult(
        check_id=CHECK_ID,
        target=target["operator_id"],
        status="ok",
        latency_ms=latency_ms,
        summary="syntax ok",
        details=details,
        evidence=output[-512:],
    )
