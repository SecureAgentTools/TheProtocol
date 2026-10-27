"""background_tasks/forensic_scanner.py — Ledger Forensics scanner (2026-06-19).

Default-OFF (`FORENSIC_SCANNER_ENABLED=false`). Leader-elected periodic worker:
each cycle it runs the registry-DB stuck-rail inventory + the EventStore detector
scan and upserts an "Open Findings" inbox (`forensic_findings`, created on first
run) with first_seen / last_seen / ack. Pure read-of-source + write-to-own-table
— it NEVER moves money. Mirrors the keeper/worker lifecycle (BackgroundWorker).

Ships inert: with the flag off, start() is a no-op, the table is never created,
and the registry boots unchanged. Enable per-frame after review.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import text

from ..es_ssl_helper import get_httpx_verify

from ..database import get_db_context
from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)


def _truthy(v: Optional[str]) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


_DDL = """
CREATE TABLE IF NOT EXISTS forensic_findings (
  finding_key  text PRIMARY KEY,
  source       text NOT NULL,
  severity     text NOT NULL,
  title        text NOT NULL,
  detail       text,
  count        bigint,
  amount       numeric(36,18),
  currency     text,
  frame        text,
  status       text NOT NULL DEFAULT 'open',
  first_seen   timestamptz NOT NULL DEFAULT now(),
  last_seen    timestamptz NOT NULL DEFAULT now(),
  acked_at     timestamptz,
  acked_by     text
)
"""

# Registry-DB rails (mirror admin_health.forensics_inventory). (key, sql, severity, title, detail)
_RAILS: List[Tuple[str, str, str, str, str]] = [
    ("cross_frame_orphan",
     "SELECT count(*), coalesce(sum(amount),0) FROM cross_frame_transfers WHERE status='locked' AND timeout_at < now()",
     "high", "Cross-frame transfers locked past timeout",
     "saga_timeout_checker should auto-refund; persistence = wedged loop / unreachable counterparty TEG."),
    ("a2a_settling_stale",
     "SELECT count(*), coalesce(sum(amount),0) FROM a2a_payment_authorizations WHERE status='settling' AND coalesce(consumed_at, created_at) < now() - interval '90 seconds'",
     "warn", "A2A payments stuck in SETTLING",
     "a2a_payment_expiry asks each one's settlement record: a kept success settles it, a failure or nothing fails it, "
     "and a claim still held (a transfer whose answer was lost: up to 24 h) leaves it SETTLING. A row that persists "
     "is a settlement whose outcome is not known: check the payer's transactions before anyone pays again."),
    ("a2a_consumed_unsettled",
     "SELECT count(*), coalesce(sum(amount),0) FROM a2a_payment_authorizations WHERE status='consumed' AND expires_at < now()",
     "warn", "A2A CONSUMED but never settled",
     "service did paid work, payer never settled; expiry worker does not sweep CONSUMED."),
    ("bridge_locked",
     "SELECT count(*), coalesce(sum(amount),0) FROM bridge_transactions WHERE status='LOCKED' AND expires_at < now()",
     "high", "Bridge transfers locked past expiry",
     "bridge_expiry unlocks outbound LOCKED; inbound + FAILED-with-stuck-lock are blind spots."),
    ("fiat_paid_no_refund",
     "SELECT count(*), coalesce(sum(amount_eur),0) FROM fiat_purchases WHERE status='failed' AND (coalesce(failure_reason,'') IN ('reward_fund_failed','anonymous_resolve_failed','no_target_agent_resolved') OR failure_reason LIKE 'reward_fund_partial:%')",
     "high", "Fiat purchases: paid EUR, credit failed or partial, no refund",
     "direct-flow buyer paid EUR, the credit (in this registry's unit) failed (past fiat_credit_retry's budget) or landed only in part, no Stripe refund issued."),
    # §#85 P4.1 AGORA market surveillance — read-only detectors over exchange_trades/orders.
    # Δ-IRRELEVANT (pure reads). Thresholds are tuned ABOVE the legitimate sim/MM footprint
    # (sim is zero-cancel since V0112 → spoof clean; sim's max reciprocal DID-pair ≈ 9 → wash
    # threshold 30 won't false-positive). A finding is a FLAG for admin review, never an
    # auto-enforcement — the admin acts via coordinated_suspension / listing halt.
    ("agora_wash_reciprocal",
     "SELECT count(*), 0 FROM (SELECT listing_id, least(buyer_did,seller_did) a, greatest(buyer_did,seller_did) b "
     "FROM exchange_trades WHERE created_at > now() - interval '2 hours' AND buyer_did <> seller_did "
     "GROUP BY 1,2,3 HAVING count(*) >= 30 AND count(*) FILTER (WHERE buyer_did < seller_did) > 0 "
     "AND count(*) FILTER (WHERE buyer_did > seller_did) > 0) x",
     "high", "AGORA: suspected wash-trading (reciprocal DID pairs)",
     "Two DIDs traded back-and-forth >=30x on one listing in 2h (BOTH directions) — inflates volume with no real position transfer. Review the pair; consider coordinated_suspension."),
    ("agora_spoof_cancels",
     "SELECT count(*), 0 FROM (SELECT agent_did FROM exchange_orders WHERE status='cancelled' "
     "AND created_at > now() - interval '1 hour' AND remaining = qty "
     "AND (updated_at - created_at) < interval '20 seconds' GROUP BY agent_did HAVING count(*) >= 15) x",
     "high", "AGORA: suspected spoofing (rapid unfilled cancels)",
     "A DID placed + cancelled >=15 orders UNFILLED within 20s each in 1h — order-book manipulation (fake depth / paint the tape). Review; consider halting the listing or suspending the agent."),
    # §C MM SLA monitor (P2.2-B, 2026-06-24) — observability for the live treasury market-maker (#82).
    # Read-only, Δ-IRRELEVANT; severity 'warn' (an SLA signal, not a security threat). Findings
    # self-clear when the MM recovers. mm_down = an MM-enabled listing isn't quoting; mm_spread_wide
    # = it IS quoting two-sided but far wider than configured.
    ("agora_mm_down",
     "SELECT count(*), 0 FROM (SELECT l.id FROM exchange_listings l "
     "JOIN treasury_mm_config c ON c.listing_id=l.id AND c.enabled WHERE l.status='trading' "
     "AND NOT EXISTS (SELECT 1 FROM exchange_orders o WHERE o.listing_id=l.id AND o.agent_did=l.treasury_agent_did AND o.status IN ('open','partial')) "
     "AND NOT EXISTS (SELECT 1 FROM exchange_orders o WHERE o.listing_id=l.id AND o.agent_did=l.treasury_agent_did AND o.created_at > now()-interval '5 minutes')) x",
     "warn", "AGORA: treasury market-maker DOWN (SLA)",
     "An MM-enabled, trading listing has NO resting treasury quotes and no MM order in 5 min: the designated market-maker stopped quoting (liquidity gap). Check TREASURY_MM_ENABLED + the treasury balance/points + the treasury_market_maker worker logs."),
    ("agora_mm_spread_wide",
     "SELECT count(*), 0 FROM (SELECT "
     "(SELECT min(price) FROM exchange_orders WHERE listing_id=l.id AND agent_did=l.treasury_agent_did AND side='sell' AND status IN ('open','partial')) ask, "
     "(SELECT max(price) FROM exchange_orders WHERE listing_id=l.id AND agent_did=l.treasury_agent_did AND side='buy' AND status IN ('open','partial')) bid, c.spread_bps sb "
     "FROM exchange_listings l JOIN treasury_mm_config c ON c.listing_id=l.id AND c.enabled WHERE l.status='trading') x "
     "WHERE bid IS NOT NULL AND ask IS NOT NULL AND ask>bid AND (ask-bid)/((ask+bid)/2.0)*10000 > GREATEST(sb*3,600)",
     "warn", "AGORA: MM spread too wide (SLA)",
     "An MM-enabled listing's two-sided treasury quotes span > 3x the configured spread (or >600bps) — the market-maker is not maintaining a tight market. Usually self-heals on the next drift re-quote; if persistent, investigate the MM ref price / band."),
]


class ForensicScanner(BackgroundWorker):
    worker_id = "forensic_scanner"
    leader_key = "forensic_scanner:leader"
    interval_sec = int(os.getenv("FORENSIC_SCANNER_INTERVAL_SEC", "600"))
    cold_start_delay_sec = 45

    def _should_run(self) -> bool:
        return _truthy(os.getenv("FORENSIC_SCANNER_ENABLED", "false"))

    async def _cycle_once(self) -> None:
        frame = self._registry_id
        found: List[Dict[str, Any]] = []

        async with get_db_context() as db:
            # Ensure the inbox table exists (idempotent; only when the worker is enabled).
            await db.execute(text(_DDL))
            await db.commit()

            # 1) Registry-DB rails — each isolated (timeout seatbelt + rollback on error).
            for key, sql, sev, title, detail in _RAILS:
                try:
                    await db.execute(text("SET LOCAL statement_timeout = 4000"))
                    row = (await db.execute(text(sql))).first()
                    n = int(row[0]) if (row and row[0]) else 0
                    amt = float(row[1]) if (row and row[1] is not None) else None
                    await db.commit()
                    if n > 0:
                        found.append({"finding_key": f"reg:{key}", "source": "registry", "severity": sev,
                                      "title": title, "detail": detail, "count": n, "amount": amt,
                                      "currency": None, "frame": frame})
                except Exception as e:  # noqa: BLE001
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                    logger.debug(f"[forensic_scanner] rail {key} skipped: {e}")

            # 2) EventStore detector scan (actionable findings only — skip 'info').
            try:
                es_url = os.getenv("EVENT_STORE_URL", "http://event-store:8200")
                es_key = os.getenv("EVENT_STORE_API_KEY", "")
                # §SOVKIT T5 (2026-09-14): the store's TLS context (SPIRE bundle + system roots + the SVID); a default
                # client presented no certificate, so behind the frame's mTLS sidecar the scan read nothing.
                async with httpx.AsyncClient(timeout=30.0, verify=get_httpx_verify()) as client:
                    r = await client.get(f"{es_url}/api/v1/forensics/scan",
                                         headers={"X-Internal-Key": es_key})
                if r.status_code == 200:
                    for f in (r.json().get("findings") or []):
                        if f.get("severity") == "info":
                            continue
                        found.append({"finding_key": f"es:{f.get('key')}", "source": "eventstore",
                                      "severity": f.get("severity", "warn"), "title": f.get("title", ""),
                                      "detail": f.get("detail"), "count": f.get("count"),
                                      "amount": None, "currency": None, "frame": frame})
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[forensic_scanner] ES scan skipped: {e}")

            # 3) Upsert — keep an acked finding acked unless its count grows.
            for f in found:
                await db.execute(text(
                    "INSERT INTO forensic_findings "
                    "(finding_key, source, severity, title, detail, count, amount, currency, frame, last_seen) "
                    "VALUES (:k,:src,:sev,:t,:d,:n,:amt,:cur,:fr, now()) "
                    "ON CONFLICT (finding_key) DO UPDATE SET "
                    "last_seen=now(), count=excluded.count, severity=excluded.severity, detail=excluded.detail, "
                    "status=CASE WHEN forensic_findings.status='acked' AND excluded.count <= forensic_findings.count "
                    "THEN 'acked' ELSE 'open' END"
                ), {"k": f["finding_key"], "src": f["source"], "sev": f["severity"], "t": f["title"],
                    "d": f.get("detail"), "n": f.get("count"), "amt": f.get("amount"),
                    "cur": f.get("currency"), "fr": f.get("frame")})
            await db.commit()

        self._stats = {"open_findings": len(found)}
        logger.info(f"[forensic_scanner] cycle: {len(found)} active finding(s) upserted")


_singleton: Optional[ForensicScanner] = None


async def start_forensic_scanner() -> None:
    global _singleton
    if _singleton is not None:
        return
    _singleton = ForensicScanner()
    if not _singleton._should_run():
        logger.info("[forensic_scanner] disabled via env gate (FORENSIC_SCANNER_ENABLED=false)")
        return
    await _singleton.start()
    logger.info("[forensic_scanner] STARTED (read-only inventory + ES scan → Open Findings inbox)")


async def stop_forensic_scanner() -> None:
    global _singleton
    if _singleton is None:
        return
    await _singleton.stop()
    _singleton = None


def get_forensic_scanner() -> Optional[ForensicScanner]:
    return _singleton
