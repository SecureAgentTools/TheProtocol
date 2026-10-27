"""FX-reserve peg keeper (ratio-peg, move-only) — migration 0092, 2026-06-17.

Holds the cross-frame FX peg by keeping THIS frame's `@fx_reserve` (the AMM pool whose 3
balances DEFINE the rate) within a [min, target, max] band:

  - ANCHOR frame (cfg.anchor_currency): target = cfg.target_float (floats in a wide band).
  - TRACKING frames: each cycle read the anchor frame's `@fx_reserve` cross-frame and set
    target = clamp(anchor_reserve * ratio_vs_anchor, min, max).  ratio=1 + equal anchors ⇒ 1:1:1.

MOVE-ONLY: treasury <-> reserve via `_fx_teg_move` (Δ-neutral, kind=transfer). It NEVER mints —
if treasury can't fund a needed top-up the move fails and the keeper raises a 'treasury dry'
alert (manual op-gated mint is the Commander's lever). Δ=0/0/0 preserved by construction.

Gating: env `FX_RESERVE_KEEPER_ENABLED` (per frame, default false) AND the DB
`fx_reserve_keeper_config.enabled` toggle (FX-Desk editable). Both must be on. Leader-elected;
runs on reserve frames (registry-a AVT / frame-b JDAY / frame-c BVT). Config is re-read every
cycle so the FX Desk can enable/retune live without a redeploy. Clone of `fx_router_keeper`.
"""
from __future__ import annotations

import logging
import os
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from sqlalchemy import select

from ..database import get_db_context
from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter as _Counter, Gauge as _Gauge
    FXRK_MOVES = _Counter("fx_reserve_keeper_moves_total",
                          "FX reserve keeper peg moves", labelnames=["frame", "action"])
    FXRK_RESERVE = _Gauge("fx_reserve_keeper_reserve", "FX reserve balance", labelnames=["frame"])
    FXRK_DRIFT = _Gauge("fx_reserve_keeper_drift_pct", "reserve drift from target (fraction)", labelnames=["frame"])
    FXRK_DRY = _Counter("fx_reserve_keeper_treasury_dry_total",
                        "top-up shortfalls (treasury dry — manual mint needed)", labelnames=["frame"])
except Exception:
    FXRK_MOVES = FXRK_RESERVE = FXRK_DRIFT = FXRK_DRY = None


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def _D(v, default="0") -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


class FxReserveKeeper(BackgroundWorker):
    worker_id = "fx_reserve_keeper"
    leader_key = "fx_reserve_keeper:leader"
    interval_sec = 60
    cold_start_delay_sec = 25

    def __init__(self) -> None:
        super().__init__()
        self._frame = self._registry_id
        self._last_action: Dict[str, Any] = {}

    # ── gating ───────────────────────────────────────────────────────────────
    def _should_run(self) -> bool:
        if not _truthy(os.getenv("FX_RESERVE_KEEPER_ENABLED", "false")):
            return False
        if not _truthy(os.getenv("FX_ENABLED", "false")):
            return False  # FX booth must be live
        if not (os.getenv("TEG_API_BASE_URL", "") or "").strip():
            return False  # need a local TEG to read/move the reserve
        return True

    def _currency(self) -> str:
        try:
            from ..routers.teg_integration import _local_frame_currency
            return _local_frame_currency()
        except Exception:
            return "AVT"

    async def _load_config(self, db):
        from .. import models
        return (await db.execute(
            select(models.FxReserveKeeperConfig).where(models.FxReserveKeeperConfig.id == "singleton")
        )).scalar_one_or_none()

    async def _anchor_reserve(self, db, anchor_ccy: str, admin_key: str) -> Optional[Decimal]:
        """Read the ANCHOR frame's @fx_reserve cross-frame (mirrors fx_pool_admin discovery)."""
        from .. import models
        from ..routers.teg_integration import (
            _resolve_peer_currency, _resolve_dest_teg_mtls_base, _fx_read_reserve, _slug,
        )
        peers = (await db.execute(
            select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE")
        )).scalars().all()
        for p in peers:
            if (getattr(p, "peer_type", "") or "").lower() != "frame":
                continue
            c = await _resolve_peer_currency(db, target_peer=p)
            if c and c == anchor_ccy:
                pslug = _slug(p.name or "")
                if not pslug:
                    continue
                teg_id = f"teg-layer-{pslug.replace('registry-', '')}"
                reg_id = pslug if pslug.startswith("registry-") else f"registry-{pslug}"
                base = await _resolve_dest_teg_mtls_base(teg_id, reg_id)
                return await _fx_read_reserve(base, admin_key)
        return None

    # ── cycle ────────────────────────────────────────────────────────────────
    async def _cycle_once(self) -> None:
        from ..routers.teg_integration import _fx_read_reserve, _fx_teg_move, _fx_reserve_floor
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
            ccy = self._currency()
            teg_base = os.environ.get("TEG_API_BASE_URL", "http://teg-layer:8080")
            admin_key = os.environ.get("TEG_ADMIN_API_KEY", "")

            try:
                res = await _fx_read_reserve(teg_base, admin_key)
            except Exception as e:
                self._stats = {"enabled": True, "action": "skip", "reason": f"reserve read failed: {str(e)[:120]}"}
                return
            if FXRK_RESERVE is not None:
                try: FXRK_RESERVE.labels(frame=self._frame).set(float(res))
                except Exception: pass

            # ── derive target ──
            anchor = (cfg.anchor_currency or "AVT").strip().upper()
            if ccy == anchor:
                target = _D(cfg.target_float)
            else:
                ar = None
                try:
                    ar = await self._anchor_reserve(db, anchor, admin_key)
                except Exception as e:
                    logger.warning(f"[fx_reserve_keeper] anchor reserve read failed: {e}")
                target = (ar * _D(cfg.ratio_vs_anchor, "1")) if (ar and ar > 0) else _D(cfg.target_float)
                lo, hi = _D(cfg.min_float), _D(cfg.max_float)
                if lo > 0:
                    target = max(target, lo)
                if hi > 0:
                    target = min(target, hi)

            base_stats = {"enabled": True, "frame": self._frame, "currency": ccy, "mode": mode,
                          "reserve": str(res), "target": str(target), "anchor": anchor,
                          "last_action": self._last_action}
            if mode in ("off", "agent"):
                # stand down — observe only; the hard FX_RESERVE_FLOOR swap-path guard still applies,
                # and (mode='agent') an external agent drives via the guarded /move primitive (v2).
                self._stats = {**base_stats, "action": "stand_down"}
                return
            if target <= 0:
                self._stats = {**base_stats, "action": "skip", "reason": "target<=0 (unconfigured)"}
                return

            drift = (res - target) / target
            if FXRK_DRIFT is not None:
                try: FXRK_DRIFT.labels(frame=self._frame).set(float(drift))
                except Exception: pass
            dead = _D(cfg.deadband_pct, "0.05")
            if abs(drift) <= dead:
                self._stats = {**base_stats, "action": "in_band", "drift_pct": str(drift)}
                return

            cap = _D(cfg.max_move_per_cycle)

            # ── TOP-UP: reserve below target beyond the deadband → draw treasury → reserve ──
            if res < target:
                need = target - res
                if cap > 0:
                    need = min(need, cap)
                if need <= 0:
                    self._stats = {**base_stats, "action": "noop"}
                    return
                try:
                    r = await _fx_teg_move(teg_base, admin_key, from_did="@treasury", to_did="@fx_reserve",
                                           amount=need, reason="fx_reserve_keeper_topup", idem_key=str(uuid.uuid4()))
                    if r.status_code != 200:
                        if FXRK_DRY is not None:
                            try: FXRK_DRY.labels(frame=self._frame).inc()
                            except Exception: pass
                        logger.error(f"[fx_reserve_keeper] TOPUP FAILED {need} {ccy} (treasury dry? "
                                     f"manual mint needed): {r.text[:160]}")
                        self._stats = {**base_stats, "action": "topup_failed", "need": str(need),
                                       "detail": r.text[:160], "alert": "treasury_dry_manual_mint_needed"}
                        return
                    self._last_action = {"action": "topup", "amount": str(need)}
                    if FXRK_MOVES is not None:
                        try: FXRK_MOVES.labels(frame=self._frame, action="topup").inc()
                        except Exception: pass
                    logger.info(f"[fx_reserve_keeper] TOPUP {need} {ccy} @treasury→@fx_reserve "
                                f"(reserve {res}→~{target})")
                    self._stats = {**base_stats, "action": "topup", "amount": str(need)}
                    return
                except Exception as e:
                    logger.error(f"[fx_reserve_keeper] topup error: {e}")
                    self._stats = {**base_stats, "action": "topup_error", "error": str(e)[:160]}
                    return

            # ── SWEEP: reserve above target beyond the deadband → return excess reserve → treasury ──
            else:
                excess = res - target
                if cap > 0:
                    excess = min(excess, cap)
                floor = _fx_reserve_floor(ccy)
                if floor > 0:
                    excess = min(excess, res - floor)  # never sweep below the hard floor
                if excess <= 0:
                    self._stats = {**base_stats, "action": "noop"}
                    return
                try:
                    r = await _fx_teg_move(teg_base, admin_key, from_did="@fx_reserve", to_did="@treasury",
                                           amount=excess, reason="fx_reserve_keeper_sweep", idem_key=str(uuid.uuid4()),
                                           floor=(floor if floor > 0 else None))
                    if r.status_code != 200:
                        logger.error(f"[fx_reserve_keeper] SWEEP FAILED {excess} {ccy}: {r.text[:160]}")
                        self._stats = {**base_stats, "action": "sweep_failed", "detail": r.text[:160]}
                        return
                    self._last_action = {"action": "sweep", "amount": str(excess)}
                    if FXRK_MOVES is not None:
                        try: FXRK_MOVES.labels(frame=self._frame, action="sweep").inc()
                        except Exception: pass
                    logger.info(f"[fx_reserve_keeper] SWEEP {excess} {ccy} @fx_reserve→@treasury "
                                f"(reserve {res}→~{target})")
                    self._stats = {**base_stats, "action": "sweep", "amount": str(excess)}
                    return
                except Exception as e:
                    logger.error(f"[fx_reserve_keeper] sweep error: {e}")
                    self._stats = {**base_stats, "action": "sweep_error", "error": str(e)[:160]}
                    return


_singleton: Optional[FxReserveKeeper] = None


async def start_fx_reserve_keeper() -> None:
    global _singleton
    if _singleton is not None:
        return
    _singleton = FxReserveKeeper()
    if not _singleton._should_run():
        logger.info("[fx_reserve_keeper] disabled via env gate "
                    "(FX_RESERVE_KEEPER_ENABLED / FX_ENABLED / TEG_API_BASE_URL)")
        return
    await _singleton.start()
    logger.info("[fx_reserve_keeper] STARTED (cross-frame FX peg keeper, move-only)")


async def stop_fx_reserve_keeper() -> None:
    global _singleton
    if _singleton is None:
        return
    await _singleton.stop()
    _singleton = None


def get_fx_reserve_keeper() -> Optional[FxReserveKeeper]:
    return _singleton
