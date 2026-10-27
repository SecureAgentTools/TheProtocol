"""D6-272 (2026-10-17) — the sender of owed cross-registry delegation revokes (xreg_revokes_owed, migration
0194_delivery_xreg_revoke).

Why it exists: an issuer's revoke is recorded on this registry first (the issuer-side record the delegate's registry asks
at use), and its message to the delegate's registry was sent once. A delegate registry that was down when the issuer
revoked kept its grant row live; one that does not ask the issuer at use kept honouring it until it expired. The route
now records a send that did not land as owed, in the transaction of the issuer-side record, and this worker sends it
again with the same request (services/xreg_revoke_delivery.send_revoke) until the delegate's registry takes it.

Leader-elected through `_worker_base.BackgroundWorker`. No database transaction is held while a peer is asked: the due
rows are read, the read is ended, and each row is written after its own send. The decision is
services/xreg_revoke_delivery.next_state: delivered closes the row (done_at); a refusal that cannot change (400, 422),
the attempt budget, or the delegation's expiry parks it (dead_at), logged [XREG-REVOKE-DEAD] with the credential, the
issuer and the delegate's registry; anything else waits longer each time (1, 5, 15 minutes, 1, 3, 6, 12 hours, then
24 hours). A row is never deleted.

Env: XREG_REVOKE_RETRY_ENABLED (default true), XREG_REVOKE_RETRY_INTERVAL_SEC (60), XREG_REVOKE_RETRY_BATCH (20),
XREG_REVOKE_RETRY_MAX_ATTEMPTS (40).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from agentvault_registry.database import get_db_context
from agentvault_registry.services import xreg_revoke_delivery as delivery

from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)


def retry_enabled() -> bool:
    return (os.getenv("XREG_REVOKE_RETRY_ENABLED") or "true").strip().lower() == "true"


try:
    from prometheus_client import Counter as _XC, Gauge as _XG

    REVOKES_TOTAL = _XC("registry_xreg_revokes_owed_total",
                        "Owed cross-registry delegation revokes sent again, by outcome (delivered, retried, dead)",
                        ["outcome"])
    REVOKES_OPEN = _XG("registry_xreg_revokes_owed_open",
                       "Cross-registry delegation revokes not yet delivered to the delegate's registry",
                       multiprocess_mode="max")
except Exception:  # pragma: no cover
    REVOKES_TOTAL = REVOKES_OPEN = None


class XRegRevokeRetry(BackgroundWorker):
    worker_id = "xreg_revoke_retry"
    leader_key = "xreg_revoke_retry"
    interval_sec = int(os.getenv("XREG_REVOKE_RETRY_INTERVAL_SEC", "60") or 60)
    cold_start_delay_sec = 30
    gate_label = "XREG_REVOKE_RETRY_ENABLED"

    def __init__(self) -> None:
        super().__init__()
        self.batch = int(os.getenv("XREG_REVOKE_RETRY_BATCH", "20") or 20)
        self._stats: Dict[str, Any] = {}

    def _should_run(self) -> bool:
        return retry_enabled()

    async def _cycle_once(self) -> None:
        delivered = retried = dead = 0
        budget = delivery.max_attempts()
        async with get_db_context() as db:
            rows = await delivery.due_rows(db, delivery.utcnow(), self.batch)
            await db.commit()   # the read ends here: nothing is held open while a peer is asked
            for row in rows:
                now = delivery.utcnow()
                if row.credential_expires_at is not None and row.credential_expires_at <= now:
                    outcome: Dict[str, Any] = {"delivered": False, "status": None, "error": delivery.EXPIRED_NOTE}
                else:
                    outcome = await delivery.send_revoke(db, row.credential_id, row.delegate_registry)
                    await db.commit()   # the peer lookup's read, ended before the row is written
                for k, v in delivery.next_state(row.attempts, outcome, delivery.utcnow(), budget=budget,
                                                credential_expires_at=row.credential_expires_at).items():
                    setattr(row, k, v)
                await db.commit()
                if row.done_at is not None:
                    delivered += 1
                    logger.info("[xreg-revoke-retry] delivered the revoke of %s (issuer %s) to %s after %d send(s)",
                                row.credential_id, row.issuer_did, row.delegate_registry, row.attempts)
                elif row.dead_at is not None:
                    dead += 1
                    logger.error("[XREG-REVOKE-DEAD] the revoke of %s (issuer %s) was not delivered to %s after %d "
                                 "send(s): %s (parked in xreg_revokes_owed; the revoke still stands at that "
                                 "registry's next check with this one)", row.credential_id, row.issuer_did,
                                 row.delegate_registry, row.attempts, row.last_error)
                else:
                    retried += 1
            open_now = await delivery.open_count(db)
            await db.commit()
        if REVOKES_TOTAL is not None:
            try:
                for name, n in (("delivered", delivered), ("retried", retried), ("dead", dead)):
                    if n:
                        REVOKES_TOTAL.labels(outcome=name).inc(n)
                REVOKES_OPEN.set(open_now)
            except Exception:  # noqa: BLE001
                pass
        if delivered or dead or retried:
            logger.info("[xreg-revoke-retry] delivered=%d retried=%d dead=%d open=%d", delivered, retried, dead,
                        open_now)
        self._stats = {"delivered_this_cycle": delivered, "retried_this_cycle": retried, "dead_this_cycle": dead,
                       "open_now": open_now}

    def _last_stats(self) -> Dict[str, Any]:
        return dict(self._stats or {})


_worker: "XRegRevokeRetry | None" = None


def get_xreg_revoke_retry() -> XRegRevokeRetry:
    global _worker
    if _worker is None:
        _worker = XRegRevokeRetry()
    return _worker
