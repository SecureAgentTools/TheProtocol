"""One of this frame's operators, as its federation record says (§MCPTEST30 V0562).

The peer row the federation fan-out stamps on every attempt (last_synced_at, consecutive failures, the last error),
read through the compliance page's own classifier (services/federation_reachability.classify): OK, STALE, UNREACHABLE,
NEVER_SYNCED, PENDING. No Docker socket and no new dial: the fan-out already asked.
"""

import time

from ..schemas import CheckResult, RemediationHint

CHECK_ID = "operator-federation-reach"
TITLE = "Operator answers the federation"
DESCRIPTION = "This frame's operator answered the federation fan-out recently (its peer row's own record)."
CATEGORY = "network"
COST_MS = 20

_STATUS = {"ok": "ok", "info": "unknown", "warning": "warn", "critical": "fail"}


def applies(target: dict) -> bool:
    return target.get("role") == "operator" and bool(target.get("peer_registry_id"))


async def load_peer(peer_id: int):
    """The peer row, fresh (the target list may be minutes old). None when it cannot be read."""
    from sqlalchemy import select
    from agentvault_registry import models
    from agentvault_registry.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(models.PeerRegistry).where(models.PeerRegistry.id == peer_id))).scalar_one_or_none()


async def run(target: dict, probe) -> CheckResult:
    from agentvault_registry.services import federation_reachability as fr
    started = time.monotonic()

    def result(status, summary, **kw):
        return CheckResult(check_id=CHECK_ID, target=target["operator_id"], status=status,
                           latency_ms=int((time.monotonic() - started) * 1000), summary=summary, **kw)

    try:
        peer = await load_peer(int(target["peer_registry_id"]))
    except Exception as e:  # noqa: BLE001
        return result("unknown", f"not measured: the peer row could not be read ({type(e).__name__})")
    if peer is None:
        return result("unknown", "not measured: the peer row is gone")
    c = fr.classify(peer)
    age = c.get("last_sync_age_seconds")
    when = "never" if age is None else (f"{age // 60} min ago" if age < 7200 else f"{age // 3600} h ago")
    summary = f"{c['state']}: last answered {when}, {c['consecutive_sync_failures']} failure(s) in a row"
    if c.get("diagnosis"):
        summary += f" ({c['diagnosis']})"
    status = _STATUS.get(c.get("severity"), "unknown")
    hint = None
    if status in ("warn", "fail") and c.get("remedy"):
        hint = RemediationHint(action_id="manual-investigate", description=c["remedy"][:400], destructive=False)
    return result(status, summary, details={k: c.get(k) for k in ("state", "last_synced_at", "last_sync_attempt_at",
                                                                     "consecutive_sync_failures", "last_sync_error")},
                  remediation=hint)
