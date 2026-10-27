"""SPIRE federation check — both frames' SPIRE servers must have a live
federation relationship with the other and refresh their bundle within ~10 min.

Per feedback_spire_federation_recurring.md: bundle injection is a band-aid;
proper `spire-server federation list` should show non-empty relationships.
"""

import re
import time

from ..schemas import CheckResult, RemediationHint

CHECK_ID = "spire-federation"
TITLE = "SPIRE federation relationships"
DESCRIPTION = "spire-server federation list must show ≥1 active relationship per mainframe."
CATEGORY = "spire"
COST_MS = 800


def applies(target: dict) -> bool:
    return target.get("role") == "mainframe"


_RELATIONSHIP_LINE = re.compile(r"trust\s*domain\s*:\s*(\S+)", re.IGNORECASE)
_REFRESH_LINE = re.compile(r"last\s*refresh.*?(\d+)", re.IGNORECASE)


async def run(target: dict, probe) -> CheckResult:
    started = time.monotonic()
    spire_container = target["containers"].get("spire_server")
    if not spire_container:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="unknown",
            latency_ms=int((time.monotonic() - started) * 1000),
            summary="no spire_server container configured",
        )

    exit_code, output = await probe.exec_in(
        spire_container,
        ["/opt/spire/bin/spire-server", "federation", "list"],
        timeout=6,
    )
    latency_ms = int((time.monotonic() - started) * 1000)

    if exit_code != 0:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=latency_ms,
            summary=f"spire-server exec failed (rc={exit_code})",
            evidence=output[:1024],
            remediation=RemediationHint(
                action_id="manual-investigate",
                description="federate through the frame invitation rail: approve and finalize set the SPIRE relationship and the peer's bundle, and the cert-writers carry the peer root to every sidecar within a cycle (the Frame-A-era manual bundle injection is retired, §F6 group 4)",
                destructive=False,
            ),
        )

    # Two cases the SPIRE CLI uses:
    #   "Found 0 federation relationships" → broken
    #   "Found N federation relationships" + per-relationship blocks → look for ≥1 trust domain
    domains = _RELATIONSHIP_LINE.findall(output)
    found_match = re.search(r"Found\s+(\d+)\s+federation\s+relationships?", output, re.IGNORECASE)
    relationship_count = int(found_match.group(1)) if found_match else len(domains)

    details = {
        "relationship_count": relationship_count,
        "trust_domains": domains[:10],
    }

    if relationship_count == 0:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=latency_ms,
            summary="0 federation relationships configured",
            details=details,
            evidence=output[:1024],
            remediation=RemediationHint(
                action_id="manual-investigate",
                description="federate through the frame invitation rail: approve and finalize set the SPIRE relationship and the peer's bundle, and the cert-writers carry the peer root to every sidecar within a cycle (the Frame-A-era manual bundle injection is retired, §F6 group 4)",
                destructive=False,
            ),
        )
    return CheckResult(
        check_id=CHECK_ID,
        target=target["operator_id"],
        status="ok",
        latency_ms=latency_ms,
        summary=f"{relationship_count} relationship(s) configured",
        details=details,
        evidence=output[:1024],
    )
