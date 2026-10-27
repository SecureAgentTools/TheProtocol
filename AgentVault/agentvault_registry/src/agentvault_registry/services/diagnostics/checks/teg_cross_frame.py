"""TEG cross-frame reach check — TEG-A logs in last 5000 log lines must show successful
HTTP 200 calls to frame-b nginx-federation, and zero CERTIFICATE_VERIFY_FAILED.

Source: feedback_spire_federation_recurring.md.
"""

import re
import time

from ..schemas import CheckResult, RemediationHint

CHECK_ID = "teg-cross-frame-reach"
TITLE = "TEG cross-frame reachability"
DESCRIPTION = "Mainframe TEGs must successfully reach the peer frame's nginx-federation in recent traffic."
CATEGORY = "teg"
COST_MS = 1200

# §CCFIX (2026-07-27): frame C was missing here, so a frame-c mainframe fell back to the
# frame-b default and looked for the wrong peer entirely. The FX triangle is A<->B<->C, so
# each frame accepts evidence from EITHER of its two peers.
_PEER_HOST_PATTERNS = {
    "A": r"frame-b|frame-c",
    "B": r"agentvault\.com|nginx-a|frame-c",
    "C": r"agentvault\.com|nginx-a|frame-b",
}


def applies(target: dict) -> bool:
    return target.get("role") == "mainframe"


async def run(target: dict, probe) -> CheckResult:
    started = time.monotonic()
    teg_container = target["containers"].get("teg")
    frame = target.get("frame", "A")
    peer_pat = _PEER_HOST_PATTERNS.get(frame, r"frame-b")
    if not teg_container:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="unknown",
            latency_ms=int((time.monotonic() - started) * 1000),
            summary="no teg container configured",
        )

    # Tail-bounded read keeps cost <2s even on busy TEGs. 5000 lines covers
    # the last ~5 min of typical traffic, which is plenty to detect cert
    # errors or circuit-open events without scanning hours of history.
    log_excerpt = await probe.logs(
        teg_container,
        tail=5000,
        grep_pattern=rf"({peer_pat}|CERTIFICATE_VERIFY_FAILED|circuit.*open)",
        max_bytes=32768,
    )
    latency_ms = int((time.monotonic() - started) * 1000)

    # §CCFIX (2026-07-27) — THIS CHECK COULD NEVER PASS ON THIS DEPLOYMENT.
    # It looked only for an nginx-style access line (`frame-b ... HTTP/1.1" 200`). The TEG is a
    # FastAPI service that emits STRUCTURED JSON logs and never writes that format, so the
    # success counter was pinned at 0 and registry-a warned "no cross-frame traffic observed"
    # forever — while the cross-frame canaries were running fine. Measured before changing it:
    # 49 of the last 5000 TEG-A lines mention frame-b, and 0 matched the old regex.
    # The real, and stronger, evidence is the peer completing an mTLS handshake against us:
    #   [TEG-AUTH] mode=mtls route=/api/v1/... spiffe=spiffe://frame-b.theprotocol.cloud/...
    # That is a verified cross-frame corridor, not an inference from a status code.
    # The old pattern is KEPT so any deployment that does front TEG with nginx still passes.
    # NOTE the `(?:...)` — `peer_pat` is an ALTERNATION, and without the group
    # `frame-b|frame-c.*HTTP/1.x.*200` parses as "frame-b" OR "frame-c...200", i.e. it matches
    # any line that merely MENTIONS the peer and reports a bogus success. That precedence bug
    # was already latent in the original for frame B (`agentvault\.com|nginx-a`), where it made
    # the check pass on nothing. Caught by replaying old-vs-new against real logs and getting an
    # implausibly round 100 (the tail cap) instead of the 0 a direct grep gave.
    nginx_style = len(re.findall(rf"(?:{peer_pat}).*HTTP/1\.[01].*200", log_excerpt))
    peer_mtls = len(re.findall(
        rf"TEG-AUTH.*mode=mtls.*spiffe=spiffe://(?:{peer_pat})", log_excerpt))
    success_hits = nginx_style + peer_mtls
    cert_errors = len(re.findall(r"CERTIFICATE_VERIFY_FAILED", log_excerpt))
    circuit_open = len(re.findall(r"circuit.*open", log_excerpt, re.IGNORECASE))

    # Keys used to claim `_last_2h` while the window is a 5000-LINE tail — on a busy TEG that is
    # roughly 15 minutes, not 2 hours. Renamed so the evidence does not misdescribe itself.
    details = {
        "success_hits_in_window": success_hits,
        "peer_mtls_handshakes_in_window": peer_mtls,
        "nginx_access_hits_in_window": nginx_style,
        "cert_verify_errors_in_window": cert_errors,
        "circuit_open_events_in_window": circuit_open,
        "window": "last 5000 log lines",
    }
    evidence = log_excerpt[-2048:] if log_excerpt else "(no matching log lines)"

    if cert_errors > 0:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=latency_ms,
            summary=f"{cert_errors} CERTIFICATE_VERIFY_FAILED in last 5000 log lines",
            details=details,
            evidence=evidence,
            remediation=RemediationHint(
                action_id="manual-investigate",
                description="federate through the frame invitation rail: approve and finalize set the SPIRE relationship and the peer's bundle, and the cert-writers carry the peer root to every sidecar within a cycle (the Frame-A-era manual bundle injection is retired, §F6 group 4)",
                destructive=False,
            ),
        )
    if success_hits == 0 and circuit_open > 0:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="warn",
            latency_ms=latency_ms,
            summary=f"no successful cross-frame hits, {circuit_open} circuit-open event(s)",
            details=details,
            evidence=evidence,
        )
    if success_hits == 0:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="warn",
            latency_ms=latency_ms,
            summary="no cross-frame traffic observed in last 5000 log lines (could be quiet, not necessarily broken)",
            details=details,
            evidence=evidence,
        )
    return CheckResult(
        check_id=CHECK_ID,
        target=target["operator_id"],
        status="ok",
        latency_ms=latency_ms,
        summary=f"{success_hits} successful cross-frame call(s) in last 5000 log lines, no cert errors",
        details=details,
        evidence=evidence,
    )
