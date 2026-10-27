"""
Countersign-break watcher — §VCSIGN-2 (2026-08-15).

A regulatory authorization's tier-3 evidence is a countersigned contract. When
that contract leaves the `agreed` state (dispute, cancel, milestone submission,
even direct surgery), the card silently drops its `contract_digest` and the
public proof endpoint answers 409 — correct, but *nobody is told*: the operator
finds out only by looking at the panel.

This watcher observes the DERIVED state (the same classifier the card, the
admin list and the public endpoint use) instead of hooking the eight-plus
status-transition sites across two routers — one implementation point that is
structurally immune to the missed-call-site class, and it catches non-API
transitions too.

Per cycle: LIVE authorizations carrying a contract_ref -> batch contract load
-> classify. Newly broken (no Redis marker) -> notify the recording developer
through the catalog (`jurisdiction.countersign_broken`: push + in-app feed +
email per their own prefs) + emit `RegulatoryCountersignBroken` to the ledger,
then set the marker (45d TTL). Healed -> clear the marker so a re-break
re-alerts. Redis is also the dedupe store: the registry leader gate fails
CLOSED without Redis, so a cycle can never alert un-deduped.

Read-only + best-effort side channels. No balances, no authority, Δ-irrelevant.
Leader-elected; READONLY_MODE freezes it via the leader gate like every worker.
"""
import asyncio
import logging
import os

from ..database import AsyncSessionLocal as async_session_factory

logger = logging.getLogger(__name__)

_running = False

CYCLE_SECONDS = int(os.getenv("REGAUTH_COUNTERSIGN_WATCH_INTERVAL", "120"))
_MARKER_TTL = 45 * 86400  # re-alert a still-broken countersign after 45 days
_MARKER_PREFIX = "regauth:countersign_alert:"

_PROBLEM_TEXT = {
    "missing": "the referenced contract no longer exists on this registry",
    "nonzero_value": "the referenced contract is not zero-value",
    "not_agreed": "the referenced contract is no longer in the agreed state",
}


def _click_url() -> "str | None":
    try:
        from ..core.public_url import public_base_url_static
        base = public_base_url_static()
        return f"{base.rstrip('/')}/ui#/admin/jurisdiction" if base else None
    except Exception:  # noqa: BLE001
        return None


async def _watch_once() -> None:
    from .leader import get_redis
    from ..services import regulatory_auth as ra

    r = await get_redis()
    if r is None:  # no dedupe store -> no alerting this cycle (leader gate normally prevents this)
        logger.debug("[REGAUTH-WATCH] redis unavailable, skipping cycle")
        return

    async with async_session_factory() as db:
        rows = await ra.list_authorizations(db, include_revoked=False)
        live_refd = [a for a in rows if a.contract_ref and ra.is_live(a)]
        if not live_refd:
            return
        contracts = await ra.load_attestation_contracts(db, [a.contract_ref for a in live_refd])

    for a in live_refd:
        contract = contracts.get(a.contract_ref)
        problem = ra.classify_loaded_attestation_contract(contract)
        marker = f"{_MARKER_PREFIX}{a.id}"
        try:
            if problem is None:
                await r.delete(marker)  # healed (or never broken): a future break re-alerts
                continue
            if await r.get(marker):
                continue  # already alerted for this break
        except Exception as e:  # noqa: BLE001
            logger.warning("[REGAUTH-WATCH] redis dedupe failed for %s: %s", a.id, e)
            continue

        status = (contract or {}).get("status")
        detail = _PROBLEM_TEXT.get(problem, problem)
        logger.warning(
            "[REGAUTH-WATCH] countersign BROKEN auth=%s ref=%s action=%s contract=%s problem=%s status=%s",
            a.id, a.reference_id, a.action, a.contract_ref, problem, status or "-",
        )
        try:
            # notify() is THE typed entry point (§NOTIFV2): catalog-validated,
            # fans out push + in-app feed + email per the developer's own prefs.
            # A 0 return = every channel suppressed by prefs, which is still a
            # delivered verdict — the ledger event below stays the durable record.
            from .push_notify import notify
            await notify(
                "jurisdiction.countersign_broken",
                [a.recorded_by_dev_id],
                title=f"Countersign broken: {a.reference_id}",
                message=(
                    f"Authorization {a.reference_id} ({a.action}) relies on countersigned "
                    f"contract {a.contract_ref}, and {detail}"
                    + (f" (status={status})" if problem == "not_agreed" and status else "")
                    + ". The signed card no longer publishes its digest and the public proof "
                    "endpoint answers 409. Review it under Settings, Jurisdiction."
                ),
                tags="warning",
                priority="high",
                click=_click_url(),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[REGAUTH-WATCH] notify failed for %s: %s (will retry next cycle)", a.id, e)
            continue  # marker NOT set -> retried next cycle
        await ra.emit_regauth_event("RegulatoryCountersignBroken", a.subject_ref or "registry", {
            "authorization_id": a.id,
            "reference_id": a.reference_id,
            "action": a.action,
            "subject_ref": a.subject_ref,
            "contract_ref": a.contract_ref,
            "problem": problem,
            "contract_status": status,
        })
        try:
            await r.set(marker, problem, ex=_MARKER_TTL)
        except Exception as e:  # noqa: BLE001
            logger.warning("[REGAUTH-WATCH] marker set failed for %s: %s", a.id, e)


async def regauth_countersign_watch_loop():
    """Background loop — leader-elected, default 120s cycle."""
    from .leader import try_acquire_leadership
    global _running
    _running = True
    logger.info("[REGAUTH-WATCH] countersign-break watcher started (%ds cycle)", CYCLE_SECONDS)
    from . import vitals as _vitals
    await _vitals.register("regauth_countersign_watch", module=__name__, pattern="hand-rolled",
                           interval_sec=CYCLE_SECONDS, enabled=True)
    while _running:
        try:
            if await try_acquire_leadership("regauth_countersign_watch"):
                async with _vitals.cycle("regauth_countersign_watch"):
                    await _watch_once()
        except Exception:
            logger.error("[REGAUTH-WATCH] cycle error", exc_info=True)
        await asyncio.sleep(CYCLE_SECONDS)


def stop_regauth_countersign_watch():
    global _running
    _running = False
