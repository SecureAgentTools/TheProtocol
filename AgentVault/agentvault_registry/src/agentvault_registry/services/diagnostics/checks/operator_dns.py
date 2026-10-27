"""Operator DNS resolution check (operator only).

A registry that can't resolve federation peer hostnames will throw
"Temporary failure in name resolution" repeatedly. >3 hits → fail.
"""

import re
import time

from ..schemas import CheckResult, RemediationHint

CHECK_ID = "operator-dns-errors"
TITLE = "Operator DNS errors"
DESCRIPTION = "Counts 'Temporary failure in name resolution' errors in operator registry logs."
CATEGORY = "network"
COST_MS = 600

# Time-bounded window — see §CCFIX note in run().
_WINDOW = "30m"

_DNS_FAIL_RE = re.compile(r"Temporary failure in name resolution", re.IGNORECASE)


def applies(target: dict) -> bool:
    return target.get("role") == "operator"


async def run(target: dict, probe) -> CheckResult:
    started = time.monotonic()
    registry_container = target["containers"].get("registry")
    if not registry_container:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="unknown",
            latency_ms=int((time.monotonic() - started) * 1000),
            summary="no registry container configured",
        )
    # §CCFIX (2026-07-28): this counted DNS errors in a rolling 2000-LINE tail, so errors that
    # were fixed days ago (the §DNSFIX/§EXTRAHOSTS work on 2026-07-26) kept re-triggering `fail`
    # until they happened to scroll out — and on a quiet operator 2000 lines can span many hours.
    # That is what made op-qatest16 flap fail<->ok. A health check must describe the PRESENT, so
    # the window is now bounded by TIME; the line cap only protects the event loop.
    log_excerpt = await probe.logs(
        registry_container,
        since=_WINDOW,
        tail=2000,
        grep_pattern=r"Temporary failure in name resolution|getaddrinfo",
        max_bytes=4096,
    )
    latency_ms = int((time.monotonic() - started) * 1000)
    dns_errors = len(_DNS_FAIL_RE.findall(log_excerpt))
    details = {"dns_resolution_errors_recent": dns_errors, "window": _WINDOW}
    if dns_errors > 3:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=latency_ms,
            summary=f"{dns_errors} DNS resolution errors in the last {_WINDOW}",
            details=details,
            evidence=log_excerpt[-2048:],
            remediation=RemediationHint(
                action_id="manual-investigate",
                description="the operator's compose names this frame's identity network and its aliases: recreating the service (the operator page's restart through the operator lifecycle, or a teardown and provision) re-attaches it (the Frame-A-era reconnect action is retired, §F6 group 4: it joined Frame A's network from any frame)",
                destructive=False,
            ),
        )
    if dns_errors > 0:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="warn",
            latency_ms=latency_ms,
            summary=f"{dns_errors} DNS error(s) in the last {_WINDOW} (below fail threshold)",
            details=details,
        )
    return CheckResult(
        check_id=CHECK_ID,
        target=target["operator_id"],
        status="ok",
        latency_ms=latency_ms,
        summary="no DNS errors in recent logs",
        details=details,
    )
