"""AGORA gateway-float keeper (solvency, move-only) — migration 0096, 2026-06-19.

Keeps THIS frame's passport gateway (`did:theprotocol:agora-gateway-<ccy>`) SOLVENT so
refund/dividend repatriations never strand. The gateway is a shared cross-frame FLOAT:
deposits come IN (foreign-buyer passport funding) and money goes OUT two ways from the same
balance — funding new passport orders (`sweep_foreign_funding`) AND repatriating refunds/
dividends home (`repatriate_gateway_credits`). It bleeds the ~0.5% FX spread on every
cross-frame hop, the funding sweeper can spend money owed to pending repats, and NOTHING
refills it — so it drifts to ~0 and large repats fail forever (the stranded-refund class).

This keeper holds `gateway_liquid >= outstanding_repat_obligations + buffer`:
  target = Σ(exchange_gateway_credits.amount WHERE status IN ('pending', 'sending', 'batched')) + buffer
  (every size since §REPATLANE V0603: the aggregated pass sends the fragments; 'unresolved' is left out)
TOP-UP ONLY (the gateway is a float, not a rate-defining reserve — no upper sweep band). The
companion sweeper-reservation (EXCHANGE_PASSPORT_RESERVE_REPAT) stops order-funding from
spending below the obligations, so the two together make the gateway solvent BY CONSTRUCTION.

MOVE-ONLY: treasury → gateway via `_fund_agent_from_treasury_internal` (the reward-funding
waterfall: fee_collector first, then treasury — Δ-neutral, kind=transfer). It NEVER mints; a
treasury/fee_collector shortfall raises a 'treasury dry' alert (manual op-gated mint stays the
Commander's lever). Δ=0/0/0 preserved by construction.

Gating: env `GATEWAY_KEEPER_ENABLED` (per frame, default false) AND `EXCHANGE_PASSPORT_ENABLED`
(the gateway only exists where the passport is live) AND the DB `gateway_float_keeper_config.enabled`
toggle. All must be on. Leader-elected; runs on venue frames (registry-a / frame-b / frame-c).
Config re-read every cycle so it can be enabled/retuned live without a redeploy. Clone of
`fx_reserve_keeper`, simplified to a one-sided (top-up) float guard.
"""
from __future__ import annotations

import logging
import os
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from sqlalchemy import func, select, text, update

from ..database import get_db_context
from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter as _Counter, Gauge as _Gauge
    GWK_TOPUPS = _Counter("gateway_float_keeper_topups_total",
                          "Gateway float keeper treasury→gateway top-ups", labelnames=["frame"])
    GWK_BALANCE = _Gauge("gateway_float_keeper_balance", "gateway liquid balance", labelnames=["frame"])
    GWK_OBLIG = _Gauge("gateway_float_keeper_obligations", "outstanding sendable repat obligations", labelnames=["frame"])
    GWK_DRY = _Counter("gateway_float_keeper_treasury_dry_total",
                       "top-up shortfalls (treasury/fee_collector dry — manual mint needed)", labelnames=["frame"])
    GWK_RECON = _Counter("gateway_float_keeper_recon_total",
                         "autonomous recon actions on stranded credits", labelnames=["frame", "kind"])
except Exception:
    GWK_TOPUPS = GWK_BALANCE = GWK_OBLIG = GWK_DRY = GWK_RECON = None


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def _D(v, default="0") -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


class GatewayFloatKeeper(BackgroundWorker):
    worker_id = "gateway_float_keeper"
    leader_key = "gateway_float_keeper:leader"
    interval_sec = 60
    cold_start_delay_sec = 30

    def __init__(self) -> None:
        super().__init__()
        self._frame = self._registry_id
        self._last_action: Dict[str, Any] = {}

    # ── gating ───────────────────────────────────────────────────────────────
    def _should_run(self) -> bool:
        if not _truthy(os.getenv("GATEWAY_KEEPER_ENABLED", "false")):
            return False
        if not _truthy(os.getenv("EXCHANGE_PASSPORT_ENABLED", "false")):
            return False  # no passport venue → no gateway to keep solvent
        if not (os.getenv("TEG_API_BASE_URL", "") or "").strip():
            return False
        return True

    async def _load_config(self, db):
        from .. import models
        return (await db.execute(
            select(models.GatewayFloatKeeperConfig).where(models.GatewayFloatKeeperConfig.id == "singleton")
        )).scalar_one_or_none()

    async def _obligations(self, db) -> Decimal:
        """Repat obligations owed by this venue's gateway: every credit still owed, of every size.
        (failed credits are re-armed to 'pending' by the recovery step.) §REPATLANE (V0603): the fragments count too
        (the aggregated pass sends them once a holder's total clears the dust floor), and so does a credit claimed for
        a send ('sending', 'batched'): it is owed until its answer is applied. 'unresolved' is left out: it may already
        have reached its trader, and it is funded here once it is released to 'pending'."""
        from .. import models
        from ..services.exchange_service import REPAT_OWED_STATUSES
        v = (await db.execute(
            select(func.coalesce(func.sum(models.ExchangeGatewayCredit.amount), 0)).where(
                models.ExchangeGatewayCredit.status.in_(REPAT_OWED_STATUSES),
            )
        )).scalar_one()
        return _D(v)

    async def _reconcile(self, db) -> Dict[str, Any]:
        """Autonomous gateway sub-ledger recon (gated GATEWAY_RECON_ENABLED). Re-arm
        attempts-exhausted 'failed' repat credits → 'pending' so the worker retries them
        (the keeper funds the gateway to cover them THIS cycle, since recon runs before the
        top-up); ABANDON credits that exhaust GATEWAY_RECON_MAX_REARM re-arm generations —
        genuinely undeliverable (a receiver problem the keeper can't fix), surfaced for ops
        instead of hot-looping. Bounded per cycle; Δ-neutral (status/counter only — the money
        stays on the gateway as float the keeper maintains)."""
        if not _truthy(os.getenv("GATEWAY_RECON_ENABLED", "false")):
            return {"recon": "disabled"}
        from .. import models
        from ..services.exchange_service import REPAT_DUST
        from ..services.payout_outcome import RETRY_PREFIX
        # §REPATLANE (V0603): the recon touches only credits whose every attempt V0603 made (tx_ref RETRY_PREFIX: each
        # proved that nothing reached the trader) or that were never attempted. A 'failed' credit from the lane before
        # V0603 counted any non-200 answer as an attempt, stranded FX routes among them: the lane holds it for a ledger
        # read ('unresolved'), and the recon must not re-arm it first.
        _marked = models.ExchangeGatewayCredit.tx_ref.like(RETRY_PREFIX + "%")
        max_rearm = int(os.getenv("GATEWAY_RECON_MAX_REARM", "5"))
        batch = int(os.getenv("GATEWAY_RECON_BATCH", "200"))
        ab = await db.execute(
            update(models.ExchangeGatewayCredit)
            .where(models.ExchangeGatewayCredit.status == "failed",
                   models.ExchangeGatewayCredit.rearm_count >= max_rearm, _marked)
            .values(status="abandoned")
        )
        abandoned = int(ab.rowcount or 0)
        # §REPATLANE (V0603): every size. A marked 'failed' credit is one whose every send proved nothing reached the
        # trader (the lane marks 'failed' only at the attempt limit of such sends), and the aggregated pass now marks its
        # fragments 'failed' too; before, a sub-dust credit at the limit stayed 'pending' where nothing looked at it again.
        # The re-arm keeps the mark (tx_ref is left as it is), so the credit stays sendable.
        ids = (await db.execute(
            select(models.ExchangeGatewayCredit.id)
            .where(models.ExchangeGatewayCredit.status == "failed",
                   models.ExchangeGatewayCredit.rearm_count < max_rearm, _marked)
            .order_by(models.ExchangeGatewayCredit.id).limit(batch)
        )).scalars().all()
        rearmed = 0
        if ids:
            r = await db.execute(
                update(models.ExchangeGatewayCredit)
                .where(models.ExchangeGatewayCredit.id.in_(ids))
                .values(status="pending", attempts=0,
                        rearm_count=models.ExchangeGatewayCredit.rearm_count + 1)
            )
            rearmed = int(r.rowcount or 0)
        # §a sub-dust terminal sweep (2026-06-24, gated GATEWAY_SUBDUST_SWEEP_ENABLED, default off): mark sub-dust
        # credits terminal 'abandoned' — status-only, Δ-neutral (money stays on the gateway float, identical to a
        # rearm-max abandon). Its premise then ("credits below REPAT_DUST are never delivered") stopped being true
        # with the aggregated pass (2026-08-28).
        # §REPATLANE (V0603): only fragments the aggregated pass (§REPATAGG) cannot carry: the holder's whole pending
        # sub-dust stays under the floor and the credit is older than GATEWAY_SUBDUST_SWEEP_MIN_AGE_DAYS (default 7).
        # The sweep predates that pass: it abandoned EVERY sub-dust credit, deliverable ones included, and in the same
        # recon pass it abandoned the fragments the re-arm above had just returned to 'pending'.
        if _truthy(os.getenv("GATEWAY_SUBDUST_SWEEP_ENABLED", "false")):
            min_age_s = float(os.getenv("GATEWAY_SUBDUST_SWEEP_MIN_AGE_DAYS", "7")) * 86400.0
            sd = await db.execute(text(
                "UPDATE exchange_gateway_credits c SET status='abandoned'"
                " WHERE c.status='pending' AND c.amount < :dust"
                " AND ((c.attempts = 0 AND c.rearm_count = 0) OR c.tx_ref LIKE :retry_mark)"
                " AND c.created_at < now() - make_interval(secs => :age)"
                " AND (SELECT coalesce(sum(o.amount), 0) FROM exchange_gateway_credits o"
                "      WHERE o.did = c.did AND o.home_registry IS NOT DISTINCT FROM c.home_registry"
                "        AND o.status='pending' AND o.amount < :dust) < :dust"),
                {"dust": str(REPAT_DUST), "age": min_age_s, "retry_mark": RETRY_PREFIX + "%"})
            abandoned += int(sd.rowcount or 0)
        # §CHATDESK C5b (§REPATAGG) — bounded re-arm of terminally 'abandoned'
        # credits, DEFAULT OFF. Two classes earned it (measured 2026-08-28,
        # frame-c): ~323.7K BVT of >=dust credits abandoned by real send
        # failures in the pre-§V0206 broken-fabric era (the fabric is fixed —
        # they deliver now), and sub-dust fragments the new aggregated batch
        # can finally carry. Biggest first, N per cycle, so the drain is a
        # trickle on the FX rail and never a sync storm. Δ-neutral by
        # construction: status-only here; the money moves on the same
        # idempotent repat rail as everything else.
        rearm_ab = int(os.getenv("GATEWAY_REARM_ABANDONED_BATCH", "0"))
        if rearm_ab > 0:
            # §REPATLANE (V0603): an abandoned credit the lane before V0603 attempted (attempts or re-arms, no mark) may
            # already have reached its trader: it stays abandoned, for a ledger read, and is never re-armed from here.
            from sqlalchemy import and_ as _and, or_ as _or
            ab_ids = (await db.execute(
                select(models.ExchangeGatewayCredit.id)
                .where(models.ExchangeGatewayCredit.status == "abandoned",
                       _or(_and(models.ExchangeGatewayCredit.attempts == 0,
                                models.ExchangeGatewayCredit.rearm_count == 0), _marked))
                .order_by(models.ExchangeGatewayCredit.amount.desc())
                .limit(rearm_ab)
            )).scalars().all()
            if ab_ids:
                rr = await db.execute(
                    update(models.ExchangeGatewayCredit)
                    .where(models.ExchangeGatewayCredit.id.in_(ab_ids))
                    .values(status="pending", attempts=0, rearm_count=0)
                )
                rearmed += int(rr.rowcount or 0)
        if rearmed or abandoned:
            await db.commit()
            if GWK_RECON is not None:
                try:
                    if rearmed:
                        GWK_RECON.labels(frame=self._frame, kind="rearmed").inc(rearmed)
                    if abandoned:
                        GWK_RECON.labels(frame=self._frame, kind="abandoned").inc(abandoned)
                except Exception:
                    pass
            logger.info(f"[gateway_float_keeper] RECON re-armed={rearmed} abandoned={abandoned} "
                        f"(max_rearm={max_rearm}, batch={batch})")
        return {"rearmed": rearmed, "abandoned": abandoned}

    # ── cycle ────────────────────────────────────────────────────────────────
    async def _cycle_once(self) -> None:
        from ..services.exchange_passport import GATEWAY_DID, gateway_balance
        async with get_db_context() as db:
            cfg = await self._load_config(db)
            if cfg is None or not cfg.enabled:
                self._stats = {"enabled": False, "reason": "config disabled" if cfg else "no config row"}
                return
            try:
                iv = int(cfg.check_interval_sec or 60)
                if iv >= 10:
                    self.interval_sec = iv
            except Exception:
                pass

            mode = (cfg.operator_mode or "worker").strip().lower()
            ccy = (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper()

            try:
                liquid = await gateway_balance()
            except Exception as e:
                self._stats = {"enabled": True, "action": "skip", "reason": f"gateway balance read failed: {str(e)[:120]}"}
                return
            recon = await self._reconcile(db)  # autonomous re-arm/abandon BEFORE sizing the top-up (so re-armed credits are funded THIS cycle)
            obligations = await self._obligations(db)
            buffer = _D(cfg.buffer)
            target = obligations + buffer

            if GWK_BALANCE is not None:
                try:
                    GWK_BALANCE.labels(frame=self._frame).set(float(liquid))
                    GWK_OBLIG.labels(frame=self._frame).set(float(obligations))
                except Exception:
                    pass

            base_stats = {"enabled": True, "frame": self._frame, "currency": ccy, "mode": mode,
                          "gateway": GATEWAY_DID, "liquid": str(liquid), "obligations": str(obligations),
                          "buffer": str(buffer), "target": str(target), "recon": recon,
                          "last_action": self._last_action}

            if mode == "off":
                self._stats = {**base_stats, "action": "stand_down"}
                return
            if target <= 0:
                self._stats = {**base_stats, "action": "noop", "reason": "nothing owed + no buffer"}
                return

            dead = _D(cfg.deadband_pct, "0.05")
            if liquid >= target * (Decimal("1") - dead):
                self._stats = {**base_stats, "action": "in_band"}
                return

            need = target - liquid
            cap = _D(cfg.max_move_per_cycle)
            if cap > 0:
                need = min(need, cap)
            if need <= 0:
                self._stats = {**base_stats, "action": "noop"}
                return

            # ── TOP-UP: treasury → gateway via the reward-funding waterfall (Δ-neutral, never mints) ──
            try:
                from ..routers.teg_integration import _fund_agent_from_treasury_internal, TreasuryFundAgentRequest
                req = TreasuryFundAgentRequest(
                    target_agent_did=GATEWAY_DID,
                    amount=str(need),
                    reason="gateway_float_topup",
                    reference_id=f"gwk-{self._frame}-{uuid.uuid4().hex[:12]}",
                )
                res = await _fund_agent_from_treasury_internal(db, req, actor_label="gateway_float_keeper")
                self._last_action = {"action": "topup", "amount": str(need), "tx": (res or {}).get("transaction_id", "")}
                if GWK_TOPUPS is not None:
                    try: GWK_TOPUPS.labels(frame=self._frame).inc()
                    except Exception: pass
                logger.info(f"[gateway_float_keeper] TOPUP {need} {ccy} @treasury→{GATEWAY_DID} "
                            f"(liquid {liquid}→~{target}; obligations={obligations} buffer={buffer})")
                self._stats = {**base_stats, "action": "topup", "amount": str(need)}
            except Exception as e:
                if GWK_DRY is not None:
                    try: GWK_DRY.labels(frame=self._frame).inc()
                    except Exception: pass
                logger.error(f"[gateway_float_keeper] TOPUP FAILED {need} {ccy} (treasury/fee_collector dry? "
                             f"manual mint needed): {str(e)[:160]}")
                self._stats = {**base_stats, "action": "topup_failed", "need": str(need),
                               "error": str(e)[:160], "alert": "treasury_dry_manual_mint_needed"}


_singleton: Optional[GatewayFloatKeeper] = None


async def start_gateway_float_keeper() -> None:
    global _singleton
    if _singleton is not None:
        return
    _singleton = GatewayFloatKeeper()
    if not _singleton._should_run():
        logger.info("[gateway_float_keeper] disabled via env gate "
                    "(GATEWAY_KEEPER_ENABLED / EXCHANGE_PASSPORT_ENABLED / TEG_API_BASE_URL)")
        return
    await _singleton.start()
    logger.info("[gateway_float_keeper] STARTED (passport gateway solvency keeper, move-only top-up)")


async def stop_gateway_float_keeper() -> None:
    global _singleton
    if _singleton is None:
        return
    await _singleton.stop()
    _singleton = None


def get_gateway_float_keeper() -> Optional[GatewayFloatKeeper]:
    return _singleton
