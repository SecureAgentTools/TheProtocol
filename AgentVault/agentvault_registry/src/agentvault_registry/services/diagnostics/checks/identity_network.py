"""Identity network alias check — every TEG and nginx-federation we know about
must be attached to THIS frame's identity network with the documented alias.

Source: project_cross_teg_networking.md. §F6 group 4 (2026-09-27): the network is the frame's own, read from
IDENTITY_NETWORK (the variable the operator provisioner renders into every operator's compose); the check named
agentvault_identity_network, Frame A's, so on any other frame it judged every operator missing from a network that was
never theirs. The suggested reconnect action is retired: it joined Frame A's network.
"""

import os
import time

from ..schemas import CheckResult, RemediationHint

CHECK_ID = "identity-network-aliases"
TITLE = "Identity-network aliases"
DESCRIPTION = "Verifies the target's TEG and nginx-federation are on this frame's identity network (IDENTITY_NETWORK) with their expected aliases."
CATEGORY = "network"
COST_MS = 400

NETWORK_NAME = "agentvault_identity_network"   # the default when IDENTITY_NETWORK is unset (Frame A's own)


def network_name() -> str:
    """This frame's identity network: the same variable and default the operator provisioner renders."""
    return os.getenv("IDENTITY_NETWORK") or NETWORK_NAME


def applies(target: dict) -> bool:
    # §MCPTEST30 (V0562): a target whose containers it names (this registry itself names none: it is the process asking,
    # and it reached Redis, its store and its TEG to be running the check at all)
    return bool(target.get("containers"))


async def run(target: dict, probe) -> CheckResult:
    started = time.monotonic()
    network = await probe.network_inspect(network_name())
    latency_ms = int((time.monotonic() - started) * 1000)

    if "error" in network:
        # §MCPTEST30 (V0562): a network Docker says does not exist is a finding; a probe that could not ask (no socket,
        # a daemon error) knows nothing about the target, and "fail" said it did (the §CCFIX rule, probe.probe_failed)
        missing = "not found" in str(network["error"]).lower()
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail" if missing else "unknown",
            latency_ms=latency_ms,
            summary=(f"the identity network {network_name()!r} does not exist" if missing
                     else f"not measured: the probe could not ask Docker ({str(network['error'])[:100]})"),
            evidence=str(network)[:1024],
        )

    containers = network.get("Containers", {})
    attached_names = {c.get("Name") for c in containers.values() if c.get("Name")}
    expected = {
        name: target["containers"][name]
        for name in ("teg", "nginx_federation")
        if name in target["containers"]
    }

    missing = {role: name for role, name in expected.items() if name not in attached_names}
    details = {
        "expected": expected,
        "attached_count": len(attached_names),
        "missing": missing,
        "network": network_name(),
    }

    if missing:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=latency_ms,
            summary=f"missing on identity network: {', '.join(missing.values())}",
            details=details,
            evidence=", ".join(sorted(attached_names))[:1024],
            remediation=RemediationHint(
                action_id="manual-investigate",
                description="the operator's compose names this frame's identity network and its aliases: recreating the service (the operator page's restart through the operator lifecycle, or a teardown and provision) re-attaches it (the Frame-A-era reconnect action is retired, §F6 group 4: it joined Frame A's network from any frame)",
                destructive=False,
            ),
        )

    return CheckResult(
        check_id=CHECK_ID,
        target=target["operator_id"],
        status="ok",
        latency_ms=latency_ms,
        summary=f"{len(expected)} expected container(s) attached",
        details=details,
    )
