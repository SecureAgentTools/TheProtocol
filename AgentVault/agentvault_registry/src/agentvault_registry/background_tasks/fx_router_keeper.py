"""FX-router liquidity keeper + dead-letter auto-refund (AAA+ op→op FX, migration 0085).

The op→op FX route's `@fx_router` is an FX-settlement **suspense (nostro)** account; the
`@fx_reserve` AMM is its **funding pool**. Per controlled traces the router nets EXACTLY 0
per successful route and fees are collected correctly — there is no leak. But it is ONE
shared suspense account, so under concurrency the booth source-lock (`@fx_router →
@fx_reserve`) can transiently outrun the ingress on the shared balance → `Insufficient
balance` → the route fails (the op→op sim's 77%). Real FX settlement runs *automated
liquidity management* on funded suspense accounts (they are deliberately NOT zero-balance).

This leader-elected worker, on each reserve frame (registry-a AVT / frame-c BVT):
  1. **Liquidity:** keeps `@fx_router` liquid within `[min, target, max]` watermarks against
     the `@fx_reserve` pool (Δ-neutral — never treasury, unless `source='treasury'`). Below
     `min` → draw to `target`; above `max` (>0) → sweep excess back to the reserve.
  2. **Dead-letter auto-refund:** processes `fx_route_dead_letters` rows (funds parked by a
     failed-compensation route) → refunds the ORIGINAL SENDER 1:1, retry-until-settled;
     last-resort sweep to the reserve after `dead_letter_max_retries`.

Gating: master env `FX_ROUTER_KEEPER_ENABLED` (default false / opt-in, set on reserve frames
only) AND the DB `fx_router_keeper_config.enabled` toggle (FX Desk-editable). Both must be on.
Config is read every cycle so the FX Desk can enable/retune live without a redeploy.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from sqlalchemy import select, text

from ..database import get_db_context
from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter as _Counter, Gauge as _Gauge
    FXK_MOVES = _Counter("fx_router_keeper_moves_total",
                         "FX router keeper liquidity moves", labelnames=["frame", "action"])
    FXK_REFUNDS = _Counter("fx_router_keeper_dead_letter_total",
                           "FX router keeper dead-letter resolutions", labelnames=["frame", "result"])
    FXK_LIQUID = _Gauge("fx_router_keeper_liquid", "FX router liquid balance", labelnames=["frame"])
except Exception:
    FXK_MOVES = FXK_REFUNDS = FXK_LIQUID = None


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


# ── §FXSELFHEAL (2026-08-10) — remote parked-route recovery, DESTINATION side ─────────
# The origin frame cannot refund a `post_conversion_remote` row: the converted funds are at
# THIS frame's @fx_router. Recovery is re-delivery here. Each cycle the keeper pulls its own
# workload from the origin peers' /federation/fx/parked-at, drives each row through the
# origin's claim→resolve CAS, and delivers with the stable `fxroute:{id}:recovery` memo.
#
# THREE guards, each earned on 2026-08-10:
#   1. claim CAS (origin side)  — the sweep rail has NO per-route idempotency; the row's
#      pending→sweeping transition is the mutual exclusion between the keeper, the manual
#      runbook, and any peer. A concurrent sweeper was observed live that day.
#   2. local delivery ledger    — `fx_route_deliveries`; two routes had ALREADY been paid
#      (egress COMPLETED 4-6 s after the origin's dead-letter write). An age gate cannot see
#      that class. Checked BEFORE claiming; a lookup failure FAILS CLOSED (skip, never sweep).
#   3. single-writer Redis lock — one keeper instance moves money at a time, fleet-wide.
# Mode gate: FX_REMOTE_RECOVERY_MODE ∈ off | endpoints | keeper | on   (default off = inert).
_RR_LOCK_KEY = "fx_remote_recovery:writer"


def _rr_mode() -> str:
    return (os.getenv("FX_REMOTE_RECOVERY_MODE", "off") or "off").strip().lower()


def _rr_keeper_enabled() -> bool:
    return _rr_mode() in ("keeper", "on")


def _rr_min_age_sec() -> int:
    try:
        return max(300, int(os.getenv("FX_REMOTE_RECOVERY_MIN_AGE_SEC", "900") or 900))
    except (TypeError, ValueError):
        return 900


def _rr_batch() -> int:
    try:
        return max(1, min(100, int(os.getenv("FX_REMOTE_RECOVERY_BATCH", "10") or 10)))
    except (TypeError, ValueError):
        return 10


def _D(v, default="0") -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


class FxRouterKeeper(BackgroundWorker):
    worker_id = "fx_router_keeper"
    leader_key = "fx_router_keeper:leader"
    interval_sec = 60
    cold_start_delay_sec = 20

    def __init__(self) -> None:
        super().__init__()
        self._frame = os.getenv("REGISTRY_NAME", "registry-a")
        self._last_action: Dict[str, Any] = {}

    # ── gating ────────────────────────────────────────────────────────────────
    def _should_run(self) -> bool:
        if not (os.getenv("FX_ROUTER_DID", "") or "").strip():
            return False  # only reserve frames hold an @fx_router
        if not _truthy(os.getenv("FX_ENABLED", "false")):
            return False  # FX booth must be live (excludes Frame B)
        # §FXSELFHEAL: remote recovery is its OWN reason to run. A frame can hold parked
        # funds for remote origins without running the liquidity manager, so the worker
        # starts when EITHER half is enabled and each half re-checks its own gate.
        if _truthy(os.getenv("FX_ROUTER_KEEPER_ENABLED", "false")):
            return True
        if _rr_keeper_enabled():
            return True
        # §FXSTRAND-2 (2026-09-07, agentvault2-eb's measurement): the SAME carve-out, third half.
        # A FRAME THAT CAN PARK MUST BE ABLE TO UNPARK, whatever its float manager is doing. Route 511e702c sat `pending / retries 0`
        # for nine minutes with 1.99 at the router and the sender 48 of 50, because this worker
        # returned here before registering: `/admin/workers/status` listed no fx_router_keeper at all,
        # and ABSENT reads exactly like NO SUCH WORKER. The refund half re-checks its own switch
        # below; the drain is a no-op read (`{"pending": 0}`) on a frame with nothing parked.
        return _truthy(os.getenv("FX_ROUTE_ENABLED", "false"))

    async def _load_config(self, db):
        from .. import models
        return (await db.execute(
            select(models.FxRouterKeeperConfig).where(models.FxRouterKeeperConfig.id == "singleton")
        )).scalar_one_or_none()

    # ── cycle ─────────────────────────────────────────────────────────────────
    async def _cycle_once(self) -> None:
        async with get_db_context() as db:
            cfg = await self._load_config(db)
            if cfg is None or not cfg.enabled:
                # §FXSELFHEAL — remote recovery does NOT depend on the liquidity config row:
                # a frame can hold other frames' parked funds while its own float manager is
                # off (and frame-c's config row is exactly that case).
                rr_only = {}
                if _rr_keeper_enabled():
                    try:
                        rr_only = await self._process_remote_parked(db, cfg)
                    except Exception as e:  # noqa: BLE001
                        logger.error(f"[fxselfheal] cycle error: {e}")
                        rr_only = {"error": str(e)[:200]}
                # §FXSTRAND-2: the dead-letter drain does NOT depend on the liquidity config either.
                # `dead_letter_refund_enabled` is its OWN column and defaults TRUE, so a frame reads
                # as configured-for-refunds while `enabled=False` silenced it — which is how 1.99 sat
                # parked with `dead_letter_refund_enabled: true` beside it. The liquidity switch gates
                # MOVING TREASURY MONEY; returning someone's own parked funds is not that decision.
                dl_only = {}
                if cfg is None or cfg.dead_letter_refund_enabled:
                    try:
                        dl_only = await self._process_dead_letters(db, cfg)
                    except Exception as e:  # noqa: BLE001 — never let the drain break the cycle
                        logger.error(f"[fxdl] drain error (liquidity off): {e}")
                        dl_only = {"error": str(e)[:200]}
                self._stats = {"enabled": False,
                               "reason": "config disabled" if cfg else "no config row",
                               "dead_letters": dl_only, "remote_recovery": rr_only}
                return
            try:
                iv = int(cfg.check_interval_sec or 60)
                if iv >= 10:
                    self.interval_sec = iv
            except Exception:
                pass

            liq_stats = await self._manage_liquidity(db, cfg)
            dl_stats = {}
            if cfg.dead_letter_refund_enabled:
                dl_stats = await self._process_dead_letters(db, cfg)
            rr_stats = {}
            if _rr_keeper_enabled():
                try:
                    rr_stats = await self._process_remote_parked(db, cfg)
                except Exception as e:  # noqa: BLE001 — never let recovery break liquidity
                    logger.error(f"[fxselfheal] cycle error: {e}")
                    rr_stats = {"error": str(e)[:200]}

            self._stats = {
                "enabled": True, "frame": self._frame,
                "currency": self._currency(),
                "target_float": str(cfg.target_float), "min_float": str(cfg.min_float),
                "max_float": str(cfg.max_float), "source": cfg.source,
                "liquidity": liq_stats, "dead_letters": dl_stats,
                "remote_recovery": rr_stats,
                "last_action": self._last_action,
            }

    def _currency(self) -> str:
        try:
            from ..routers.teg_integration import _local_frame_currency
            return _local_frame_currency()
        except Exception:
            return "AVT"

    async def _router_liquid(self, db) -> tuple:
        from ..routers.teg_integration import _fx_router_liquid
        return await _fx_router_liquid(db)  # (router_did, Decimal|None, agent)

    # ── PART 1: liquidity management vs the @fx_reserve pool ─────────────────────
    async def _manage_liquidity(self, db, cfg) -> Dict[str, Any]:
        from ..routers.teg_integration import _fx_teg_move, _fund_agent_from_treasury_internal, TreasuryFundAgentRequest
        target = _D(cfg.target_float); lo = _D(cfg.min_float); hi = _D(cfg.max_float)
        cap = _D(cfg.max_move_per_cycle)
        router_did, liquid, _agent = await self._router_liquid(db)
        if liquid is None:
            return {"action": "skip", "reason": "router balance unavailable", "router_did": router_did}
        if FXK_LIQUID is not None:
            try: FXK_LIQUID.labels(frame=self._frame).set(float(liquid))
            except Exception: pass
        if target <= 0:
            return {"action": "skip", "reason": "target_float=0 (unconfigured)", "liquid": str(liquid)}

        teg_base = os.environ.get("TEG_API_BASE_URL", "http://teg-layer:8080")
        admin_key = os.environ.get("TEG_ADMIN_API_KEY", "")
        ccy = self._currency()

        # TOP-UP: liquid below the low watermark → draw to target
        if lo > 0 and liquid < lo:
            need = target - liquid
            if cap > 0:
                need = min(need, cap)
            if need <= 0:
                return {"action": "noop", "liquid": str(liquid)}
            try:
                if (cfg.source or "fx_reserve") == "treasury":
                    req = TreasuryFundAgentRequest(target_agent_did=router_did, amount=str(need),
                                                   reason="fx_router_keeper_topup")
                    await _fund_agent_from_treasury_internal(db, req, actor_label="fx_router_keeper")
                else:
                    r = await _fx_teg_move(teg_base, admin_key, from_did="@fx_reserve", to_did=router_did,
                                           amount=need, reason="fx_router_keeper_topup",
                                           idem_key=str(uuid.uuid4()))
                    if r.status_code != 200:
                        return {"action": "topup_failed", "need": str(need), "detail": r.text[:160]}
                self._last_action = {"action": "topup", "amount": str(need), "from": cfg.source, "to": router_did}
                if FXK_MOVES is not None:
                    try: FXK_MOVES.labels(frame=self._frame, action="topup").inc()
                    except Exception: pass
                logger.info(f"[fx_router_keeper] TOPUP {need} {ccy} {cfg.source}→@fx_router "
                            f"(liquid {liquid}→~{target})")
                return {"action": "topup", "amount": str(need), "from": cfg.source,
                        "liquid_before": str(liquid), "target": str(target)}
            except Exception as e:
                logger.error(f"[fx_router_keeper] topup error: {e}")
                return {"action": "topup_error", "error": str(e)[:160]}

        # SWEEP: liquid above the high watermark → return excess to the @fx_reserve pool.
        # ONLY in source='fx_reserve' mode: in 'treasury' mode the float is operational capital,
        # so pushing it into the AMM pool would inflate the pool / move the rate — never do that.
        # (treasury-mode excess is left as residue; the FX Desk manual sweep / dead-letter refund
        # reclaim it.)
        if hi > 0 and liquid > hi and (cfg.source or "treasury") == "fx_reserve":
            excess = liquid - target
            if cap > 0:
                excess = min(excess, cap)
            if excess <= 0:
                return {"action": "noop", "liquid": str(liquid)}
            try:
                r = await _fx_teg_move(teg_base, admin_key, from_did=router_did, to_did="@fx_reserve",
                                       amount=excess, reason="fx_router_keeper_sweep",
                                       idem_key=str(uuid.uuid4()))
                if r.status_code != 200:
                    return {"action": "sweep_failed", "excess": str(excess), "detail": r.text[:160]}
                self._last_action = {"action": "sweep", "amount": str(excess), "to": "@fx_reserve"}
                if FXK_MOVES is not None:
                    try: FXK_MOVES.labels(frame=self._frame, action="sweep").inc()
                    except Exception: pass
                logger.info(f"[fx_router_keeper] SWEEP {excess} {ccy} @fx_router→@fx_reserve "
                            f"(liquid {liquid}→~{target})")
                return {"action": "sweep", "amount": str(excess), "liquid_before": str(liquid),
                        "target": str(target)}
            except Exception as e:
                logger.error(f"[fx_router_keeper] sweep error: {e}")
                return {"action": "sweep_error", "error": str(e)[:160]}

        return {"action": "in_band", "liquid": str(liquid), "min": str(lo), "max": str(hi)}

    # ── PART 2: dead-letter auto-refund to the original sender ───────────────────
    async def _process_dead_letters(self, db, cfg) -> Dict[str, Any]:
        from .. import models
        from ..routers.teg_integration import (
            _fx_route_1to1_2pc, _fx_route_find_active_peer, _resolve_receiver_registry, _fx_teg_move,
            _resolve_peer_currency, _fx_dead_letter_refund_amounts, _fee_collector_distribute, _leg_moved_nothing,
            _LegError,
        )
        # cfg may be None (no config row) — the drain is reachable without one since §FXSTRAND-2,
        # and the model's own default for this column is 8.
        max_retries = int((getattr(cfg, "dead_letter_max_retries", None) if cfg else None) or 8)
        # §FXDL (2026-07-28) — PHASE GUARD. This loop refunds the origin sender FROM THE LOCAL
        # @fx_router. That is only correct when the parked funds are actually HERE, which is true
        # for `pre_conversion` (the route died before the currency boundary, money never left).
        #
        # A `post_conversion` dead-letter is the opposite case: the FX core swap SUCCEEDED and the
        # converted funds are parked at the DESTINATION frame's @fx_router. Refunding those from
        # this frame would pay the sender while the converted money still sits on the far side —
        # value created out of nothing, and the supply invariant would (correctly) scream.
        # The model has always allowed phase='post_conversion'; this loop never distinguished it,
        # so the guard is written explicitly rather than left to the fact that nobody writes those
        # rows yet. Recovery for that phase is RE-DELIVERY on the far frame, never a local refund.
        # §REPATLANE-2 (V0603): an ALLOWLIST. `pre_conversion` rows are refunded; `egress_unknown` rows (a local egress
        # whose outcome was not known) are finished forward under the egress's own idempotency key; every other phase
        # (post_conversion*, swap_unknown, egress_2pc_unknown, anything newer) is never refunded from here.
        rows = (await db.execute(
            select(models.FxRouteDeadLetter)
            .where(models.FxRouteDeadLetter.status == "pending")
            .where(models.FxRouteDeadLetter.phase.in_(("pre_conversion", "egress_unknown")))
            .order_by(models.FxRouteDeadLetter.created_at).limit(20)
        )).scalars().all()
        if not rows:
            return {"pending": 0}

        router_did = (os.getenv("FX_ROUTER_DID", "") or "").strip()
        router_agent = (await db.execute(
            select(models.Agent).where(models.Agent.did == router_did)
        )).scalar_one_or_none()
        if router_agent is None:
            return {"pending": len(rows), "reason": "router agent missing"}

        teg_base = os.environ.get("TEG_API_BASE_URL", "http://teg-layer:8080")
        admin_key = os.environ.get("TEG_ADMIN_API_KEY", "")
        refunded = swept = failed = delivered = held = 0
        for dl in rows:
            try:
                if dl.phase == "egress_unknown":
                    outcome = await self._finish_unknown_egress(db, dl, router_agent, router_did, max_retries)
                    delivered += outcome == "delivered"
                    failed += outcome == "failed"
                    await db.commit()
                    continue
                # resolve the original sender's home TEG (refund target)
                rtid = dl.origin_teg_id; rrid = dl.origin_registry_id
                if not rtid:
                    rtid, rrid = await _resolve_receiver_registry(db, dl.origin_did)
                recv_peer = await _fx_route_find_active_peer(db, rrid) if rrid else None
                ok = err = None
                # §FXPOSTCONV (2026-09-26): the refund is 1:1 in THIS row's currency. An origin whose home holds
                # another currency cannot take it (its TEG refuses: measured on the sandbox pair every night since
                # 09-23, one row a night, 8 retries refused, then 'failed'). Such a row is money an older far frame
                # parked AFTER a conversion; it needs re-delivery to its receiver, never this refund. So no leg is
                # attempted and the row says why, once.
                try:
                    o_ccy = await _resolve_peer_currency(db, target_peer=recv_peer) if recv_peer is not None else None
                except Exception:  # noqa: BLE001 — unknown currency: the refund decides as before
                    o_ccy = None
                if o_ccy and dl.currency and str(o_ccy).upper() != str(dl.currency).upper():
                    dl.status = "failed"
                    dl.last_error = (f"not refundable here: the origin's home holds {o_ccy} and this row {dl.currency} "
                                     f"(money parked after a conversion: re-deliver to the receiver)")[:480]
                    failed += 1
                    logger.error(f"[fx_router_keeper] dead-letter route={dl.route_id}: {dl.last_error}")
                    await db.commit()
                    if FXK_REFUNDS is not None:
                        try: FXK_REFUNDS.labels(frame=self._frame, result="cross_currency").inc()
                        except Exception: pass
                    continue
                # §REPATLANE-6 (V0606): the payer is made whole. What the router holds is what the ingress leg
                # credited of the payer's payment, and the refund leg costs a fee too: this frame's fee collector pays
                # the router the difference first (fee-free, under the route's own key, so a pass that sends again
                # never pays it twice), and the refund sends enough for the payer's TEG to credit the whole payment.
                # A top-up whose outcome is not known is asked again next pass before anything is sent; one the TEG
                # refused leaves the refund as it was (the money, without its fees).
                send_amount, top_up = _fx_dead_letter_refund_amounts(dl.amount)
                fees_note = ""
                if rtid and top_up > 0:
                    t_tx, t_refused, t_why = await _fee_collector_distribute(
                        f"fxroute:{dl.route_id}:dead-letter-fees", router_did, top_up,
                        f"dead-letter-fees:route-{dl.route_id}")
                    if not t_tx and not t_refused:
                        dl.last_error = (f"the fees' top-up ({top_up}) for this refund was not answered ({t_why}): "
                                         f"asked again next pass under fxroute:{dl.route_id}:dead-letter-fees")[:480]
                        logger.warning(f"[fx_router_keeper] dead-letter route={dl.route_id}: {dl.last_error}")
                        await db.commit()
                        continue
                    if not t_tx:
                        send_amount = Decimal(str(dl.amount))
                        fees_note = f" (its fees did not go back: {t_why})"
                if rtid:
                    ok, err, _credited, tx = await _fx_route_1to1_2pc(
                        db, sender_agent=router_agent, sender_did=router_did, receiver_did=dl.origin_did,
                        amount=str(send_amount), target_teg_id=rtid, target_registry_id=rrid,
                        target_peer=recv_peer, memo=f"fxroute:{dl.route_id}:dead-letter-refund")
                else:
                    ok, err = False, _LegError(f"cannot resolve origin {dl.origin_did}", nothing_moved=True)
                if ok:
                    dl.status = "refunded"; dl.resolution_tx = tx; dl.resolved_at = _now()
                    dl.last_error = fees_note.strip(" ()")[:480] or None
                    refunded += 1
                    logger.info(f"[fx_router_keeper] dead-letter REFUNDED route={dl.route_id} "
                                f"{send_amount} {dl.currency} → {dl.origin_did} (tx={tx}){fees_note}")
                elif not _leg_moved_nothing(err):
                    # §REPATLANE-6 (V0606): a refund leg whose outcome is not known may have refunded the origin;
                    # sending it again next pass could refund twice. It holds for a read of the leg.
                    dl.phase = "refund_unknown"
                    dl.last_error = (f"the refund leg fxroute:{dl.route_id}:dead-letter-refund ({send_amount}) ended "
                                     f"(outcome not known): {err}; read the origin's ledger before refunding again")[:480]
                    held += 1
                    logger.error(f"[fx_router_keeper] dead-letter route={dl.route_id}: {dl.last_error}")
                else:
                    dl.retries = (dl.retries or 0) + 1
                    dl.last_error = (err or "refund failed")[:480]
                    if dl.retries >= max_retries:
                        # Exhausted auto-refund retries → escalate for MANUAL review (FX Desk). Do NOT
                        # auto-move the funds: pre-conversion residue is the ORIGINAL SENDER's money, not
                        # pool capital — an admin decides (re-refund / pool-return / treasury). The funds
                        # remain safely parked at @fx_router; the residue-sweep button can place them.
                        dl.status = "failed"
                        failed += 1
                        logger.error(f"[fx_router_keeper] dead-letter FAILED after {dl.retries} retries "
                                     f"route={dl.route_id} {dl.amount} {dl.currency} — funds remain at "
                                     f"{router_did}; escalate to FX Desk manual sweep")
                await db.commit()
                if FXK_REFUNDS is not None:
                    try:
                        FXK_REFUNDS.labels(frame=self._frame,
                                           result=dl.status if dl.status in ("refunded", "swept", "failed") else "retry").inc()
                    except Exception: pass
            except Exception as e:
                await db.rollback()
                logger.error(f"[fx_router_keeper] dead-letter error route={getattr(dl,'route_id','?')}: {e}")
        return {"pending": len(rows), "refunded": refunded, "swept": swept, "failed": failed,
                "delivered": delivered, "held": held}

    async def _finish_unknown_egress(self, db, dl, router_agent, router_did: str, max_retries: int) -> str:
        """§REPATLANE-2 (V0603): a local egress whose outcome the hop could not learn (phase egress_unknown). It is asked
        again under its own Idempotency-Key (fxroute:<route>:egress-local), so it can never pay twice: a 200 is the
        delivery (made then or now); a refusal that proves the egress never ran returns the row to the refund path (the
        money is still at this @fx_router); anything else waits for the next pass. The TEG keeps the key for 24 h, so a
        row older than FX_EGRESS_UNKNOWN_MAX_AGE_HOURS (default 20) is no longer asked: it holds for a ledger read."""
        from ..routers.teg_integration import _fx_route_local_egress, _leg_moved_nothing, _record_fx_delivery
        max_age_h = float(os.getenv("FX_EGRESS_UNKNOWN_MAX_AGE_HOURS", "20"))
        created = dl.created_at
        if created is not None and created.tzinfo is None:
            import datetime as _dtz
            created = created.replace(tzinfo=_dtz.timezone.utc)
        age_h = ((_now() - created).total_seconds() / 3600.0) if created is not None else 0.0
        if age_h > max_age_h or not dl.receiver_did:
            dl.status = "failed"
            dl.last_error = (f"egress_unknown {'without a receiver' if not dl.receiver_did else f'older than {max_age_h:g} h'}"
                             f": read the ledger for fxroute:{dl.route_id}:egress-local before refunding or "
                             f"re-delivering")[:480]
            logger.error(f"[fx_router_keeper] egress_unknown route={dl.route_id}: {dl.last_error}")
            return "failed"
        ok, err, credited, tx = await _fx_route_local_egress(db, router_agent, router_did, dl.receiver_did,
                                                             str(dl.amount), dl.route_id)
        if ok:
            await _record_fx_delivery(db, route_id=dl.route_id, receiver_did=dl.receiver_did,
                                      amount=credited or dl.amount, currency=dl.currency,
                                      kind="egress-local", tx_id=tx)
            dl.status = "delivered"
            dl.resolution_tx = tx
            dl.resolved_at = _now()
            dl.last_error = None
            logger.info(f"[fx_router_keeper] egress_unknown route={dl.route_id} DELIVERED under its own key "
                        f"{dl.amount} {dl.currency} -> {dl.receiver_did} (tx={tx})")
            return "delivered"
        if _leg_moved_nothing(err):
            dl.phase = "pre_conversion"
            dl.last_error = f"the egress provably never ran ({err}): returned to the refund path"[:480]
            logger.warning(f"[fx_router_keeper] egress_unknown route={dl.route_id}: {dl.last_error}")
            return "to_refund"
        dl.retries = (dl.retries or 0) + 1
        dl.last_error = (err or "egress outcome still not known")[:480]
        if dl.retries >= max_retries:
            dl.status = "failed"
            logger.error(f"[fx_router_keeper] egress_unknown route={dl.route_id} still not known after {dl.retries} "
                         f"passes: held for a ledger read (fxroute:{dl.route_id}:egress-local)")
            return "failed"
        return "retry"

    # ── PART 3: §FXSELFHEAL — recover routes parked HERE by remote origins ───────────
    async def _peer_client(self, peer):
        """Outbound peer-authenticated client + base URL, mirroring federation_sync's
        contract exactly (mTLS SVID for https, license/internal-secret headers for http)."""
        import httpx
        from ..identity import svid_client
        from ..routers.teg_integration import _to_internal_mtls_url
        base = _to_internal_mtls_url((peer.base_url or "").rstrip("/"))
        if not base:
            return None, "no base_url"
        cfg: Dict[str, Any] = {"timeout": 20.0}
        headers = {}
        if base.startswith("https://"):
            cert_config = svid_client.get_client_cert_config(target_url=base)
            if not cert_config:
                # Return a REASON, never a silent skip: an inert keeper that cannot
                # authenticate must not be indistinguishable from a healthy idle one.
                # (Observed 2026-08-10 in a cold one-shot process, where the SVID cache
                # the running app warms at startup is empty.)
                return None, "no mTLS client cert available"
            cfg.update(cert_config)
        else:
            lic = os.environ.get("FEDERATION_LICENSE_KEY", "")
            if lic:
                headers = {"X-Federation-License": lic}
            else:
                headers = {"X-Federation-Secret": os.environ.get("FEDERATION_INTERNAL_SECRET", ""),
                           "X-Federation-SPIFFE-ID": svid_client.get_spiffe_id() or ""}
        if headers:
            cfg["headers"] = headers
        return httpx.AsyncClient(**cfg), base

    async def _origin_peers(self, db):
        """The bounded set of frames that can park at MY router: the configured FX gateway
        peers (a cross-currency route can only originate at a reserve frame in the directory).
        Iterating every ACTIVE peer would dial 14 cloud-ops that never originate FX routes."""
        from ..routers.teg_integration import _fx_route_peer_gateways, _fx_route_find_active_peer
        seen, peers = set(), []
        for g in _fx_route_peer_gateways():
            reg_id = str(g.get("registry_id", "")).strip()
            if not reg_id or reg_id in seen:
                continue
            seen.add(reg_id)
            p = await _fx_route_find_active_peer(db, reg_id)
            if p is not None:
                peers.append(p)
        return peers

    async def _deliver_one(self, db, router_agent, router_did: str, rid: str,
                           receiver_did: str, amount: str):
        """Deliver a recovered route to its intended receiver, local or remote."""
        from ..routers.teg_integration import (
            _fx_route_1to1_2pc, _fx_route_find_active_peer, _resolve_receiver_registry,
            _fx_route_local_egress, _LegError,
        )
        from .. import models
        rtid, rrid = await _resolve_receiver_registry(db, receiver_did)
        if not rtid:
            local_rcv = (await db.execute(
                select(models.Agent).where(models.Agent.did == receiver_did)
            )).scalar_one_or_none()
            if local_rcv is None:
                # nothing was posted: a refusal that proves nothing moved (§REPATLANE-3)
                return False, _LegError(f"cannot resolve receiver {receiver_did}", nothing_moved=True), None, None
            return await _fx_route_local_egress(db, router_agent, router_did, receiver_did,
                                                amount, rid)
        recv_peer = await _fx_route_find_active_peer(db, rrid) if rrid else None
        return await _fx_route_1to1_2pc(
            db, sender_agent=router_agent, sender_did=router_did, receiver_did=receiver_did,
            amount=amount, target_teg_id=rtid, target_registry_id=rrid, target_peer=recv_peer,
            memo=f"fxroute:{rid}:recovery")

    async def _process_remote_parked(self, db, cfg) -> Dict[str, Any]:
        from .. import models
        from ..routers.teg_integration import (
            _fx_route_local_router_did, _fx_route_already_delivered, _record_fx_delivery,
            _local_frame_currency, _fx_route_held_here, _leg_moved_nothing, _record_fx_dead_letter,
        )
        if not _rr_keeper_enabled():
            return {"enabled": False, "mode": _rr_mode()}
        router_did = _fx_route_local_router_did()
        if not router_did:
            return {"enabled": False, "reason": "no local @fx_router"}

        # GUARD 3 — single-writer. 2026-08-10: a peer session swept ~219 routes concurrently
        # with the manual runbook; zero collisions was luck plus the CAS, not design.
        from .leader import get_redis
        redis = None
        try:
            redis = await get_redis()
        except Exception:  # noqa: BLE001
            redis = None
        if redis is None:
            # FAIL CLOSED: without the lock we cannot guarantee single-writer, and this
            # path moves money. (Contrast the §FXEGRESS breaker, which fails OPEN because
            # it only ever REFUSES a transfer.)
            return {"skipped": "redis unavailable — refusing to recover without the writer lock"}
        lock_ttl = max(120, int(self.interval_sec) * 3)
        try:
            got = await redis.set(_RR_LOCK_KEY, self._frame, nx=True, ex=lock_ttl)
        except Exception as e:  # noqa: BLE001
            return {"skipped": f"lock error: {str(e)[:120]}"}
        if not got:
            return {"skipped": "another writer holds the lock"}

        router_agent = (await db.execute(
            select(models.Agent).where(models.Agent.did == router_did)
        )).scalar_one_or_none()
        if router_agent is None:
            try:
                await redis.delete(_RR_LOCK_KEY)
            except Exception:  # noqa: BLE001
                pass
            return {"skipped": "router agent missing"}

        ccy = _local_frame_currency()
        offered = recovered = already = released = skipped = unreachable = held = held_now = 0
        errors: list = []
        peers: list = []
        try:
            peers = await self._origin_peers(db)
            for peer in peers:
                client, base = await self._peer_client(peer)
                if client is None:
                    unreachable += 1
                    errors.append(f"{peer.name}: {base or 'unreachable'}")
                    continue
                async with client:
                    try:
                        resp = await client.get(
                            f"{base}/api/v1/federation/fx/parked-at",
                            params={"router_did": router_did,
                                    "min_age_sec": _rr_min_age_sec(),
                                    "limit": _rr_batch()})
                    except Exception as e:  # noqa: BLE001 — fail-open per peer
                        errors.append(f"{peer.name}: list {str(e)[:80]}")
                        continue
                    if resp.status_code == 404:
                        continue  # pre-§FXSELFHEAL peer: endpoints absent, nothing to do
                    if resp.status_code != 200:
                        errors.append(f"{peer.name}: list HTTP {resp.status_code}")
                        continue
                    rows = ((resp.json() or {}).get("rows") or [])
                    offered += len(rows)
                    for row in rows:
                        rid = str(row.get("route_id") or "")
                        receiver = str(row.get("receiver_did") or "")
                        amount = str(row.get("amount") or "0")
                        if not rid or not receiver or _D(amount) <= 0:
                            skipped += 1
                            continue

                        # GUARD 2 — already delivered? Checked BEFORE the claim so a paid
                        # route is never even claimed. Raises ⇒ fail closed ⇒ skip.
                        try:
                            prior = await _fx_route_already_delivered(db, rid)
                        except Exception:
                            skipped += 1
                            errors.append(f"{rid[:8]}: delivery-guard unavailable (fail closed)")
                            continue

                        # GUARD 2b (§REPATLANE-3, V0604) — does this frame HOLD the route? A held dead letter here (a
                        # 2PC egress whose outcome it could not learn) means its egress may already have paid: a
                        # re-delivery could pay twice. Skipped BEFORE the claim, so the origin row stays as it is until
                        # someone reads the ledger. Raises => fail closed => skip.
                        if prior is None:
                            try:
                                held_here = await _fx_route_held_here(db, rid)
                            except Exception:
                                skipped += 1
                                errors.append(f"{rid[:8]}: held-route guard unavailable (fail closed)")
                                continue
                            if held_here is not None:
                                held += 1
                                logger.warning(
                                    f"[fxselfheal] route={rid} is HELD here ({held_here['phase']}, "
                                    f"{held_here['status']}): not re-delivered; read the ledger first")
                                continue

                        # GUARD 1 — claim CAS on the ORIGIN row.
                        try:
                            cresp = await client.post(
                                f"{base}/api/v1/federation/fx/parked-claim",
                                json={"route_id": rid, "router_did": router_did})
                        except Exception as e:  # noqa: BLE001
                            errors.append(f"{rid[:8]}: claim {str(e)[:80]}")
                            continue
                        if cresp.status_code == 409:
                            skipped += 1
                            continue
                        if cresp.status_code != 200:
                            errors.append(f"{rid[:8]}: claim HTTP {cresp.status_code}")
                            continue

                        if prior is not None:
                            # Already paid from here — resolve the origin row as delivered,
                            # naming the ORIGINAL transaction. No money moves.
                            await self._resolve(client, base, router_did, rid, "delivered",
                                                tx=str(prior["tx_id"] or ""), errors=errors)
                            already += 1
                            logger.warning(
                                f"[fxselfheal] route={rid} was ALREADY delivered from here "
                                f"(kind={prior['kind']} tx={prior['tx_id']}) — marked delivered, NOT swept")
                            continue

                        ok, err, credited, tx = await self._deliver_one(
                            db, router_agent, router_did, rid, receiver, amount)
                        if ok:
                            # Record BEFORE resolving: if the resolve ack is lost, the origin
                            # row stays 'sweeping' (never auto-released) and this ledger row
                            # makes the next pass mark it delivered instead of paying twice.
                            await _record_fx_delivery(db, route_id=rid, receiver_did=receiver,
                                                      amount=credited or amount, currency=ccy,
                                                      kind="recovery", tx_id=tx)
                            await self._resolve(client, base, router_did, rid, "swept",
                                                tx=str(tx or ""), errors=errors)
                            recovered += 1
                            if FXK_REFUNDS is not None:
                                try: FXK_REFUNDS.labels(frame=self._frame, result="remote_recovered").inc()
                                except Exception: pass
                            logger.info(f"[fxselfheal] RECOVERED route={rid} {amount} {ccy} → "
                                        f"{receiver} (credited={credited} tx={tx})")
                        else:
                            if not _leg_moved_nothing(err):
                                # §REPATLANE-3 (V0604): the re-delivery may have paid the receiver (its answer was lost,
                                # or it failed after it could have moved), and sending it again could pay twice (a 2PC
                                # leg gets a fresh transfer id). This frame holds the route instead (redelivery_unknown,
                                # the transfer named in the note): GUARD 2b skips it from the next pass until someone
                                # reads the ledger. The origin row is released with that sentence.
                                _ref = tx or f"key fxroute:{rid}:egress-local"
                                await _record_fx_dead_letter(
                                    db, route_id=rid, origin_did=str(row.get("origin_did") or f"remote:{peer.name}"),
                                    amount=amount, currency=str(row.get("currency") or ccy), parked_at_did=router_did,
                                    phase="redelivery_unknown", receiver_did=receiver,
                                    note=f"the re-delivery's outcome is not known ({_ref}): {err}")
                                # read the hold back: without it the next pass would send the route again, so a hold
                                # that did not land leaves the origin row claimed (sweeping, never auto-released)
                                try:
                                    _held_ok = await _fx_route_held_here(db, rid) is not None
                                except Exception:  # noqa: BLE001
                                    _held_ok = False
                                if not _held_ok:
                                    skipped += 1
                                    errors.append(f"{rid[:8]}: outcome not known and not held here; the origin row "
                                                  f"stays claimed")
                                    logger.error(f"[fxselfheal] route={rid}: the re-delivery's outcome is not known and "
                                                 f"the hold could not be written: the origin row stays claimed "
                                                 f"(sweeping), so no pass sends it again; read the ledger ({_ref})")
                                    continue
                                held_now += 1
                                err = f"held at the delivering frame, outcome not known ({_ref}): {err}"
                            await self._resolve(client, base, router_did, rid, "released",
                                                err=(err or "delivery failed"), errors=errors)
                            released += 1
                            logger.warning(f"[fxselfheal] release route={rid}: {err}")
        finally:
            try:
                await redis.delete(_RR_LOCK_KEY)
            except Exception:  # noqa: BLE001
                pass

        # Observability: a keeper that CANNOT reach its origins is inert, and an inert keeper
        # must never look like a healthy idle one (the §EXTRAHOSTS/§COVERAGE lesson: degradation
        # whose only signal is log volume nobody measures). Silence here means "dialed every
        # origin, nothing to recover" — which is the honest steady state.
        if unreachable:
            logger.warning("[fxselfheal] %d/%d origin peer(s) unreachable — recovery is INERT "
                           "for those corridors: %s", unreachable, len(peers), "; ".join(errors[:3]))
        elif offered:
            logger.info("[fxselfheal] cycle: offered=%d recovered=%d already_delivered=%d "
                        "released=%d skipped=%d", offered, recovered, already, released, skipped)

        return {"enabled": True, "router_did": router_did, "peers": len(peers),
                "peers_unreachable": unreachable, "offered": offered,
                "recovered": recovered, "already_delivered": already, "released": released,
                "skipped": skipped, "held": held, "held_now": held_now, "errors": errors[:5]}

    async def _resolve(self, client, base: str, router_did: str, rid: str, outcome: str,
                       tx: str = "", err: str = "", errors: Optional[list] = None) -> None:
        body: Dict[str, Any] = {"route_id": rid, "router_did": router_did, "outcome": outcome}
        if outcome in ("swept", "delivered"):
            body["resolution_tx"] = tx
        if err:
            body["error"] = err[:480]
        try:
            r = await client.post(f"{base}/api/v1/federation/fx/parked-resolve", json=body)
            if r.status_code != 200 and errors is not None:
                errors.append(f"{rid[:8]}: resolve HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            if errors is not None:
                errors.append(f"{rid[:8]}: resolve {str(e)[:80]}")

    def _last_stats(self) -> Dict[str, Any]:
        return self._stats or {"enabled": self._should_run()}


def _now():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc)


_singleton: Optional[FxRouterKeeper] = None


async def start_fx_router_keeper() -> None:
    global _singleton
    if _singleton is not None:
        return
    _singleton = FxRouterKeeper()
    if not _singleton._should_run():
        logger.info("[fx_router_keeper] disabled via env gate (FX_ROUTER_KEEPER_ENABLED / FX_ROUTER_DID / FX_ENABLED)")
        return
    await _singleton.start()
    logger.info("[fx_router_keeper] STARTED (reserve-frame FX suspense liquidity manager)")


async def stop_fx_router_keeper() -> None:
    global _singleton
    if _singleton is None:
        return
    await _singleton.stop()
    _singleton = None


def get_fx_router_keeper() -> Optional[FxRouterKeeper]:
    return _singleton
