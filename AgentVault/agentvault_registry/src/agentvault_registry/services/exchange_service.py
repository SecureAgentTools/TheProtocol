"""
AGORA — organization stock exchange: the venue service (2026-06-12).

Contract: sessionlogs2026/STRATEGY_2026-06-12_AGORA_LOCKED_IMPLEMENTATION.md
(decisions D1–D25). Architecture in one breath:

  SHARES live HERE (registry tables, migration 0088) and never touch the TEG.
  MONEY moves exclusively through the TEG escrow mover
  (POST {TEG}/api/v1/admin/exchange/move — escrow-one-side, "exref:{key}"
  idempotent replay, solvency floor) so every leg is a plain transfer →
  transit-neutral → supply Δ=0 by construction. The venue is therefore
  crash-safe by state machine, not by luck:

    BUY order : insert(status='funding') → deposit leg → advisory-lock tx
                (flip open → match → trades 'pending_settlement') ;
                worker settles trade legs / refunds residual escrow.
    SELL order: one advisory-lock tx (lock shares → insert open → match).
    IPO       : insert(funding) → deposit leg → lock tx allocate-or-refund ;
                worker moves proceeds to the org treasury agent.
    DIVIDEND  : snapshot legs under lock ; worker funds ONE pot leg
                (treasury → escrow) then pays per-holder legs.

  Per-listing serialization = pg_advisory_xact_lock(hashtext('agora:'||id)):
  share legs + book mutations are single-DB ACID; the only deferred piece is
  money settlement, which is escrow-held and exref-replay-idempotent (I-X3/I-X4).

  COMPLIANCE (D25 — "no anonymous ghosts"): every trading DID must have an
  exchange_participants row. Local agents auto-verify from the local developer
  record; foreign agents verify via DevCard (§9 Passport, flag-gated).

  FEES (D3/D19 refined): fee_total = notional × fee_bps/10000 (ROUND_DOWN),
  deducted from SELLER proceeds (buyer pays exactly notional, so buy escrow
  is exact even on price-improved fills). fee_org : fee_proto split per listing.

Invariants this module can self-check (GET /exchange/admin/invariant):
  I-X1 share conservation : Σ positions.qty == (total−float) + ipo_sold   (per listing, post-approve)
  I-X2 lock honesty       : Σ positions.locked_qty == Σ open SELL remaining
  I-X3 escrow solvency    : TEG escrow balance == Σ buy-order holds + Σ unsettled
                            trade notionals + Σ unpaid dividend legs (funded pots)
                            + Σ IPO deposits awaiting proceeds/refund + parked listing fees
  I-X4 settlement liveness: no pending_settlement older than EXCHANGE_SETTLE_SLO_SEC
"""
from __future__ import annotations

from ..core.agora_paths import peer_request as _peer_request  # §AGORAWORDS Phase 5
import asyncio
import logging
import os
import re
import time
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import String, and_, column, func, or_, select, text, values
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.config import settings
from agentvault_registry.core.exchange_metrics import (
    agora_order_placed,
    agora_repat_outcome,
    agora_set_invariants,
    agora_trade_executed,
)
from agentvault_registry.es_ssl_helper import get_httpx_verify
from agentvault_registry.event_emitter import get_event_emitter
from agentvault_registry.models import (
    Agent,
    AgentCard,
    Developer,
    ExchangeDividend,
    ExchangeDividendLeg,
    ExchangeFlag,
    ExchangeGatewayCredit,
    ExchangeIpoPurchase,
    ExchangeListing,
    ExchangeMarketMaker,
    ExchangeOrder,
    ExchangeParticipant,
    ExchangeProposal,
    ExchangeProposalHolder,
    ExchangeProposalVote,
    ExchangeTrade,
    Organization,
    OrgSharePosition,
    TreasuryMMConfig,
)
from agentvault_registry.services.organization_service import OrganizationService
from agentvault_registry.services import payout_outcome  # §REPATLANE (V0603)

logger = logging.getLogger(__name__)

# ── config ────────────────────────────────────────────────────────────────
TEG_API_BASE_URL = getattr(settings, "TEG_API_BASE_URL", "http://teg-layer:8080")
TEG_API_V1_PREFIX = "/api/v1"
TEG_ADMIN_API_KEY = getattr(settings, "TEG_ADMIN_API_KEY", "")

EXCHANGE_ENABLED = os.getenv("EXCHANGE_ENABLED", "false").lower() == "true"
REQUIRE_COMPLIANT_PARTICIPANT = os.getenv(
    "EXCHANGE_REQUIRE_COMPLIANT_PARTICIPANT", "true"
).lower() == "true"
LISTING_FEE = Decimal(os.getenv("EXCHANGE_LISTING_FEE", "1000"))
MAX_OPEN_ORDERS_PER_AGENT = int(os.getenv("EXCHANGE_MAX_OPEN_ORDERS", "20"))
MAX_ORDER_NOTIONAL = Decimal(os.getenv("EXCHANGE_MAX_NOTIONAL", "1000000"))
MARKET_SLIPPAGE_PCT = Decimal(os.getenv("EXCHANGE_MARKET_SLIPPAGE_PCT", "10"))
SETTLE_SLO_SEC = int(os.getenv("EXCHANGE_SETTLE_SLO_SEC", "300"))
FUNDING_RETRY_AFTER_SEC = int(os.getenv("EXCHANGE_FUNDING_RETRY_SEC", "30"))
# §settlement-resilience (2026-06-13): a settlement leg uses a SHORTER mover
# timeout than the order path so one convoyed leg can't outlive the 30s leader
# lease (which caused overlapping batches → escrow hot-row collapse on frame-b).
# Sized so worst-case-single-trade (3 legs) + the cycle budget stays < the 30s
# LOCK_TTL: 3×5s + 12s = 27s. Safe to fail-fast at 5s (< the 10s TEG lock GUC)
# now the exref UNIQUE index backstops any timed-out-but-committed leg.
SETTLE_LEG_TIMEOUT_S = float(os.getenv("EXCHANGE_SETTLE_LEG_TIMEOUT_S", "5"))
SETTLE_BATCH = int(os.getenv("EXCHANGE_SETTLE_BATCH", "20"))
# §2026-06-22 P2.2 maker-taker pricing. OFF by default ⇒ maker_rebate_bps is treated as
# 0 EVERYWHERE (no carve at match, no rebate leg at settle) — byte-for-byte current
# behaviour. When on, the rebate is carved from the protocol fee slice (Δ=0, proven in
# _match) and paid to the resting (maker) order at settlement.
MAKER_REBATE_ENABLED = os.getenv("EXCHANGE_MAKER_REBATE_ENABLED", "").strip().lower() in ("1", "true", "yes")

EXCHANGE_ESCROW_SENTINEL = "@exchange_escrow"
FEE_COLLECTOR_SENTINEL = "@fee_collector"
Q18 = Decimal("0.000000000000000001")
ZERO = Decimal("0")


class ExchangeError(Exception):
    """Service-level error → the router maps to an HTTP response."""

    def __init__(self, status_code: int, detail: str, headers: Optional[Dict[str, str]] = None):
        self.status_code = status_code
        self.detail = detail
        self.headers = headers   # §LEDGERGATE (V0598): Retry-After when the TEG's ledger refused
        super().__init__(detail)


# ── TEG mover client ──────────────────────────────────────────────────────
class MoverError(ExchangeError):
    pass


class ExchangeMover:
    """Thin client for the TEG escrow mover. Every call is replay-idempotent
    on the TEG side (attached_message == 'exref:{idempotency_key}')."""

    def __init__(self) -> None:
        self._base = f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/admin/exchange"
        self._headers = {"Authorization": f"Bearer {TEG_ADMIN_API_KEY}"}

    async def move(
        self,
        from_did: str,
        to_did: str,
        amount: Decimal,
        reason: str,
        idempotency_key: str,
        floor: Optional[Decimal] = None,
        timeout_s: float = 35.0,
    ) -> Dict[str, Any]:
        if amount <= ZERO:  # zero-fee legs etc. — nothing to move
            return {"status": "skipped_zero", "transaction_id": None}
        body: Dict[str, Any] = {
            "from_did": from_did,
            "to_did": to_did,
            "amount": str(amount),
            "reason": reason,
            "idempotency_key": idempotency_key,
        }
        if floor is not None:
            body["floor"] = str(floor)
        # 2026-06-13: ONE attempt, NEVER an immediate retry. The exref replay
        # guard is a lookup, not a constraint — a timed-out attempt can still be
        # sitting in the TEG's pool/lock queue, so an instant retry races it:
        # the retry's replay lookup sees nothing, both eventually commit, and
        # the leg executes twice (frame-b incident 2026-06-13, 1,850 duplicate
        # legs / 3.6k AVT escrow drain). Worker cycles are the retry path; the
        # TEG-side partial UNIQUE index on exref rows (TEG migration 0004) makes
        # even those collisions roll back. 35s ceiling clears the 10s
        # lock_timeout GUC convoy that caused the original 20s 502s.
        # 2026-06-13 (settlement resilience): callers under a leader lease pass a
        # SHORTER timeout_s (the settlement worker uses 8s) so a single convoyed
        # leg can't outlive the 30s leader lease and trigger overlapping batches.
        async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
            try:
                resp = await client.post(
                    f"{self._base}/move", json=body, headers=self._headers, timeout=timeout_s
                )
            except httpx.TimeoutException as e:
                logger.warning(f"[AGORA-mover] move timeout ({idempotency_key}) — worker cycle retries")
                raise MoverError(502, f"exchange mover timeout: {type(e).__name__}") from e
            except httpx.HTTPError as e:
                raise MoverError(502, f"exchange mover unreachable: {type(e).__name__}: {e}") from e
        if resp.status_code == 200:
            return resp.json()
        # §LEDGERGATE (V0598): the TEG's ledger gate refused the move (nothing moved): passed on as it came (503, the
        # sentence, Retry-After), never as a 502 "exchange mover 503: ..."
        from .ledger_unavailable import ledger_refusal
        _refusal = ledger_refusal(resp)
        if _refusal is not None:
            raise MoverError(503, _refusal.detail, headers=_refusal.headers)
        try:
            detail = resp.json().get("detail", resp.text[:200])
        except Exception:
            detail = resp.text[:200]
        raise MoverError(
            400 if resp.status_code == 400 else 502,
            f"exchange mover {resp.status_code}: {detail}",
        )

    async def escrow_balance(self) -> Decimal:
        async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
            try:
                resp = await client.get(
                    f"{self._base}/escrow", headers=self._headers, timeout=10.0
                )
            except httpx.HTTPError as e:
                raise MoverError(502, f"exchange mover unreachable: {e}") from e
        if resp.status_code != 200:
            raise MoverError(502, f"escrow info {resp.status_code}")
        return Decimal(str(resp.json()["balance"]))

    async def agent_balance(self, did: str) -> Decimal:
        """§V0064 P2 — gateway-solvency read for I-X5 (TEG admin balance/{did})."""
        async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
            try:
                resp = await client.get(
                    f"{self._base}/balance/{did}", headers=self._headers, timeout=10.0
                )
            except httpx.HTTPError as e:
                raise MoverError(502, f"exchange mover unreachable: {e}") from e
        if resp.status_code != 200:
            raise MoverError(502, f"balance read {resp.status_code}")
        return Decimal(str(resp.json()["balance"]))


mover = ExchangeMover()


def _deposit_failed(e: MoverError, what: str) -> ExchangeError:
    """§LEDGERGATE (V0598): what a refused deposit raises. The ledger gate's refusal passes on whole (nothing moved; try
    again shortly); any other failure keeps its words with what failed in front."""
    from .ledger_unavailable import refusal_from_error
    _refusal = refusal_from_error(e)
    if _refusal is not None:
        return ExchangeError(_refusal.status_code, _refusal.detail, headers=_refusal.headers)
    return ExchangeError(e.status_code, f"{what}: {e.detail}")

# §V0064 P2 repatriation — the venue deposit gateway (exchange_passport owns
# creation). §2026-06-15: FRAME-SPECIFIC (derive from FRAME_CURRENCY) — a single
# shared DID across A/B/C broke cross-frame /teg/send receiver resolution
# (MultipleResultsFound) + federation card-sync (uix_agent_cards_agent_did dup).
# Foreign dividends/refunds park HERE; batch I drains them home.
def venue_gateway_slug() -> str:
    """This venue's own slug — empty on a mainframe.

    §VENUEGW 2026-08-26. One level up from the per-FRAME split above, for the same
    reason: a shared DID names an account somebody else's ledger holds. Per-frame was
    not enough, because a cloud-op shares its frame's CURRENCY but keeps its OWN TEG —
    so a currency-only DID names an account on the FRAME's ledger that the op's venue
    sweeper polls for and can never see, and every inbound passport buy sits in
    'funding' until it expires. Measured before the change: registry-a 221,045 filled
    passport orders, frame-b 227,600, and every cloud-op ZERO, ever.

    Mainframes keep the currency-only DID BY CONSTRUCTION (empty slug), so no live
    gateway balance and none of those 448k orders move.
    """
    if (os.getenv("IS_CENTRAL_REGISTRY", "false") or "").strip().lower() in ("1", "true", "yes"):
        return ""
    raw = (os.getenv("AGORA_GATEWAY_SLUG") or os.getenv("REGISTRY_NAME") or "").strip().lower()
    if raw.startswith("cloud-op-"):
        raw = raw[len("cloud-op-"):]
    slug = "".join(ch if (ch.isalnum() or ch == "-") else "-" for ch in raw).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    if not slug:
        # A non-central registry with no name cannot scope its gateway. Fall back to
        # the currency-only DID (today's behaviour, so nothing breaks) and SAY so —
        # silently sharing a money account is how this class started.
        logger.warning(
            "[AGORA] no REGISTRY_NAME/AGORA_GATEWAY_SLUG on a non-central registry — "
            "gateway falls back to the frame-wide DID; inbound passport buys cannot settle here"
        )
    return slug


def gateway_did() -> str:
    """The deposit gateway this venue owns, on this venue's own TEG."""
    ccy = (os.getenv("FRAME_CURRENCY", "AVT") or "AVT").strip().lower()
    slug = venue_gateway_slug()
    # Currency LAST on purpose: both shapes end in the currency, so every existing
    # `rsplit("-", 1)` currency read stays correct (there is one, in exchange.py).
    return f"did:theprotocol:agora-gateway-{slug + '-' if slug else ''}{ccy}"


GATEWAY_DID = gateway_did()
REPAT_DUST = Decimal(os.getenv("EXCHANGE_REPAT_DUST", "0.5"))
REPAT_MAX_ATTEMPTS = int(os.getenv("EXCHANGE_REPAT_MAX_ATTEMPTS", "6"))
# §REPATLANE (V0603): the payout lane's states besides pending / paid / failed / abandoned. 'sending' (per credit) and
# 'batched' (a bundle of fragments) are claimed for a send whose answer has not been applied yet; 'unresolved' is a payout
# that may have moved (services/payout_outcome.py) and is never sent again on its own. All three are still owed until
# the ledger says otherwise, so the float keeper, the sweep reserve and I-X5 count the first two; 'unresolved' is shown
# on its own (it may already have reached the trader).
REPAT_SENDING, REPAT_BATCHED, REPAT_UNRESOLVED = "sending", "batched", "unresolved"
REPAT_OWED_STATUSES = ("pending", REPAT_SENDING, REPAT_BATCHED)

# §GATEWAYROLE (2026-09-24): the gateway was born with no role on every frame, so IRONKEY refused every repatriation
# it signed; each refusal counted as a delivery attempt, parked the credit as 'failed' after six, and a re-arm loop
# replayed it (6,876 credits and a fleet warning storm on the sandbox pair). Now the gateway's role is healed before
# the first send of each process, and a permission refusal is not an attempt: the credit waits, and ONE line per
# cycle says why.
_GATEWAY_ROLE_OK = False
_PERM_REFUSAL = re.compile(r"lacks required permission:\s*([a-z_.]+)")


async def _ensure_gateway_role_once(db: AsyncSession) -> None:
    global _GATEWAY_ROLE_OK
    if _GATEWAY_ROLE_OK:
        return
    from agentvault_registry.services import exchange_passport as _pp  # lazy: exchange_passport imports this module
    if (await db.execute(select(Agent.id).where(Agent.did == GATEWAY_DID))).first() is None:
        return  # no gateway yet: check again next cycle
    if await _pp.ensure_gateway_role(db):
        await db.commit()
    _GATEWAY_ROLE_OK = True


def _permission_refused(r) -> Optional[str]:
    """The permission a 403 names when IRONKEY refused the SENDER (the gateway itself), else None.
    (services/payout_outcome.permission_refused reads the same regex for the lane.)"""
    if r is None or r.status_code != 403:
        return None
    m = _PERM_REFUSAL.search(r.text or "")
    return m.group(1) if m else None


# ── helpers ───────────────────────────────────────────────────────────────
def q18(d: Decimal) -> Decimal:
    return d.quantize(Q18, rounding=ROUND_DOWN)


def fee_split(notional: Decimal, fee_bps: int, org_split_bps: int) -> Tuple[Decimal, Decimal, Decimal]:
    """(fee_total, fee_org, fee_proto) per D19 — remainder goes to protocol."""
    fee_total = q18(notional * Decimal(fee_bps) / Decimal(10000))
    fee_org = q18(fee_total * Decimal(org_split_bps) / Decimal(10000))
    fee_proto = fee_total - fee_org
    return fee_total, fee_org, fee_proto


async def _is_active_market_maker(db: AsyncSession, listing_id: str, agent_did: str) -> bool:
    """§2026-06-22 P2.2 — does `agent_did` hold an ACTIVE designated-MM seat on this
    listing? (rebate eligibility gate when rebate_requires_registration is true.)"""
    row = (
        await db.execute(
            select(ExchangeMarketMaker.id).where(
                ExchangeMarketMaker.listing_id == listing_id,
                ExchangeMarketMaker.agent_did == agent_did,
                ExchangeMarketMaker.status == "active",
            )
        )
    ).first()
    return row is not None


async def _compute_maker_rebate(
    db: AsyncSession, listing: ExchangeListing, notional: Decimal, fee_total: Decimal,
    fee_org: Decimal, maker_did: str,
) -> Decimal:
    """§2026-06-22 P2.2 — the maker rebate carved from the PROTOCOL fee slice.

    Returns 0 unless the flag is on AND listing.maker_rebate_bps>0 AND (registration not
    required OR maker_did holds an active MM seat). The value is bounded so it can never
    exceed the protocol slice:
        rebate = min(fee_total − fee_org, notional · maker_rebate_bps/1e4)
    The caller re-derives fee_proto = fee_total − fee_org − rebate (always ≥0), so the
    four settlement legs still sum to notional (Δ=0). The taker still pays exactly
    fee_total — the network gives up its slice, the org split is untouched."""
    if not MAKER_REBATE_ENABLED:
        return ZERO
    bps = getattr(listing, "maker_rebate_bps", 0) or 0
    if bps <= 0:
        return ZERO
    if getattr(listing, "rebate_requires_registration", True):
        if not await _is_active_market_maker(db, listing.id, maker_did):
            return ZERO
    proto_slice = fee_total - fee_org  # = fee_proto before the carve, always ≥0
    if proto_slice <= ZERO:
        return ZERO
    want = q18(notional * Decimal(bps) / Decimal(10000))
    return want if want < proto_slice else proto_slice


async def _listing_lock(db: AsyncSession, listing_id: str) -> None:
    """Per-listing serialization. MUST be called inside the transaction that
    performs the book/share mutations — released at commit/rollback."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"agora:{listing_id}"}
    )


def _emit(event_type: str, listing_id: str, data: Dict[str, Any], key: str) -> None:
    """Registry-side domain event (skip_in_projection policy rows seeded in 0088).
    aggregate_id = listing_id → ES fans out on the agent:{listing_id} channel,
    which the Exchange Desk subscribes for per-listing live updates.
    ALL Decimals must already be str() (VoteCast Decimal-loss gotcha)."""
    try:
        get_event_emitter().emit_background(
            event_type=event_type,
            aggregate_id=listing_id,
            aggregate_type="ExchangeListing",
            data=data,
            idempotency_key=key,
        )
    except Exception as e:  # emission must never break money paths
        logger.warning(f"[AGORA] emit {event_type} failed (non-fatal): {e}")


async def get_flag(db: AsyncSession, key: str) -> Optional[str]:
    row = (await db.execute(select(ExchangeFlag).where(ExchangeFlag.key == key))).scalar_one_or_none()
    return row.value if row else None


async def set_flag(db: AsyncSession, key: str, value: str) -> None:
    row = (await db.execute(select(ExchangeFlag).where(ExchangeFlag.key == key))).scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(ExchangeFlag(key=key, value=value))
    await db.commit()


# ============================================================================
# §2026-06-25 AGORA Director "Campaign Engine" v1 (registry-only; design =
# sessionlogs2026/STRATEGY_2026-06-24_AGORA_DIRECTOR_CAMPAIGN_ENGINE.md).
# Drives the EXISTING demand_director flag through scripted, timed phases — the
# sim already polls /demand-director each cycle, so NO sim edit. State lives in
# flag 'agora_campaign'; the settlement worker calls step_active_campaign() each
# cycle. Δ-IRRELEVANT (only biases the sim's own order generation; bounded by the
# abs floor/ceiling + the circuit-breaker — moves no money, touches no balance).
# ============================================================================
CAMPAIGN_SOFTPEG_DIR = -1.0
CAMPAIGN_SOFTPEG_STRENGTH = 0.04
CAMPAIGN_PRESETS = {
    "bull_run": {"name": "bull_run", "description": "Sustained rally on the targets.",
        "on_finish": "restore_softpeg", "phases": [
            {"name": "accumulate", "duration_sec": 180, "targets": ["*"], "dir": 1, "curve": {"from": 0.06, "to": 0.18, "shape": "ease_in"}, "intensity": 0.2},
            {"name": "breakout",   "duration_sec": 300, "targets": ["*"], "dir": 1, "curve": {"from": 0.18, "to": 0.42, "shape": "ease_in"}, "regime": "euphoria", "intensity": 0.5}]},
    "flash_crash": {"name": "flash_crash", "description": "Sharp drop, then recovery.",
        "on_finish": "restore_softpeg", "phases": [
            {"name": "crash",    "duration_sec": 90,  "targets": ["*"], "dir": -1, "strength": 0.8, "regime": "panic", "intensity": 0.9, "volatility": 0.8},
            {"name": "recovery", "duration_sec": 360, "targets": ["*"], "dir": 1,  "curve": {"from": 0.35, "to": 0.08, "shape": "ease_out"}, "intensity": 0.3}]},
    "pump_and_dump": {"name": "pump_and_dump", "description": "Ramp up, then dump.",
        "on_finish": "restore_softpeg", "phases": [
            {"name": "pump", "duration_sec": 300, "targets": ["*"], "dir": 1,  "curve": {"from": 0.1, "to": 0.5, "shape": "linear"}, "regime": "euphoria", "intensity": 0.6},
            {"name": "dump", "duration_sec": 150, "targets": ["*"], "dir": -1, "strength": 0.7, "regime": "panic", "intensity": 0.8, "volatility": 0.6}]},
    "soft_peg": {"name": "soft_peg", "description": "Hold near fair (the baseline).",
        "on_finish": "hold", "phases": [
            {"name": "hold", "duration_sec": 86400, "targets": ["*"], "dir": CAMPAIGN_SOFTPEG_DIR, "strength": CAMPAIGN_SOFTPEG_STRENGTH}]},
}


def _campaign_curve(phase: dict, frac: float) -> float:
    """Strength at fraction frac in [0,1] through a phase (curve interpolation or flat)."""
    frac = max(0.0, min(1.0, frac))
    c = (phase or {}).get("curve")
    if not c:
        try:
            return max(0.0, min(1.0, float((phase or {}).get("strength", 0.0))))
        except (ValueError, TypeError):
            return 0.0
    try:
        a = float(c.get("from", 0.0)); b = float(c.get("to", 0.0))
    except (ValueError, TypeError):
        return 0.0
    shape = c.get("shape", "linear")
    if shape == "ease_in":     w = frac * frac
    elif shape == "ease_out":  w = 1.0 - (1.0 - frac) * (1.0 - frac)
    elif shape == "spike":     w = 1.0 - abs(2.0 * frac - 1.0)
    elif shape == "sawtooth":  w = (frac * 4.0) % 1.0
    else:                      w = frac
    return max(0.0, min(1.0, a + (b - a) * w))


async def _resolve_campaign_targets(db: AsyncSession, targets) -> list:
    """Expand targets to local trading symbols: 'SYM' | 'venue:<ccy>'/'currency:<ccy>' | '*'."""
    syms = set(); all_l = None
    for t in (targets or ["*"]):
        t = str(t)
        if t == "*" or t.startswith("venue:") or t.startswith("currency:"):
            if all_l is None:
                all_l = (await db.execute(select(ExchangeListing).where(ExchangeListing.status == "trading"))).scalars().all()
            if t == "*":
                syms.update(l.symbol for l in all_l)
            else:
                ccy = t.split(":", 1)[1].upper()
                syms.update(l.symbol for l in all_l if (l.currency or "").upper() == ccy)
        else:
            syms.add(t.upper())
    return sorted(syms)


def _campaign_locate_phase(camp: dict, elapsed: float):
    """Return (phase, phase_elapsed, idx) for the wall-clock elapsed, or (None, t_total, -1) if finished."""
    t = 0.0
    for i, ph in enumerate(camp.get("phases", [])):
        dur = float(ph.get("duration_sec", 0) or 0)
        if elapsed < t + dur:
            return ph, elapsed - t, i
        t += dur
    return None, t, -1


async def start_campaign(db: AsyncSession, campaign: dict) -> dict:
    """Begin a campaign (validated dict). Persists the 'agora_campaign' flag; the worker
    drives the demand_director from it each cycle. Idempotent overwrite (replaces any active)."""
    import json
    if not isinstance(campaign, dict) or not campaign.get("phases"):
        raise ExchangeError(422, "campaign needs phases")
    for ph in campaign["phases"]:
        if not isinstance(ph, dict) or "duration_sec" not in ph:
            raise ExchangeError(422, "each phase needs duration_sec")
        try:
            d = float(ph.get("dir", 0))
        except (ValueError, TypeError):
            raise ExchangeError(422, "phase dir must be numeric")
        if d < -1.0 or d > 1.0:
            raise ExchangeError(422, "phase dir must be -1..1")
    state = {"active": True, "campaign": campaign, "started_at": datetime.now(timezone.utc).timestamp()}
    await set_flag(db, "agora_campaign", json.dumps(state))
    return {"started": True, "name": campaign.get("name"), "phases": len(campaign["phases"])}


async def stop_campaign(db: AsyncSession, restore_softpeg: bool = True) -> dict:
    """Stop the active campaign; optionally restore the uniform soft-peg director."""
    import json
    await set_flag(db, "agora_campaign", json.dumps({"active": False}))
    if restore_softpeg:
        syms = await _resolve_campaign_targets(db, ["*"])
        await set_flag(db, "demand_director", json.dumps({"enabled": True,
            "tickers": {s: {"dir": CAMPAIGN_SOFTPEG_DIR, "strength": CAMPAIGN_SOFTPEG_STRENGTH} for s in syms}}))
    return {"stopped": True, "restored_softpeg": restore_softpeg}


async def campaign_status(db: AsyncSession) -> dict:
    import json
    raw = await get_flag(db, "agora_campaign")
    if not raw:
        return {"active": False}
    try:
        state = json.loads(raw)
    except (ValueError, TypeError):
        return {"active": False}
    if not state.get("active"):
        return {"active": False}
    camp = state.get("campaign", {}) or {}
    elapsed = datetime.now(timezone.utc).timestamp() - float(state.get("started_at", 0) or 0)
    cur, pe, idx = _campaign_locate_phase(camp, elapsed)
    total = sum(float(p.get("duration_sec", 0) or 0) for p in camp.get("phases", []))
    dur = float((cur or {}).get("duration_sec", 1) or 1)
    return {"active": True, "name": camp.get("name"), "elapsed_sec": round(elapsed, 1), "total_sec": total,
            "phase": (cur.get("name") if cur else "finished"), "phase_idx": idx, "phase_elapsed_sec": round(pe, 1),
            "current_dir": (cur.get("dir") if cur else None),
            "current_strength": (round(_campaign_curve(cur, pe / dur), 4) if cur else None)}


async def step_active_campaign(db: AsyncSession, batch: int = 0) -> int:
    """Settlement-worker batch: drive the demand_director from the active campaign. No-op when
    no campaign is active. On finish -> on_finish (restore_softpeg|flat|hold) or loop. Δ-irrelevant."""
    import json
    raw = await get_flag(db, "agora_campaign")
    if not raw:
        return 0
    try:
        state = json.loads(raw)
    except (ValueError, TypeError):
        return 0
    if not state.get("active"):
        return 0
    camp = state.get("campaign", {}) or {}
    if not camp.get("phases"):
        return 0
    elapsed = datetime.now(timezone.utc).timestamp() - float(state.get("started_at", 0) or 0)
    cur, pe, _idx = _campaign_locate_phase(camp, elapsed)
    if cur is None:
        if camp.get("loop"):
            state["started_at"] = datetime.now(timezone.utc).timestamp()
            await set_flag(db, "agora_campaign", json.dumps(state))
            return 1
        on_finish = camp.get("on_finish", "restore_softpeg")
        await set_flag(db, "agora_campaign", json.dumps({"active": False}))
        if on_finish == "restore_softpeg":
            syms = await _resolve_campaign_targets(db, ["*"])
            await set_flag(db, "demand_director", json.dumps({"enabled": True,
                "tickers": {s: {"dir": CAMPAIGN_SOFTPEG_DIR, "strength": CAMPAIGN_SOFTPEG_STRENGTH} for s in syms}}))
        elif on_finish == "flat":
            await set_flag(db, "demand_director", json.dumps({"enabled": False, "tickers": {}}))
        logger.info(f"[AGORA-campaign] '{camp.get('name')}' finished (on_finish={on_finish})")
        return 1
    dur = float(cur.get("duration_sec", 1) or 1)
    strength = _campaign_curve(cur, pe / dur)
    try:
        d = float(cur.get("dir", 0))
    except (ValueError, TypeError):
        d = 0.0
    syms = await _resolve_campaign_targets(db, cur.get("targets", ["*"]))
    if syms:
        _entry = {"dir": d, "strength": round(strength, 4)}
        for _k in ("intensity", "volatility"):   # §2026-06-25 v2 per-phase enrichments (E1 volume / E2 vol)
            try:
                if cur.get(_k) is not None:
                    _entry[_k] = max(0.0, min(1.0, float(cur.get(_k))))
            except (ValueError, TypeError):
                pass
        if cur.get("regime"):                     # §v2 E3 regime
            _entry["regime"] = str(cur.get("regime"))
        await set_flag(db, "demand_director", json.dumps({"enabled": True,
            "tickers": {s: _entry for s in syms}}))
    return 1


_PEG_LAST_RUN = 0.0


async def run_peg_keeper(db: AsyncSession, batch: int = 0) -> int:
    """§2026-06-25 Adaptive equity peg-keeper (deadband P-controller) — replaces manual whack-a-mole
    re-drains. On reg-a ONLY (env EQUITY_PEG_KEEPER_ENABLED) + DB flag `peg_keeper`, every
    ~interval_sec read each MAINFRAME ticker's ratio (last / fair, fair = ipo×20) across reg-a +
    frame-b + frame-c (:8000 reachable; cloud-ops are NOT → they mean-revert), then write the
    demand_director per-ticker toward fair: outside ±deadband → dir toward fair, strength =
    base+(|dev|-deadband)*gain (capped); inside the deadband → neutral (free wander). Strength backs
    off to `base` at the deadband edge, so it CANNOT over-drive past fair (fixes both the SPLT
    re-inflation AND the NEKO over-drain). DEFERS to an active campaign (never overrides FE tests).
    Δ-IRRELEVANT — writes the director flag only; the sim reads it, money flows via the escrow mover.
    DB-flag gated, default-OFF; env-gated to reg-a (the registry whose director the sim reads)."""
    global _PEG_LAST_RUN
    import json
    if (os.getenv("EQUITY_PEG_KEEPER_ENABLED", "") or "").strip().lower() not in ("1", "true", "yes", "on"):
        return 0
    raw = await get_flag(db, "peg_keeper")
    if not raw:
        return 0
    try:
        cfg = json.loads(raw)
    except (ValueError, TypeError):
        return 0
    if not cfg.get("enabled"):
        return 0
    interval = float(cfg.get("interval_sec", 75))
    now = time.monotonic()
    if now - _PEG_LAST_RUN < interval:
        return 0
    _PEG_LAST_RUN = now
    craw = await get_flag(db, "agora_campaign")          # defer to an active campaign
    if craw:
        try:
            if json.loads(craw).get("active"):
                return 0
        except (ValueError, TypeError):
            pass
    deadband = max(0.02, float(cfg.get("deadband", 0.15)))
    base = max(0.0, float(cfg.get("base", 0.05)))
    gain = max(0.0, float(cfg.get("gain", 0.3)))
    maxs = min(1.0, float(cfg.get("max_strength", 0.6)))
    # mainframe venues (reachable on :8000) + optional OP venues via the host gateway:host-port
    # (flag `op_venues`, e.g. "http://172.17.0.1:27000") — closes the op-coverage gap (§2026-06-25 v1.1).
    venues = ["http://localhost:8000", "http://frame-b-registry:8000", "http://frame-c-registry:8000"]
    _ov = cfg.get("op_venues")
    if isinstance(_ov, list):
        venues += [str(u) for u in _ov if u]
    ratios = {}
    async with httpx.AsyncClient(timeout=6.0) as c:
        for base_url in venues:
            try:
                r = await _peer_request(c, "GET", base_url, "/listings")
                if r.status_code != 200:
                    continue
                for x in (r.json().get("listings") or []):
                    sym = str(x.get("symbol") or "").upper()
                    st = x.get("stats") or {}
                    last = float(st.get("last") or 0)
                    ipo = float(x.get("ipo_price") or 0)
                    if sym and last > 0 and ipo > 0 and x.get("status") == "trading":
                        ratios[sym] = last / (ipo * 20.0)
            except Exception:
                continue
    if not ratios:
        return 0
    director = {}
    for sym, ratio in ratios.items():
        dev = ratio - 1.0
        if abs(dev) <= deadband:
            director[sym] = {"dir": 0, "strength": 0.0}
        else:
            director[sym] = {"dir": (-1.0 if dev > 0 else 1.0),
                             "strength": round(min(maxs, base + (abs(dev) - deadband) * gain), 3)}
    await set_flag(db, "demand_director", json.dumps({"enabled": True, "tickers": director}))
    _dn = sum(1 for v in director.values() if v["dir"] < 0)
    _up = sum(1 for v in director.values() if v["dir"] > 0)
    logger.info(f"[AGORA-peg-keeper] pegged {len(director)} tickers toward fair "
                f"(drain={_dn} pump={_up} neutral={len(director) - _dn - _up})")
    return 1


async def _require_venue_open(db: AsyncSession) -> None:
    if not EXCHANGE_ENABLED:
        raise ExchangeError(503, "AGORA market disabled on this registry (EXCHANGE_ENABLED=false)")
    if (await get_flag(db, "global_halt")) == "true":
        raise ExchangeError(503, "AGORA market globally halted by admin")


# ── participants (D25) ────────────────────────────────────────────────────
async def ensure_participant(db: AsyncSession, agent_did: str) -> ExchangeParticipant:
    """Resolve-or-provision the compliance row for a trading DID.

    Local agents: auto-provision + verify from the local developer record.
    Unknown DIDs (foreign): provision 'pending' — tradable only once the §9
    Passport pipeline verifies a DevCard (EXCHANGE_PASSPORT_ENABLED phase)."""
    part = (
        await db.execute(select(ExchangeParticipant).where(ExchangeParticipant.agent_did == agent_did))
    ).scalar_one_or_none()

    agent = (await db.execute(select(Agent).where(Agent.did == agent_did))).scalar_one_or_none()
    if agent is not None:
        dev = (
            await db.execute(select(Developer).where(Developer.id == agent.creator_developer_id))
        ).scalar_one_or_none()
        blocked = agent.status != "active"
        if part is None:
            part = ExchangeParticipant(
                agent_did=agent_did,
                home_registry="local",
                verification_source="local",
                owner_dev_ref=str(agent.creator_developer_id),
                owner_dev_name=getattr(dev, "name", None),
                owner_dev_contact=getattr(dev, "email", None),
                compliance_status="blocked" if blocked else "verified",
                verified_at=None if blocked else datetime.now(timezone.utc),
            )
            db.add(part)
        else:
            part.compliance_status = "blocked" if blocked else "verified"
            if not blocked and part.verified_at is None:
                part.verified_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(part)
    elif part is None:
        part = ExchangeParticipant(agent_did=agent_did, home_registry="unknown", compliance_status="pending")
        db.add(part)
        await db.commit()
        await db.refresh(part)

    if REQUIRE_COMPLIANT_PARTICIPANT and part.compliance_status != "verified":
        raise ExchangeError(
            403,
            f"participant {part.compliance_status}: AGORA requires a verified owner identity "
            f"(local agents verify automatically; federated agents need the AGORA Passport / DevCard)",
        )
    return part


# ── listings ──────────────────────────────────────────────────────────────
TICKER_RE = r"^[A-Z0-9]{2,6}$"



def _treasury_card_data(org_name: str, symbol: str, treasury_did: str) -> dict:
    """The AGORA treasury's card, CONFORMANT to the canonical A2A AgentCard schema.

    🔴 THE SAME DEFECT §VENUEGW FIXED FOR THE DEPOSIT GATEWAY ON 2026-08-26, IN THE SAME FILE
    FAMILY, LEFT STANDING IN ITS SIBLING. This was a five-field stub (name/description/did/
    agora_treasury/version): no protocolVersion, no humanReadableId, no provider, no endpoint.
    A peer running `FEDERATION_INGEST_FAIL_CLOSED=true` — both live frames do — validates every
    inbound card and QUARANTINES what does not conform, so every AGORA IPO has been minting a card
    that can never reach a peer, silently, since the flag went on. Measured 2026-09-09 on EU: the
    one treasury card there is the only native card failing validation for a reason other than an
    empty `provider.url`.

    §FANOUTFIX's rule, one level up: when a defect is fixed, grep every OTHER site with the same
    SHAPE. `services/org_treasury.py` was the third instance and is fixed in the same pass.
    """
    from ..core import public_url as _pu
    base = (_pu.public_base_url_static() or "").rstrip("/")
    # ⚠ a cloud-op's baked BASE_URL default is http://localhost:8000 — TRUTHY, so a plain
    # falsy-guard publishes someone's loopback. public_base_url_static already refuses it; if it
    # yields nothing, fall back to something stable rather than to a lie.
    slug = treasury_did.rsplit(":", 1)[-1]
    url = f"{base}/api/v1/agora" if base else f"https://theprotocol.cloud/agora/{slug}"
    return {
        "protocolVersion": "0.3.0",
        "humanReadableId": f"agora/{slug}",
        "agentVersion": "1.0.0",
        "name": f"{org_name} Treasury (${symbol})",
        "description": (
            f"AGORA treasury agent for ${symbol}, receiving launch proceeds and the org fee split, "
            f"and paying distributions."
        ),
        "url": url,
        "provider": {"name": org_name, "url": "https://theprotocol.cloud"},
        "capabilities": {"streaming": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{
            "id": "agora-treasury",
            "name": "AGORA treasury",
            "description": f"Holds ${symbol} launch proceeds and pays distributions.",
        }],
        "authSchemes": [{"scheme": "none"}],
        "did": treasury_did,
        "agora_treasury": True,
        "version": "1.0",
    }


async def create_listing(
    db: AsyncSession,
    developer: Developer,
    organization_id: str,
    symbol: str,
    total_shares: int,
    ipo_float: int,
    ipo_price: Decimal,
    funding_agent_did: str,
    display_name: Optional[str] = None,
) -> ExchangeListing:
    """Org OWNER lists their org: creates the listing (unapproved) + the org
    treasury agent (real Agent row, creds generated-and-discarded) and attempts
    the listing-fee legs (replay-safe; the worker finishes them if interrupted)."""
    import re

    org = await OrganizationService.get_organization(db, organization_id)
    if not org:
        raise ExchangeError(404, "organization not found")
    if org.owner_id != developer.id:
        raise ExchangeError(403, "only the organization OWNER can list it on AGORA")
    if not re.match(TICKER_RE, symbol or ""):
        raise ExchangeError(422, "symbol must match ^[A-Z0-9]{2,6}$")
    if total_shares <= 0 or ipo_float < 0 or ipo_float > total_shares:
        raise ExchangeError(422, "require 0 <= ipo_float <= total_shares and total_shares > 0")
    if ipo_price <= ZERO:
        raise ExchangeError(422, "ipo_price must be > 0")

    existing = (
        await db.execute(
            select(ExchangeListing).where(
                or_(
                    ExchangeListing.organization_id == organization_id,
                    ExchangeListing.symbol == symbol,
                )
            )
        )
    ).scalars().first()
    if existing:
        raise ExchangeError(409, "organization already listed or symbol taken")

    # The listing-fee funding agent must belong to the caller.
    fund_agent = (
        await db.execute(select(Agent).where(Agent.did == funding_agent_did))
    ).scalar_one_or_none()
    if not fund_agent or fund_agent.creator_developer_id != developer.id:
        raise ExchangeError(403, "funding_agent_did must be one of your own agents")

    # Org treasury agent: un-loginable (secret discarded), owned by the org owner.
    from agentvault_registry.security import hash_password

    treasury_did = f"did:theprotocol:org-{symbol.lower()}-treasury"
    treasury = Agent(
        did=treasury_did,
        client_id=f"agora-{symbol.lower()}-treasury-{secrets.token_hex(4)}",
        hashed_client_secret=hash_password(f"tp_secret_{secrets.token_hex(32)}"),
        creator_developer_id=developer.id,
        status="active",
    )
    db.add(treasury)
    await db.flush()
    db.add(
        AgentCard(
            id=uuid.uuid4(),
            developer_id=developer.id,
            agent_did=treasury_did,
            card_data=_treasury_card_data(org.name, symbol, treasury_did),
            name=f"{org.name} Treasury (${symbol})",
            description=f"AGORA treasury agent for ${symbol}",
            is_active=True,
        )
    )

    listing = ExchangeListing(
        organization_id=organization_id,
        symbol=symbol,
        display_name=display_name or org.name,
        total_shares=total_shares,
        treasury_agent_did=treasury_did,
        currency=os.getenv("FRAME_CURRENCY", "AVT"),
        ipo_price=ipo_price,
        ipo_float=ipo_float,
        created_by_dev=developer.id,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)

    # Listing fee legs (1000 → escrow → fee_collector). Replay-safe; the worker
    # retries via settle_listing_fees if we crash between legs.
    try:
        await _settle_listing_fee(db, listing, funding_agent_did)
    except ExchangeError as e:
        logger.warning(f"[AGORA] listing fee for ${symbol} pending ({e.detail}) — worker will retry")

    _emit(
        "ExchangeListingCreated",
        listing.id,
        {
            "symbol": symbol,
            "organization_id": organization_id,
            "total_shares": str(total_shares),
            "ipo_float": str(ipo_float),
            "ipo_price": str(ipo_price),
            "currency": listing.currency,
            "treasury_agent_did": treasury_did,
        },
        key=f"exchange-listing:{listing.id}",
    )
    return listing


async def _settle_listing_fee(db: AsyncSession, listing: ExchangeListing, funding_agent_did: Optional[str] = None) -> None:
    """Two replay-safe legs. parked=True after leg1 so I-X3 stays computable."""
    if listing.listing_fee_paid or LISTING_FEE <= ZERO:
        if not listing.listing_fee_paid:
            listing.listing_fee_paid = True
            await db.commit()
        return
    payer = funding_agent_did
    if payer is None:
        raise ExchangeError(409, "listing fee unpaid and no funding agent recorded — re-create not needed; admin may settle manually")
    await mover.move(payer, EXCHANGE_ESCROW_SENTINEL, LISTING_FEE, "listing_fee", f"lst-{listing.id}:fee")
    listing.listing_fee_parked = True
    await db.commit()
    await mover.move(EXCHANGE_ESCROW_SENTINEL, FEE_COLLECTOR_SENTINEL, LISTING_FEE, "listing_fee_settle", f"lst-{listing.id}:fees")
    listing.listing_fee_parked = False
    listing.listing_fee_paid = True
    await db.commit()


async def approve_listing(db: AsyncSession, listing_id: str) -> ExchangeListing:
    """Admin approval (D15): grants the retained allocation (total−float) to the
    org treasury agent's position and opens the market (status → trading)."""
    listing = await _get_listing(db, listing_id)
    if listing.approved:
        return listing
    await _listing_lock(db, listing.id)
    retained = listing.total_shares - listing.ipo_float
    if retained > 0:
        pos = await _get_or_create_position(db, listing.id, listing.treasury_agent_did)
        pos.qty += retained
    # The treasury agent is a participant too (it holds shares + receives fees).
    listing.approved = True
    listing.status = "trading"
    await db.commit()
    # Outside the lock: provision the treasury participant row (local-verified).
    try:
        await ensure_participant(db, listing.treasury_agent_did)
    except ExchangeError as e_:
        # enforcement errors don't apply to the treasury grant itself — but the treasury participant row NOT being
        # provisioned is the reason a later trade on this listing fails; say it here, where the cause is (§S4 pass 4)
        logger.warning("[EXCHANGE] treasury participant for %s not provisioned at approval: %s", listing.symbol, getattr(e_, "detail", str(e_))[:160])
    # §VENUEGW 2026-08-26 — a venue that can be traded should already have its deposit
    # terminus. The gateway used to be created lazily on the FIRST inbound passport
    # order, which meant the first foreign buyer on every new venue paid for the cold
    # start: its home could not resolve a gateway card that did not exist yet, and (once
    # the card existed) could not pay a DID its spend policy had never heard of. Creating
    # it here lets the ordinary federation card sync carry it before anyone needs it.
    # Idempotent, and a no-op on a mainframe that already has one.
    try:
        from agentvault_registry.services import exchange_passport as _pp
        await _pp.ensure_gateway(db)
    except Exception as _gwe:  # noqa: BLE001 — never block an approval on the gateway
        logger.warning("[AGORA] gateway not provisioned at approval for %s: %s", listing.symbol, _gwe)
    _emit(
        "ExchangeListingApproved",
        listing.id,
        {"symbol": listing.symbol, "retained_to_treasury": str(retained)},
        key=f"exchange-approve:{listing.id}",
    )
    return listing


async def set_listing_halt(db: AsyncSession, listing_id: str, halted: bool) -> ExchangeListing:
    listing = await _get_listing(db, listing_id)
    if listing.status == "delisted":
        raise ExchangeError(409, "listing is delisted")
    listing.status = "halted" if halted else "trading"
    await db.commit()
    _emit(
        "ExchangeListingHalted",
        listing.id,
        {"symbol": listing.symbol, "halted": str(halted)},
        key=f"exchange-halt:{listing.id}:{listing.status}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
    )
    return listing


async def delist(db: AsyncSession, listing_id: str) -> Dict[str, Any]:
    """Halt + cancel-all (shares unlocked; buy refunds drain via the worker)."""
    listing = await _get_listing(db, listing_id)
    await _listing_lock(db, listing.id)
    open_orders = (
        await db.execute(
            select(ExchangeOrder).where(
                ExchangeOrder.listing_id == listing.id,
                ExchangeOrder.status.in_(("open", "partial", "funding")),
            )
        )
    ).scalars().all()
    cancelled = 0
    for o in open_orders:
        if o.side == "sell":
            pos = await _get_or_create_position(db, listing.id, o.agent_did)
            pos.locked_qty = max(0, pos.locked_qty - o.remaining)
        o.status = "cancelled"
        o.reject_reason = "delisted"
        cancelled += 1
    listing.status = "delisted"
    await db.commit()
    return {"listing_id": listing.id, "symbol": listing.symbol, "orders_cancelled": cancelled}


async def get_org_treasury(db: AsyncSession, org_id: str, developer: "Developer") -> Dict[str, Any]:
    """§V0113 Org Consolidated Treasury (read-only, Δ-irrelevant). Holding-company
    roll-up: every listing of `org_id` is a subsidiary with its own keyless
    treasury_agent_did (IPO proceeds + org fee split land there). Balance is read
    LIVE from the TEG (mover.agent_balance); `raised` = ipo_sold × ipo_price. A
    single unreachable treasury surfaces balance=null rather than failing the roll-up.
    Auth: any org member may VIEW (mirrors declare_dividend's member-permission gate)."""
    if not await OrganizationService.check_member_permission(db, org_id, developer.id, "member"):
        raise ExchangeError(403, "org membership required")
    rows = (
        await db.execute(
            select(ExchangeListing)
            .where(ExchangeListing.organization_id == org_id)
            .order_by(ExchangeListing.symbol)
        )
    ).scalars().all()
    listing_ids = [lst.id for lst in rows]
    fees_by_listing: Dict[str, Decimal] = {}
    divs_by_listing: Dict[str, Decimal] = {}
    if listing_ids:
        fee_rows = (await db.execute(
            select(ExchangeTrade.listing_id, func.coalesce(func.sum(ExchangeTrade.fee_org), ZERO))
            .where(ExchangeTrade.listing_id.in_(listing_ids))
            .group_by(ExchangeTrade.listing_id)
        )).all()
        fees_by_listing = {lid: amt for lid, amt in fee_rows}
        div_rows = (await db.execute(
            select(ExchangeDividend.listing_id, func.coalesce(func.sum(ExchangeDividend.total_amount), ZERO))
            .where(ExchangeDividend.listing_id.in_(listing_ids), ExchangeDividend.status != "failed")
            .group_by(ExchangeDividend.listing_id)
        )).all()
        divs_by_listing = {lid: amt for lid, amt in div_rows}
    mover = ExchangeMover()
    listings: List[Dict[str, Any]] = []
    tot_bal = ZERO
    tot_raised = ZERO
    tot_fees = ZERO
    tot_divs = ZERO
    currency: Optional[str] = None
    for lst in rows:
        try:
            bal: Optional[Decimal] = await mover.agent_balance(lst.treasury_agent_did)
        except MoverError:
            bal = None
        raised = q18(lst.ipo_price * Decimal(lst.ipo_sold))
        fees = q18(fees_by_listing.get(lst.id, ZERO))
        divs = q18(divs_by_listing.get(lst.id, ZERO))
        currency = currency or lst.currency
        if bal is not None:
            tot_bal += bal
        tot_raised += raised
        tot_fees += fees
        tot_divs += divs
        listings.append({
            "symbol": lst.symbol,
            "treasury_agent_did": lst.treasury_agent_did,
            "currency": lst.currency,
            "status": lst.status,
            "balance": str(bal) if bal is not None else None,
            "available": str(bal) if bal is not None else None,
            "raised": str(raised),
            "fees_earned": str(fees),
            "dividends_paid": str(divs),
            "ipo_sold": lst.ipo_sold,
            "ipo_float": lst.ipo_float,
            "total_shares": lst.total_shares,
            "ipo_price": str(lst.ipo_price),
        })
    return {
        "organization_id": org_id,
        "currency": currency,
        "listing_count": len(listings),
        "totals": {"balance": str(tot_bal), "raised": str(tot_raised),
                   "fees_earned": str(tot_fees), "dividends_paid": str(tot_divs)},
        "listings": listings,
    }


async def treasury_move(
    db: AsyncSession,
    org_id: str,
    symbol: str,
    dest_did: str,
    amount: Decimal,
    action: str,
    developer: "Developer",
    *,
    reserve_floor: Decimal = ZERO,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """§V0113 Treasury spend CORE — the single Δ-safe path funds leave an org treasury.
    ORG-ADMIN gated (mirrors declare_dividend). The treasury_agent_did is KEYLESS by
    design (client_secret discarded at creation → no JWT → it cannot call /teg/transfer),
    so funds move via the admin exref mover, which is escrow-only. We therefore route
    treasury → @exchange_escrow → dest in TWO Δ-neutral legs (escrow nets exactly 0) — the
    identical hub `declare_dividend`'s pot funding uses. Reasons → ES kinds
    `exchange_treasury_{action}_out` (treasury→escrow) + `exchange_treasury_{action}`
    (escrow→dest), both transit-net under the Part-C labeling. Reserve-floor guard
    (pre-check) never drains the treasury below `reserve_floor`. Leg idempotency keys derive
    from the HTTP `Idempotency-Key` when supplied, so a retry replays each COMPLETED leg as a
    TEG no-op (never double-debits, never strands); absent it a random base is used (single-
    shot). Δ=0 (move, never mint). Callers: transfer / sweep (dividend + buyback ride their
    own escrow-valid paths)."""
    if not await OrganizationService.check_member_permission(db, org_id, developer.id, "admin"):
        raise ExchangeError(403, "org admin role required")
    if amount <= ZERO:
        raise ExchangeError(422, "amount must be > 0")
    listing = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.organization_id == org_id,
                ExchangeListing.symbol == symbol.upper(),
            )
        )
    ).scalar_one_or_none()
    if not listing:
        raise ExchangeError(404, "listing not found for this organization")
    amt = q18(amount)
    mover = ExchangeMover()
    bal = await mover.agent_balance(listing.treasury_agent_did)
    if bal - amt < reserve_floor:
        raise ExchangeError(
            409,
            f"insufficient treasury: balance {bal}, requested {amt}, reserve floor {reserve_floor}",
        )
    # Keyless treasury → the only server-authorized mover is the escrow-only exref mover,
    # so hop through @exchange_escrow in two Δ-neutral legs (escrow nets 0). Deterministic
    # base (HTTP Idempotency-Key when present) makes each TEG leg replay-safe on retry: a
    # re-run finds the COMPLETED :out leg (no re-debit) and only completes the :in leg.
    # D6-777: the base is the caller's (caller_key): another admin's request under the same key value never runs into
    # these legs, and no leg written before (treasury-<id>-<action>-<key>) shares this form.
    from agentvault_registry.services.idempotency.cache import caller_key, developer_caller
    tail = caller_key(developer_caller(developer.id), idempotency_key) if idempotency_key else "r" + secrets.token_hex(8)
    base = f"treasury.{listing.id}.{action}.{tail}"
    await mover.move(
        listing.treasury_agent_did, EXCHANGE_ESCROW_SENTINEL, amt, f"treasury_{action}_out", f"{base}:out"
    )
    res = await mover.move(
        EXCHANGE_ESCROW_SENTINEL, dest_did, amt, f"treasury_{action}", f"{base}:in"
    )
    return {
        "status": "ok",
        "symbol": listing.symbol,
        "action": action,
        "dest_did": dest_did,
        "amount": str(amt),
        "transaction_id": res.get("transaction_id"),
    }


async def treasury_buyback(
    db: AsyncSession,
    org_id: str,
    symbol: str,
    qty: int,
    limit_price: Decimal,
    developer: "Developer",
) -> Dict[str, Any]:
    """§V0113 Treasury buyback — the org's own (keyless) treasury bids on its own
    listing. ORG-ADMIN gated (mirrors treasury_move). The treasury_agent_did is
    keyless by design, so we place the BUY on its behalf via the normal `place_order`
    path: that runs the order_deposit escrow leg (treasury → escrow) and CLOB match,
    so spend rides the existing exref mover → Δ=0 (move, never mint)."""
    if not await OrganizationService.check_member_permission(db, org_id, developer.id, "admin"):
        raise ExchangeError(403, "org admin role required")
    listing = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.organization_id == org_id,
                ExchangeListing.symbol == symbol.upper(),
            )
        )
    ).scalar_one_or_none()
    if not listing:
        raise ExchangeError(404, "listing not found for this organization")
    placed = await place_order(
        db,
        agent_did=listing.treasury_agent_did,
        listing_ref=listing.id,
        side="buy",
        order_type="limit",
        qty=qty,
        price=q18(limit_price),
    )
    o = placed.order
    return {
        "status": "ok",
        "symbol": listing.symbol,
        "action": "buyback",
        "order_id": o.id,
        "order_status": o.status,
        "qty": o.qty,
        "remaining": o.remaining,
        "limit_price": str(limit_price),
        "fills": [
            {"trade_id": t.id, "price": str(t.price), "qty": t.qty, "notional": str(t.notional)}
            for t in placed.fills
        ],
    }


async def treasury_sweep(
    db: AsyncSession,
    org_id: str,
    from_symbol: str,
    to_symbol: str,
    amount: Decimal,
    developer: "Developer",
    *,
    reserve_floor: Decimal = ZERO,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """§V0113 Treasury sweep — move funds between two listings of the SAME org
    (from_symbol's treasury → to_symbol's treasury). Resolves the destination
    treasury_agent_did, then delegates to treasury_move (which gates org-admin,
    reserve-floor guards, and rides the exref mover via the escrow hub → Δ=0)."""
    to_listing = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.organization_id == org_id,
                ExchangeListing.symbol == to_symbol.upper(),
            )
        )
    ).scalar_one_or_none()
    if not to_listing:
        raise ExchangeError(404, "destination listing not found for this organization")
    return await treasury_move(
        db, org_id, from_symbol, to_listing.treasury_agent_did, amount, "sweep",
        developer, reserve_floor=reserve_floor, idempotency_key=idempotency_key,
    )


async def treasury_refloat(
    db: AsyncSession,
    org_id: str,
    symbol: str,
    qty: int,
    developer: "Developer",
    *,
    offer_price: Optional[Decimal] = None,
    min_retained: int = 0,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """§P1.1 Treasury re-float — release `qty` retained shares from the org treasury
    position back into the buyable IPO float (a secondary offering). ORG-ADMIN gated
    (mirrors treasury_buyback/move). PURE SHARE-LEDGER op — no TEG leg: bumps
    `ipo_float` and debits the treasury OrgSharePosition.qty under _listing_lock.
    I-X1 stays balanced (expected (total-ipo_float)+ipo_sold drops by qty AND the
    treasury position drops by qty); the freed shares re-open IPO headroom. Re-prices
    the IPO to `offer_price` (default current market last) so a follow-on doesn't
    undercut the live price. Emits no LedgerBalanceChanged → Δ-irrelevant to supply."""
    if not await OrganizationService.check_member_permission(db, org_id, developer.id, "admin"):
        raise ExchangeError(403, "org admin role required")
    if qty <= 0:
        raise ExchangeError(422, "qty must be > 0")
    if min_retained < 0:
        raise ExchangeError(422, "min_retained must be >= 0")
    listing = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.organization_id == org_id,
                ExchangeListing.symbol == symbol.upper(),
            )
        )
    ).scalar_one_or_none()
    if not listing:
        raise ExchangeError(404, "listing not found for this organization")
    if not listing.approved or listing.status not in ("trading", "halted"):
        raise ExchangeError(409, "listing not approved / not open")
    if listing.ipo_float + qty > listing.total_shares:
        raise ExchangeError(
            409,
            f"re-release would push the launch allocation to {listing.ipo_float + qty} > total {listing.total_shares}; "
            f"max re-release = {listing.total_shares - listing.ipo_float} (use treasury-sell for points the treasury already bought)",
        )
    new_price = q18(offer_price) if offer_price is not None else None
    if new_price is None:
        last = await _last_price(db, listing.id)
        new_price = q18(last) if last and last > ZERO else listing.ipo_price
    if new_price <= ZERO:
        raise ExchangeError(422, "offer price must be > 0")

    await _listing_lock(db, listing.id)
    await db.refresh(listing)
    if listing.ipo_float + qty > listing.total_shares:
        await db.rollback()
        raise ExchangeError(409, "re-release would exceed total points (raced)")
    pos = await _get_or_create_position(db, listing.id, listing.treasury_agent_did)
    free = pos.qty - pos.locked_qty
    if free < qty:
        await db.rollback()
        raise ExchangeError(409, f"treasury free points {free} < requested {qty}")
    if pos.qty - qty < min_retained:
        await db.rollback()
        raise ExchangeError(409, f"would breach min_retained {min_retained} (treasury {pos.qty}, re-release {qty})")

    pos.qty -= qty
    listing.ipo_float += qty
    listing.ipo_price = new_price
    await db.commit()

    from agentvault_registry.services.idempotency.cache import caller_key, developer_caller
    _emit(
        "ExchangeShareRefloated",
        listing.id,
        {
            "symbol": listing.symbol,
            "qty": str(qty),
            "new_ipo_float": str(listing.ipo_float),
            "offer_price": str(new_price),
            "treasury_remaining": str(pos.qty),
        },
        key=f"exchange-refloat.{listing.id}." + (  # D6-777: the caller's own event key (caller_key)
            caller_key(developer_caller(developer.id), idempotency_key) if idempotency_key else secrets.token_hex(8)),
    )
    return {
        "status": "ok",
        "symbol": listing.symbol,
        "action": "refloat",
        "qty": qty,
        "ipo_float": listing.ipo_float,
        "ipo_sold": listing.ipo_sold,
        "buyable_now": listing.ipo_float - listing.ipo_sold,
        "offer_price": str(new_price),
        "treasury_remaining": pos.qty,
    }


async def treasury_sell(
    db: AsyncSession,
    org_id: str,
    symbol: str,
    qty: int,
    developer: "Developer",
    *,
    order_type: str = "limit",
    limit_price: Optional[Decimal] = None,
    min_retained: int = 0,
) -> Dict[str, Any]:
    """§P1.2 Treasury market-sell — the org's keyless treasury places a SELL on its
    own listing to distribute retained/bought-back shares at market (mirror of
    treasury_buyback's BUY). ORG-ADMIN gated. Sells from the treasury POSITION (not
    ipo_float — that's re-float). place_order's SELL path locks free treasury shares +
    CLOB-matches; proceeds settle to the treasury balance via the exref escrow path →
    Δ=0 (move, never mint)."""
    if not await OrganizationService.check_member_permission(db, org_id, developer.id, "admin"):
        raise ExchangeError(403, "org admin role required")
    if qty <= 0:
        raise ExchangeError(422, "qty must be > 0")
    if order_type not in ("limit", "market"):
        raise ExchangeError(422, "order_type must be limit|market")
    if order_type == "limit" and (limit_price is None or limit_price <= ZERO):
        raise ExchangeError(422, "limit order needs limit_price > 0")
    listing = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.organization_id == org_id,
                ExchangeListing.symbol == symbol.upper(),
            )
        )
    ).scalar_one_or_none()
    if not listing:
        raise ExchangeError(404, "listing not found for this organization")
    pos = await _get_or_create_position(db, listing.id, listing.treasury_agent_did)
    if pos.qty - pos.locked_qty < qty:
        raise ExchangeError(409, f"treasury free points {pos.qty - pos.locked_qty} < {qty}")
    if pos.qty - qty < min_retained:
        raise ExchangeError(409, f"would breach min_retained {min_retained} (treasury {pos.qty})")
    placed = await place_order(
        db,
        agent_did=listing.treasury_agent_did,
        listing_ref=listing.id,
        side="sell",
        order_type=order_type,
        qty=qty,
        price=q18(limit_price) if limit_price is not None else None,
    )
    o = placed.order
    return {
        "status": "ok",
        "symbol": listing.symbol,
        "action": "sell",
        "order_id": o.id,
        "order_status": o.status,
        "qty": o.qty,
        "remaining": o.remaining,
        "fills": [{"trade_id": t.id, "price": str(t.price), "qty": t.qty} for t in placed.fills],
    }


async def set_mm_config(
    db: AsyncSession,
    org_id: str,
    symbol: str,
    developer: "Developer",
    *,
    enabled: Optional[bool] = None,
    spread_bps: Optional[int] = None,
    quote_qty: Optional[int] = None,
    reserve_shares: Optional[int] = None,
    cash_floor: Optional[Decimal] = None,
    ref_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """§P2.1 Upsert the treasury market-maker config for an org's listing (org-admin).
    The leader-elected treasury_market_maker worker reads enabled rows each cycle."""
    if not await OrganizationService.check_member_permission(db, org_id, developer.id, "admin"):
        raise ExchangeError(403, "org admin role required")
    listing = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.organization_id == org_id,
                ExchangeListing.symbol == symbol.upper(),
            )
        )
    ).scalar_one_or_none()
    if not listing:
        raise ExchangeError(404, "listing not found for this organization")
    cfg = (
        await db.execute(select(TreasuryMMConfig).where(TreasuryMMConfig.listing_id == listing.id))
    ).scalar_one_or_none()
    if cfg is None:
        cfg = TreasuryMMConfig(listing_id=listing.id)
        db.add(cfg)
    if enabled is not None:
        cfg.enabled = bool(enabled)
    if spread_bps is not None:
        cfg.spread_bps = max(1, int(spread_bps))
    if quote_qty is not None:
        cfg.quote_qty = max(1, int(quote_qty))
    if reserve_shares is not None:
        cfg.reserve_shares = max(0, int(reserve_shares))
    if cash_floor is not None:
        cfg.cash_floor = q18(cash_floor) if cash_floor >= ZERO else ZERO
    if ref_mode is not None and ref_mode in ("last", "fair"):
        cfg.ref_mode = ref_mode
    await db.commit()
    return await get_mm_config(db, org_id, symbol)


async def get_mm_config(db: AsyncSession, org_id: str, symbol: str) -> Dict[str, Any]:
    listing = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.organization_id == org_id,
                ExchangeListing.symbol == symbol.upper(),
            )
        )
    ).scalar_one_or_none()
    if not listing:
        raise ExchangeError(404, "listing not found for this organization")
    cfg = (
        await db.execute(select(TreasuryMMConfig).where(TreasuryMMConfig.listing_id == listing.id))
    ).scalar_one_or_none()
    if cfg is None:
        return {"symbol": listing.symbol, "configured": False, "enabled": False}
    return {
        "symbol": listing.symbol, "configured": True, "enabled": cfg.enabled,
        "spread_bps": cfg.spread_bps, "quote_qty": cfg.quote_qty,
        "reserve_shares": cfg.reserve_shares, "cash_floor": str(cfg.cash_floor),
        "ref_mode": cfg.ref_mode,
    }


# ── §2026-06-22 P2.2 — designated external MM + maker rebate ──────────────
async def set_circuit_breaker(db: AsyncSession, listing_id: str, cb_pct: int) -> ExchangeListing:
    """§#84 admin: set a listing's circuit-breaker threshold (bps; 0 disables). Δ-IRRELEVANT
    (config/state only — no money or share movement). cb_pct>0 arms volatility auto-halt
    (_circuit_breaker_react halts the listing when `last` moves > cb_pct/1e4 from a rolling
    reference within EXCHANGE_CB_WINDOW_SEC; resume_expired_circuit_breakers auto-resumes after
    cooldown). cb_pct=0 disables AND releases a standing breaker-set halt (cb_halted_until set) —
    but never a manual halt."""
    cb_pct = int(cb_pct)
    if cb_pct < 0 or cb_pct > 10000:
        raise ExchangeError(422, "cb_pct must be between 0 and 10000 bps")
    listing = await _get_listing(db, listing_id)
    await _listing_lock(db, listing.id)
    await db.refresh(listing)
    listing.cb_pct = cb_pct
    if cb_pct == 0:
        # disabling: clear the rolling reference; if the BREAKER (not an admin) currently holds
        # the listing halted, release it back to trading.
        was_breaker_halt = listing.cb_halted_until is not None
        listing.cb_ref_price = None
        listing.cb_ref_at = None
        listing.cb_halted_until = None
        if was_breaker_halt and listing.status == "halted":
            listing.status = "trading"
    await db.commit()
    await db.refresh(listing)
    _emit("ExchangeCircuitBreakerSet", listing.id,
          {"symbol": listing.symbol, "cb_pct": cb_pct, "status": listing.status},
          key=f"exchange-cb-set:{listing.id}:{cb_pct}")
    return listing


async def set_price_band(db: AsyncSession, listing_id: str, band_pct: int) -> ExchangeListing:
    """§PRICEBAND admin: set a listing's price band. Δ-IRRELEVANT (config only — no money
    or share movement), mirroring `set_circuit_breaker` above.

    The band is the ±% around the last trade that `place_order` and the passport relay
    will accept a limit price inside (`_band_bounds`, and the two call sites at
    `exchange_service.py:2450` / `exchange_passport.py:584`). It is a fat-finger and
    manipulation guard, and until now it was a column with a default of 25 and NO way to
    change it: `cb_pct` had an admin route, `band_pct` did not, so the guard that actually
    rejects orders was the one an operator could not tune.

    🔴 **THE UNIT IS PERCENT, AND THE NEIGHBOURING ROUTE'S IS NOT.**
    `cb_pct` is BASIS POINTS (`move > cb_pct / 10000`, so 3500 = 35%). `band_pct` is
    PERCENT (`spread = last * band_pct / 100`, so 25 = 25%). Two adjacent admin routes,
    two fields both spelled `*_pct`, two different units. An operator who learned the
    circuit-breaker route first would very reasonably send 2500 meaning 25% and get a
    ±2500% band — i.e. silently switch the guard off on a money rail.

    That is why the ceiling here is 500 and not 10000: it makes the bps mistake a LOUD
    422 instead of a quiet disable. 500% is already ±5x the last price, unconstrained for
    any real order, and `MAX_ORDER_NOTIONAL` still applies above it.

    ⚠ And 0 is REFUSED rather than treated as "off". On the circuit-breaker route 0 means
    DISABLED; here it would mean maximally strict — only a price exactly equal to the last
    trade would be accepted, freezing the book. The same integer meaning opposite things on
    two neighbouring routes is not a default worth having, so there is no disable value:
    widen the band instead.
    """
    band_pct = int(band_pct)
    if band_pct < 1 or band_pct > 500:
        raise ExchangeError(
            422,
            "band_pct must be between 1 and 500 PERCENT (not bps — cb_pct is bps, this is not)",
        )
    listing = await _get_listing(db, listing_id)
    await _listing_lock(db, listing.id)
    await db.refresh(listing)
    previous = int(listing.band_pct)
    listing.band_pct = band_pct
    await db.commit()
    await db.refresh(listing)
    # ⚠ TIME-STAMPED KEY, unlike `set_circuit_breaker`'s `…:{cb_pct}`. A key built from the
    # VALUE dedups in the EventStore, so 25 -> 50 -> 25 records only two events and the
    # return to 25 vanishes from the trail. The halt emitter in this same file already
    # stamps the time for exactly this reason; a config change is only auditable if every
    # change is in the log.
    _emit("ExchangePriceBandSet", listing.id,
          {"symbol": listing.symbol, "band_pct": band_pct,
           "previous_band_pct": previous, "status": listing.status},
          key=f"exchange-band-set:{listing.id}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}")
    return listing


async def set_maker_rebate(
    db: AsyncSession,
    org_id: str,
    symbol: str,
    developer: "Developer",
    *,
    maker_rebate_bps: int,
    rebate_requires_registration: Optional[bool] = None,
) -> Dict[str, Any]:
    """Set the maker-taker rebate on an org's listing (ORG-ADMIN). The rebate is paid
    to the resting (maker) order out of the PROTOCOL fee slice at settlement (Δ=0).

    CONFIG BOUND (B-2): reject a rebate that would eat into the org's share, i.e. require
    org_split_bps/1e4 + maker_rebate_bps/1e4 ≤ 1.0. Equivalently the rebate (per notional)
    must fit inside the protocol slice of the fee: maker_rebate_bps ≤ fee_bps·(1 −
    org_split_bps/1e4) = the bps the protocol keeps. Enforced at write time so the carve in
    _match can never drive fee_proto negative."""
    if not await OrganizationService.check_member_permission(db, org_id, developer.id, "admin"):
        raise ExchangeError(403, "org admin role required")
    listing = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.organization_id == org_id,
                ExchangeListing.symbol == symbol.upper(),
            )
        )
    ).scalar_one_or_none()
    if not listing:
        raise ExchangeError(404, "listing not found for this organization")
    rebate_bps = int(maker_rebate_bps)
    if rebate_bps < 0:
        raise ExchangeError(422, "maker_rebate_bps must be ≥ 0")
    # Config bound: rebate can't eat the org split (so fee_proto ≥ 0 always at match).
    # proto slice (in bps of notional) = fee_bps − fee_bps·org_split_bps/1e4.
    proto_bps_of_notional = Decimal(listing.fee_bps) - q18(
        Decimal(listing.fee_bps) * Decimal(listing.fee_org_split_bps) / Decimal(10000)
    )
    if Decimal(rebate_bps) > proto_bps_of_notional:
        raise ExchangeError(
            422,
            f"maker_rebate_bps {rebate_bps} exceeds the protocol fee slice "
            f"({proto_bps_of_notional} bps of notional = fee_bps − org split); "
            f"rebate cannot eat the org's share",
        )
    listing.maker_rebate_bps = rebate_bps
    if rebate_requires_registration is not None:
        listing.rebate_requires_registration = bool(rebate_requires_registration)
    await db.commit()
    await db.refresh(listing)
    return {
        "symbol": listing.symbol,
        "maker_rebate_bps": listing.maker_rebate_bps,
        "rebate_requires_registration": listing.rebate_requires_registration,
        "fee_bps": listing.fee_bps,
        "fee_org_split_bps": listing.fee_org_split_bps,
        "rebate_enabled_globally": MAKER_REBATE_ENABLED,
        "note": (
            "rebate carved from the protocol fee slice at settlement; "
            + ("set EXCHANGE_MAKER_REBATE_ENABLED to activate" if not MAKER_REBATE_ENABLED else "active")
        ),
    }


async def grant_market_maker(
    db: AsyncSession,
    org_id: str,
    symbol: str,
    developer: "Developer",
    *,
    agent_did: str,
    status: str = "active",
    min_uptime_pct: Optional[int] = None,
    max_spread_bps: Optional[int] = None,
) -> Dict[str, Any]:
    """Grant/update/revoke a designated external market-maker seat on an org's listing
    (ORG-ADMIN). Upserts ExchangeMarketMaker by (listing, agent_did) and reflects the
    seat on the participant's market_maker flag. status ∈ active|suspended|revoked;
    only 'active' earns the rebate when rebate_requires_registration is true."""
    if not await OrganizationService.check_member_permission(db, org_id, developer.id, "admin"):
        raise ExchangeError(403, "org admin role required")
    if status not in ("active", "suspended", "revoked"):
        raise ExchangeError(422, "status must be active|suspended|revoked")
    did = (agent_did or "").strip()
    if not did:
        raise ExchangeError(422, "agent_did required")
    listing = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.organization_id == org_id,
                ExchangeListing.symbol == symbol.upper(),
            )
        )
    ).scalar_one_or_none()
    if not listing:
        raise ExchangeError(404, "listing not found for this organization")
    row = (
        await db.execute(
            select(ExchangeMarketMaker).where(
                ExchangeMarketMaker.listing_id == listing.id,
                ExchangeMarketMaker.agent_did == did,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = ExchangeMarketMaker(
            listing_id=listing.id, agent_did=did, granted_by_dev=developer.id
        )
        db.add(row)
    row.status = status
    if min_uptime_pct is not None:
        row.min_uptime_pct = int(min_uptime_pct)
    if max_spread_bps is not None:
        row.max_spread_bps = int(max_spread_bps)
    # Reflect on the participant trading-identity row (surface flag): true while the DID
    # holds at least one active seat anywhere, else false.
    part = (
        await db.execute(select(ExchangeParticipant).where(ExchangeParticipant.agent_did == did))
    ).scalar_one_or_none()
    if part is not None:
        still_active = (
            await db.execute(
                select(ExchangeMarketMaker.id).where(
                    ExchangeMarketMaker.agent_did == did,
                    ExchangeMarketMaker.status == "active",
                    ExchangeMarketMaker.listing_id != listing.id,
                )
            )
        ).first()
        part.market_maker = (status == "active") or (still_active is not None)
    await db.commit()
    await db.refresh(row)
    return {
        "symbol": listing.symbol,
        "agent_did": row.agent_did,
        "status": row.status,
        "min_uptime_pct": row.min_uptime_pct,
        "max_spread_bps": row.max_spread_bps,
    }


async def list_market_makers(db: AsyncSession, listing_ref: str) -> Dict[str, Any]:
    """PUBLIC — the designated market-makers committed to a listing + their obligation
    params (a credibility surface). Accepts id OR symbol."""
    listing = await _get_listing(db, listing_ref)
    rows = (
        await db.execute(
            select(ExchangeMarketMaker)
            .where(ExchangeMarketMaker.listing_id == listing.id)
            .order_by(ExchangeMarketMaker.created_at.asc())
        )
    ).scalars().all()
    mms = [
        {
            "agent_did": r.agent_did,
            "status": r.status,
            "min_uptime_pct": r.min_uptime_pct,
            "max_spread_bps": r.max_spread_bps,
            "since": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {
        "symbol": listing.symbol,
        "maker_rebate_bps": getattr(listing, "maker_rebate_bps", 0),
        "rebate_requires_registration": getattr(listing, "rebate_requires_registration", True),
        "market_makers": mms,
        "active_count": sum(1 for m in mms if m["status"] == "active"),
    }


# ── §2026-06-22 P5 (5.6) admin fee-edit ───────────────────────────────────
async def set_listing_fees(
    db: AsyncSession,
    org_id: str,
    symbol: str,
    developer: "Developer",
    *,
    fee_bps: Optional[int] = None,
    fee_org_split_bps: Optional[int] = None,
    maker_rebate_bps: Optional[int] = None,
) -> Dict[str, Any]:
    """Set an org listing's fee schedule (ORG-ADMIN; mirrors set_maker_rebate). Only the
    provided fields are updated. Δ-NEUTRAL: new trades stamp the new fee_bps/split at match;
    this NEVER touches an existing trade, escrow leg, or balance.

    CRITICAL config bound: after applying the change, re-validate the maker-rebate invariant
    (the same B-2 bound enforced in set_maker_rebate) — the effective maker_rebate_bps must
    still fit inside the PROTOCOL fee slice:
        maker_rebate_bps ≤ fee_bps − fee_bps·fee_org_split_bps/1e4
    A fee_bps decrease or an org-split increase can shrink the protocol slice below an already
    stored rebate; if the resulting state would violate the bound we reject 422 so the carve in
    _match can never drive fee_proto negative."""
    if not await OrganizationService.check_member_permission(db, org_id, developer.id, "admin"):
        raise ExchangeError(403, "org admin role required")
    listing = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.organization_id == org_id,
                ExchangeListing.symbol == symbol.upper(),
            )
        )
    ).scalar_one_or_none()
    if not listing:
        raise ExchangeError(404, "listing not found for this organization")

    # Resolve the prospective values (provided ⇒ override, else current).
    new_fee_bps = int(fee_bps) if fee_bps is not None else int(listing.fee_bps)
    new_org_split_bps = (
        int(fee_org_split_bps) if fee_org_split_bps is not None else int(listing.fee_org_split_bps)
    )
    new_rebate_bps = (
        int(maker_rebate_bps) if maker_rebate_bps is not None else int(getattr(listing, "maker_rebate_bps", 0) or 0)
    )

    # Field-range validation (fee_bps capped at 1000 = 10%; org split is a fraction of the fee).
    if not (0 <= new_fee_bps <= 1000):
        raise ExchangeError(422, "fee_bps must be in [0, 1000] (≤10%)")
    if not (0 <= new_org_split_bps <= 10000):
        raise ExchangeError(422, "fee_org_split_bps must be in [0, 10000]")
    if new_rebate_bps < 0:
        raise ExchangeError(422, "maker_rebate_bps must be ≥ 0")

    # Config bound (re-validated against the PROSPECTIVE fee schedule): the rebate must fit
    # inside the protocol slice so fee_proto ≥ 0 at every future match. proto slice (bps of
    # notional) = fee_bps − fee_bps·org_split_bps/1e4. Identical math to set_maker_rebate.
    proto_bps_of_notional = Decimal(new_fee_bps) - q18(
        Decimal(new_fee_bps) * Decimal(new_org_split_bps) / Decimal(10000)
    )
    if Decimal(new_rebate_bps) > proto_bps_of_notional:
        raise ExchangeError(
            422,
            f"resulting maker_rebate_bps {new_rebate_bps} would exceed the protocol fee slice "
            f"({proto_bps_of_notional} bps of notional = fee_bps − org split); lower the rebate "
            f"or raise fee_bps / lower the org split first",
        )

    listing.fee_bps = new_fee_bps
    listing.fee_org_split_bps = new_org_split_bps
    listing.maker_rebate_bps = new_rebate_bps
    await db.commit()
    await db.refresh(listing)
    return {
        "symbol": listing.symbol,
        "fee_bps": listing.fee_bps,
        "fee_org_split_bps": listing.fee_org_split_bps,
        "maker_rebate_bps": listing.maker_rebate_bps,
        "rebate_requires_registration": listing.rebate_requires_registration,
        "protocol_fee_slice_bps_of_notional": str(proto_bps_of_notional),
        "note": "Δ-neutral: new trades stamp the new fee schedule at match; existing trades/escrow untouched",
    }


# ── §2026-06-22 P5 (5.4) cap-table + AGORA index (PUBLIC reads) ────────────
async def listing_holders(
    db: AsyncSession, listing_ref: str, *, limit: int = 50, offset: int = 0
) -> Dict[str, Any]:
    """PUBLIC cap-table: the external shareholders of a listing (EXCLUDING the keyless org
    treasury), sorted by qty desc, paginated. Pure read — no money, no mutation. Mirrors the
    enfranchisement holder query (qty>0, excl treasury_agent_did)."""
    listing = await _get_listing(db, listing_ref)
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    rows = (
        await db.execute(
            select(OrgSharePosition).where(
                OrgSharePosition.listing_id == listing.id,
                OrgSharePosition.qty > 0,
                OrgSharePosition.agent_did != listing.treasury_agent_did,
            )
        )
    ).scalars().all()
    total_shares = int(listing.total_shares or 0)
    treasury_pos = (
        await db.execute(
            select(OrgSharePosition.qty).where(
                OrgSharePosition.listing_id == listing.id,
                OrgSharePosition.agent_did == listing.treasury_agent_did,
            )
        )
    ).scalar_one_or_none()
    rows_sorted = sorted(rows, key=lambda h: int(h.qty), reverse=True)
    holder_count = len(rows_sorted)
    page = rows_sorted[offset : offset + limit]
    holders = [
        {
            "agent_did": h.agent_did,
            "qty": int(h.qty),
            "pct": (
                str(q18(Decimal(int(h.qty)) / Decimal(total_shares) * Decimal(100)))
                if total_shares > 0
                else None
            ),
        }
        for h in page
    ]
    return {
        "symbol": listing.symbol,
        "total_shares": total_shares,
        "holder_count": holder_count,
        "treasury_qty": int(treasury_pos) if treasury_pos is not None else 0,
        "limit": limit,
        "offset": offset,
        "holders": holders,
    }


# In-process cache for the index (mirrors registry_card_builder._cache_* TTL pattern).
# NOTE: a leader-elected historical-index worker (time-series snapshots) is the v2 — OUT OF
# SCOPE here; this v1 computes the index fresh on serve (small query) with a short TTL cache.
_INDEX_CACHE: Dict[str, Tuple[float, Any]] = {}
_INDEX_CACHE_TTL = 30.0  # seconds


async def agora_index(db: AsyncSession, *, top_n: int = 10) -> Dict[str, Any]:
    """PUBLIC market-cap-weighted "AGORA N" index over the top-N approved, non-delisted
    listings by market cap (last_price·total_shares). last_price falls back to ipo_price when
    a listing has no secondary trade yet (same rule the stock card / listing_stats use). Pure
    read — Δ-irrelevant. Cached in-process ~30s."""
    top_n = max(1, min(int(top_n), 50))
    ckey = f"agora_index:{top_n}"
    cached = _INDEX_CACHE.get(ckey)
    if cached is not None and (time.monotonic() - cached[0]) <= _INDEX_CACHE_TTL:
        return cached[1]

    listings = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.approved.is_(True),
                ExchangeListing.status != "delisted",
            )
        )
    ).scalars().all()

    rows: List[Dict[str, Any]] = []
    for l in listings:
        last = await _last_price(db, l.id)
        if last is None and l.ipo_price and l.ipo_price > ZERO:
            last = l.ipo_price  # opening-price fallback (see listing_stats)
        if last is None or last <= ZERO:
            continue
        try:
            mcap = q18(last * Decimal(int(l.total_shares)))
        except ArithmeticError:
            # mcap needs no sub-unit precision; fall back to 2dp on Decimal-context overflow
            # (same guard as listing_stats for large 18dp·share-count products).
            mcap = (last * Decimal(int(l.total_shares))).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        rows.append({"symbol": l.symbol, "last": last, "total_shares": int(l.total_shares), "market_cap": mcap})

    rows.sort(key=lambda r: r["market_cap"], reverse=True)
    constituents = rows[:top_n]
    index_value = sum((c["market_cap"] for c in constituents), ZERO)
    out = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "index_value": str(index_value),
        "count": len(constituents),
        "constituents": [
            {
                "symbol": c["symbol"],
                "last": str(c["last"]),
                "total_shares": c["total_shares"],
                "market_cap": str(c["market_cap"]),
                "weight_pct": (
                    str(q18(c["market_cap"] / index_value * Decimal(100))) if index_value > ZERO else None
                ),
            }
            for c in constituents
        ],
    }
    _INDEX_CACHE[ckey] = (time.monotonic(), out)
    return out


# ── P3.1 share-weighted shareholder governance ────────────────────────────
async def create_proposal(
    db: AsyncSession,
    org_id: str,
    symbol: str,
    developer: "Developer",
    *,
    title: str,
    description: str,
    duration_seconds: int,
    quorum_pct: float = 20.0,
    pass_pct: float = 50.0,
    proposal_type: str = "advisory",
    action_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """§P3.1 Open a share-weighted shareholder proposal on a listing (ORG-ADMIN). Freezes the
    eligible-holder snapshot at creation (treasury excluded, like dividends) — there is no
    holdings-by-seq replay, so weights MUST be materialized now. Δ-irrelevant (no money).
    §2026-06-22 P1.4: proposal_type="advisory" (no effect) | "dilution" (on pass, org-admin
    executes a share mint via execute_dilution); action_params carries {new_shares, destination}."""
    if not await OrganizationService.check_member_permission(db, org_id, developer.id, "admin"):
        raise ExchangeError(403, "org admin role required to open a proposal")
    if not (title or "").strip() or not (description or "").strip():
        raise ExchangeError(422, "title and description required")
    proposal_type = (proposal_type or "advisory").lower()
    if proposal_type not in ("advisory", "dilution"):
        raise ExchangeError(422, "proposal_type must be 'advisory' or 'dilution'")
    if proposal_type == "dilution":
        ap = action_params or {}
        try:
            new_shares = int(ap.get("new_shares") or 0)
        except (TypeError, ValueError):
            new_shares = 0
        if not (0 < new_shares <= 10**15):
            raise ExchangeError(422, "dilution requires action_params.new_shares in (0, 1e15]")
        action_params = {"new_shares": new_shares, "destination": "treasury"}  # v1: mint to treasury
    else:
        action_params = None
    dur = max(60, min(int(duration_seconds), 2592000))
    listing = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.organization_id == org_id,
                ExchangeListing.symbol == symbol.upper(),
            )
        )
    ).scalar_one_or_none()
    if not listing:
        raise ExchangeError(404, "listing not found for this organization")
    if not listing.approved:
        raise ExchangeError(409, "listing not approved")
    await _listing_lock(db, listing.id)
    snapshot_seq = (
        await db.execute(
            select(func.coalesce(func.max(ExchangeTrade.seq), 0)).where(ExchangeTrade.listing_id == listing.id)
        )
    ).scalar_one()
    holders = (
        await db.execute(
            select(OrgSharePosition).where(OrgSharePosition.listing_id == listing.id, OrgSharePosition.qty > 0)
        )
    ).scalars().all()
    holders = [h for h in holders if h.agent_did != listing.treasury_agent_did]
    if not holders:
        await db.rollback()
        raise ExchangeError(409, "no external holders to enfranchise")
    enfranchised = sum(int(h.qty) for h in holders)
    prop = ExchangeProposal(
        listing_id=listing.id, proposer_did=f"dev:{developer.id}", title=title.strip()[:255],
        description=description.strip(), quorum_pct=float(quorum_pct), pass_pct=float(pass_pct),
        snapshot_seq=int(snapshot_seq), enfranchised_total=int(enfranchised),
        end_at=datetime.now(timezone.utc) + timedelta(seconds=dur),
        proposal_type=proposal_type, action_params=action_params,
    )
    db.add(prop)
    await db.flush()
    for h in holders:
        db.add(ExchangeProposalHolder(proposal_id=prop.id, agent_did=h.agent_did, weight=int(h.qty)))
    await db.commit()
    _emit(
        "ExchangeProposalOpened", listing.id,
        {"proposal_id": prop.id, "symbol": listing.symbol, "enfranchised": str(enfranchised)},
        key=f"exchange-prop:{prop.id}",
    )
    return await get_proposal(db, prop.id)


async def cast_share_vote(
    db: AsyncSession, agent_did: str, proposal_id: str, in_favor: bool, reason: Optional[str] = None,
    voter_registry_id: Optional[str] = None,
) -> Dict[str, Any]:
    """§P3.1 Cast a share-weighted vote (caller = shareholder agent). One vote per DID; weight is
    the FROZEN snapshot weight (buying shares mid-vote cannot increase power).
    §2026-06-22 cross-frame: `voter_registry_id` is the relaying peer's SPIFFE when the vote
    arrives via the federation channel (a foreign-homed shareholder who is in this venue's
    snapshot but cannot authenticate locally); NULL = local same-registry voter. Enfranchisement
    is by snapshot membership (agent_did is globally unique), so a foreign voter validates the
    same way. Δ-irrelevant (no money)."""
    prop = (
        await db.execute(select(ExchangeProposal).where(ExchangeProposal.id == proposal_id))
    ).scalar_one_or_none()
    if not prop:
        raise ExchangeError(404, "proposal not found")
    if prop.status != "voting" or datetime.now(timezone.utc) > prop.end_at:
        raise ExchangeError(409, "voting closed")
    holder = (
        await db.execute(
            select(ExchangeProposalHolder).where(
                ExchangeProposalHolder.proposal_id == prop.id,
                ExchangeProposalHolder.agent_did == agent_did,
            )
        )
    ).scalar_one_or_none()
    if not holder or holder.weight <= 0:
        raise ExchangeError(403, "not a holder at the snapshot")
    existing = (
        await db.execute(
            select(ExchangeProposalVote).where(
                ExchangeProposalVote.proposal_id == prop.id,
                ExchangeProposalVote.agent_did == agent_did,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.vote = bool(in_favor)
        existing.reason = (reason or None)
        existing.voter_registry_id = voter_registry_id
    else:
        db.add(ExchangeProposalVote(
            proposal_id=prop.id, agent_did=agent_did, vote=bool(in_favor),
            weight=int(holder.weight), reason=(reason or None),
            voter_registry_id=voter_registry_id,
        ))
    await db.commit()
    _emit(
        "ExchangeVoteCast", prop.listing_id,
        {"proposal_id": prop.id, "agent_did": agent_did, "weight": str(holder.weight), "for": bool(in_favor)},
        key=f"exchange-vote:{prop.id}:{agent_did}",
    )
    return {"status": "ok", "proposal_id": prop.id, "weight": int(holder.weight), "for": bool(in_favor)}


async def tally_proposal(db: AsyncSession, proposal_id: str, *, finalize: bool = True) -> Dict[str, Any]:
    """§P3.1 Tally a share-weighted proposal: SUM(weight) for/against, quorum vs enfranchised,
    pass threshold. Finalizes (passed/failed) once voting has ended."""
    prop = (
        await db.execute(select(ExchangeProposal).where(ExchangeProposal.id == proposal_id))
    ).scalar_one_or_none()
    if not prop:
        raise ExchangeError(404, "proposal not found")
    for_w = (
        await db.execute(
            select(func.coalesce(func.sum(ExchangeProposalVote.weight), 0)).where(
                ExchangeProposalVote.proposal_id == prop.id, ExchangeProposalVote.vote.is_(True)
            )
        )
    ).scalar_one()
    against_w = (
        await db.execute(
            select(func.coalesce(func.sum(ExchangeProposalVote.weight), 0)).where(
                ExchangeProposalVote.proposal_id == prop.id, ExchangeProposalVote.vote.is_(False)
            )
        )
    ).scalar_one()
    cast = int(for_w) + int(against_w)
    # §2026-06-22 cross-frame: how many distinct home-frames participated (NULL → "local").
    distinct_registries = (
        await db.execute(
            select(func.count(func.distinct(func.coalesce(ExchangeProposalVote.voter_registry_id, "local")))).where(
                ExchangeProposalVote.proposal_id == prop.id
            )
        )
    ).scalar_one()
    quorum_met = cast >= prop.enfranchised_total * (prop.quorum_pct / 100.0)
    passed = bool(quorum_met and cast > 0 and (int(for_w) / cast * 100.0) >= prop.pass_pct)
    ended = datetime.now(timezone.utc) > prop.end_at
    if finalize and ended and prop.status == "voting":
        prop.status = "passed" if passed else "failed"
        await db.commit()
        _emit(
            "ExchangeProposalTallied", prop.listing_id,
            {"proposal_id": prop.id, "passed": passed, "for": str(int(for_w)), "against": str(int(against_w))},
            key=f"exchange-tally:{prop.id}",
        )
    return {
        "proposal_id": prop.id, "for": int(for_w), "against": int(against_w),
        "enfranchised": prop.enfranchised_total, "cast": cast, "quorum_met": bool(quorum_met),
        "passed": passed, "voting_ended": ended, "status": prop.status,
        "distinct_registries": int(distinct_registries),
    }


async def get_proposal(db: AsyncSession, proposal_id: str) -> Dict[str, Any]:
    prop = (
        await db.execute(select(ExchangeProposal).where(ExchangeProposal.id == proposal_id))
    ).scalar_one_or_none()
    if not prop:
        raise ExchangeError(404, "proposal not found")
    sym = (
        await db.execute(select(ExchangeListing.symbol).where(ExchangeListing.id == prop.listing_id))
    ).scalar_one_or_none()
    return {
        "id": prop.id, "symbol": sym, "title": prop.title, "description": prop.description,
        "status": prop.status, "proposer_did": prop.proposer_did, "quorum_pct": prop.quorum_pct,
        "pass_pct": prop.pass_pct, "enfranchised_total": prop.enfranchised_total,
        "proposal_type": getattr(prop, "proposal_type", "advisory"), "action_params": getattr(prop, "action_params", None),
        "end_at": prop.end_at.isoformat() if prop.end_at else None,
        "created_at": prop.created_at.isoformat() if prop.created_at else None,
    }


async def execute_dilution(db: AsyncSession, proposal_id: str, developer: "Developer") -> Dict[str, Any]:
    """§2026-06-22 P1.4 — execute a PASSED dilution proposal (ORG-ADMIN). Mints new_shares to the
    listing's treasury position: total_shares += N AND treasury OrgSharePosition.qty += N — the exact
    dual of re-float, so I-X1 (Σpositions == (total_shares − ipo_float) + ipo_sold, when approved)
    stays balanced (RHS +N via total_shares, LHS +N via the treasury position). status passed→applied
    (idempotent guard vs double-mint). Δ-irrelevant (shares are the registry ledger, NOT TEG money)."""
    prop = (
        await db.execute(select(ExchangeProposal).where(ExchangeProposal.id == proposal_id))
    ).scalar_one_or_none()
    if not prop:
        raise ExchangeError(404, "proposal not found")
    if (prop.proposal_type or "advisory") != "dilution":
        raise ExchangeError(409, "not a dilution proposal (no executable action)")
    if prop.status == "applied":
        raise ExchangeError(409, "dilution already executed")
    if prop.status != "passed":
        raise ExchangeError(409, f"proposal must be PASSED to execute (current: {prop.status})")
    listing = (
        await db.execute(select(ExchangeListing).where(ExchangeListing.id == prop.listing_id))
    ).scalar_one_or_none()
    if not listing:
        raise ExchangeError(404, "listing not found")
    if not await OrganizationService.check_member_permission(db, listing.organization_id, developer.id, "admin"):
        raise ExchangeError(403, "org admin role required to execute")
    if not listing.approved:
        raise ExchangeError(409, "listing not approved")
    n = int((prop.action_params or {}).get("new_shares") or 0)
    if n <= 0:
        raise ExchangeError(422, "invalid new_shares on proposal")
    await _listing_lock(db, listing.id)
    await db.refresh(listing)
    await db.refresh(prop)
    if prop.status == "applied":  # raced another executor
        await db.rollback()
        raise ExchangeError(409, "dilution already executed")
    pos = await _get_or_create_position(db, listing.id, listing.treasury_agent_did)
    listing.total_shares = int(listing.total_shares) + n   # MINT
    pos.qty = int(pos.qty) + n                              # to treasury (keeps I-X1 balanced)
    prop.status = "applied"
    await db.commit()
    _emit(
        "ExchangeSharesIssued", listing.id,
        {"symbol": listing.symbol, "new_shares": str(n), "destination": "treasury",
         "total_shares": str(listing.total_shares), "treasury_qty": str(pos.qty), "proposal_id": prop.id},
        key=f"exchange-dilute:{prop.id}",
    )
    return {"status": "applied", "proposal_id": prop.id, "symbol": listing.symbol,
            "minted": n, "total_shares": int(listing.total_shares), "treasury_qty": int(pos.qty)}


async def split_listing(db: AsyncSession, org_id: str, symbol: str, developer: "Developer", *, factor: int) -> Dict[str, Any]:
    """§2026-06-22 P1.3 forward stock split N:1 (ORG-ADMIN, no vote — proportional/administrative,
    harmless to holders). Rescales EVERY holder's qty ×N, total_shares/ipo_float/ipo_sold ×N, and
    ipo_price ÷N (tick-snapped). Ownership fractions + market cap (shares×price) are UNCHANGED.
    Δ-neutral (shares are the registry ledger, NOT money; no TEG move). I-X1 stays balanced (LHS Σpos
    and RHS (total_shares-ipo_float)+ipo_sold both scale ×N). Requires NO open orders — rescaling an
    open order's price on a tick-snap would drift its escrow notional; caller halts + clears the book
    first via the existing halt/cancel endpoints. (Reverse split ÷N deferred — fractional-share policy.)"""
    if not await OrganizationService.check_member_permission(db, org_id, developer.id, "admin"):
        raise ExchangeError(403, "org admin role required to split a listing")
    N = int(factor)
    if not (2 <= N <= 1000):
        raise ExchangeError(422, "split factor must be an integer in [2, 1000] (forward split; reverse not supported in v1)")
    listing = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.organization_id == org_id, ExchangeListing.symbol == symbol.upper()
            )
        )
    ).scalar_one_or_none()
    if not listing:
        raise ExchangeError(404, "listing not found for this organization")
    if not listing.approved:
        raise ExchangeError(409, "listing not approved")
    await _listing_lock(db, listing.id)
    await db.refresh(listing)
    open_ct = (
        await db.execute(
            select(func.count()).select_from(ExchangeOrder).where(
                ExchangeOrder.listing_id == listing.id,
                ExchangeOrder.status.in_(("open", "partial", "funding")),
            )
        )
    ).scalar_one()
    if int(open_ct) > 0:
        await db.rollback()
        raise ExchangeError(409, f"halt + clear the order book first ({open_ct} open orders) — split rescales positions only")
    positions = (
        await db.execute(select(OrgSharePosition).where(OrgSharePosition.listing_id == listing.id))
    ).scalars().all()
    for p in positions:
        p.qty = int(p.qty) * N
        p.locked_qty = int(p.locked_qty) * N  # 0 here (no open orders), rescaled for safety
    old_total = int(listing.total_shares)
    listing.total_shares = old_total * N
    listing.ipo_float = int(listing.ipo_float) * N
    listing.ipo_sold = int(listing.ipo_sold) * N
    tick = Decimal(str(listing.tick or "0.01"))
    snapped = (Decimal(str(listing.ipo_price)) / N / tick).to_integral_value() * tick  # V0120 tick-snap (NOT .quantize)
    listing.ipo_price = snapped if snapped >= tick else tick
    await db.commit()
    _emit(
        "ExchangeSharesSplit", listing.id,
        {"symbol": listing.symbol, "factor": str(N), "total_shares": str(listing.total_shares),
         "ipo_price": str(listing.ipo_price), "holders_rescaled": str(len(positions))},
        key=f"exchange-split:{listing.id}:{old_total}->{listing.total_shares}",
    )
    return {"status": "ok", "symbol": listing.symbol, "factor": N, "total_shares": int(listing.total_shares),
            "ipo_price": str(listing.ipo_price), "holders_rescaled": len(positions)}


async def list_proposals(db: AsyncSession, listing_ref: str) -> Dict[str, Any]:
    listing = await _get_listing(db, listing_ref)
    props = (
        await db.execute(
            select(ExchangeProposal).where(ExchangeProposal.listing_id == listing.id)
            .order_by(ExchangeProposal.created_at.desc()).limit(50)
        )
    ).scalars().all()
    return {
        "symbol": listing.symbol,
        "proposals": [
            {"id": p.id, "title": p.title, "status": p.status, "enfranchised_total": p.enfranchised_total,
             "end_at": p.end_at.isoformat() if p.end_at else None}
            for p in props
        ],
    }


async def _get_listing(db: AsyncSession, listing_ref: str) -> ExchangeListing:
    """Accepts id OR symbol."""
    q = select(ExchangeListing).where(
        or_(ExchangeListing.id == listing_ref, ExchangeListing.symbol == listing_ref.upper())
    )
    listing = (await db.execute(q)).scalars().first()
    if not listing:
        raise ExchangeError(404, f"listing '{listing_ref}' not found")
    return listing


async def _get_or_create_position(db: AsyncSession, listing_id: str, agent_did: str) -> OrgSharePosition:
    pos = (
        await db.execute(
            select(OrgSharePosition).where(
                OrgSharePosition.listing_id == listing_id,
                OrgSharePosition.agent_did == agent_did,
            )
        )
    ).scalar_one_or_none()
    if pos is None:
        pos = OrgSharePosition(listing_id=listing_id, agent_did=agent_did, qty=0, locked_qty=0)
        db.add(pos)
        await db.flush()
    return pos


# ── IPO (fixed-price primary) ────────────────────────────────────────────
async def ipo_buy(db: AsyncSession, agent_did: str, listing_ref: str, qty: int) -> ExchangeIpoPurchase:
    await _require_venue_open(db)
    listing = await _get_listing(db, listing_ref)
    await ensure_participant(db, agent_did)
    if not listing.approved or listing.status not in ("trading", "halted"):
        raise ExchangeError(409, "listing not approved/open for launch")
    if listing.status == "halted":
        raise ExchangeError(409, "listing halted")
    if qty <= 0:
        raise ExchangeError(422, "qty must be > 0")
    if listing.ipo_sold + qty > listing.ipo_float:
        raise ExchangeError(409, f"launch allocation remaining: {listing.ipo_float - listing.ipo_sold}")
    amount = q18(listing.ipo_price * Decimal(qty))
    if amount > MAX_ORDER_NOTIONAL:
        raise ExchangeError(422, f"max notional per purchase is {MAX_ORDER_NOTIONAL}")

    purchase = ExchangeIpoPurchase(listing_id=listing.id, agent_did=agent_did, qty=qty, amount=amount)
    db.add(purchase)
    await db.commit()
    await db.refresh(purchase)

    # Deposit leg (buyer → escrow). Insufficient funds → rejected, nothing moved.
    try:
        await mover.move(agent_did, EXCHANGE_ESCROW_SENTINEL, amount, "ipo_deposit", f"ipo-{purchase.id}:dep")
    except MoverError as e:
        purchase.status = "rejected"
        await db.commit()
        raise _deposit_failed(e, "launch deposit failed")

    # Allocate under the listing lock (float may have moved while funding).
    await _listing_lock(db, listing.id)
    await db.refresh(listing)
    if listing.ipo_sold + qty <= listing.ipo_float and listing.status != "delisted":
        listing.ipo_sold += qty
        pos = await _get_or_create_position(db, listing.id, agent_did)
        _update_avg_cost(pos, qty, listing.ipo_price)
        pos.qty += qty
        purchase.status = "allocated"
    else:
        purchase.status = "refunding"  # worker refunds the deposit
    await db.commit()
    await db.refresh(purchase)
    return purchase


def _update_avg_cost(pos: OrgSharePosition, add_qty: int, price: Decimal) -> None:
    total_qty = pos.qty + add_qty
    if total_qty > 0:
        pos.avg_cost = q18(((pos.avg_cost * Decimal(pos.qty)) + (price * Decimal(add_qty))) / Decimal(total_qty))


# ── orders + matching ─────────────────────────────────────────────────────
async def _last_price(db: AsyncSession, listing_id: str) -> Optional[Decimal]:
    row = (
        await db.execute(
            select(ExchangeTrade.price)
            .where(ExchangeTrade.listing_id == listing_id)
            .order_by(ExchangeTrade.seq.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


def _band_bounds(last: Decimal, band_pct: int) -> Tuple[Decimal, Decimal]:
    spread = last * Decimal(band_pct) / Decimal(100)
    return (last - spread, last + spread)


async def _best_opposite_price(
    db: AsyncSession, listing_id: str, taker_side: str, exclude_did: str
) -> Optional[Decimal]:
    """§2026-06-22 P5.1 post-only — best resting price on the OPPOSITE side, excluding
    the taker's own resting orders (self-trades never fill — D17). A BUY's opposite is the
    best ask (min sell price); a SELL's opposite is the best bid (max buy price). Returns
    None when the opposite book is empty (post-only then can't cross → always rests)."""
    opposite = "sell" if taker_side == "buy" else "buy"
    agg = func.min if taker_side == "buy" else func.max
    return (
        await db.execute(
            select(agg(ExchangeOrder.price)).where(
                ExchangeOrder.listing_id == listing_id,
                ExchangeOrder.side == opposite,
                ExchangeOrder.status.in_(("open", "partial")),
                ExchangeOrder.agent_did != exclude_did,
            )
        )
    ).scalar_one_or_none()


async def _immediately_fillable_qty(
    db: AsyncSession, listing_id: str, taker_side: str, taker_cap: Decimal, exclude_did: str
) -> int:
    """§2026-06-22 P5.1 FOK dry-run — total resting qty that WOULD fill a taker right now,
    capped at the taker's price (mirrors _match's eligibility exactly: same status set,
    same price-cross test, same self-trade skip). Read-only; commits nothing. FOK rejects
    pre-escrow when this is < the order qty, so no money ever moves on a non-fillable FOK."""
    q = select(ExchangeOrder.remaining).where(
        ExchangeOrder.listing_id == listing_id,
        ExchangeOrder.side == ("sell" if taker_side == "buy" else "buy"),
        ExchangeOrder.status.in_(("open", "partial")),
        ExchangeOrder.agent_did != exclude_did,
    )
    q = q.where(ExchangeOrder.price <= taker_cap) if taker_side == "buy" else q.where(ExchangeOrder.price >= taker_cap)
    rows = (await db.execute(q)).scalars().all()
    return sum(int(r) for r in rows)


@dataclass
class PlacedOrder:
    order: ExchangeOrder
    fills: List[ExchangeTrade] = field(default_factory=list)


async def _cb_enabled(db: AsyncSession) -> bool:
    """Master gate: env EXCHANGE_CB_ENABLED OR the live DB flag `cb_enabled` (same pattern as
    the MM's mm_default_on / the demand-director) so the breaker can be flipped on a running
    registry with NO recreate, and rolled back instantly."""
    if (os.getenv("EXCHANGE_CB_ENABLED", "false") or "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    try:
        return (await get_flag(db, "cb_enabled")) == "true"
    except Exception:
        return False


async def _circuit_breaker_resume(db: AsyncSession, listing: ExchangeListing) -> bool:
    """§#84 lazy auto-resume: if the listing is cb-halted and the cooldown (cb_halted_until)
    has passed, un-halt and re-baseline the reference to the current last. Returns True if it
    resumed. Δ-irrelevant (status/state only). Safe to call at the top of every place_order."""
    if listing.status != "halted" or not listing.cb_halted_until:
        return False
    now = datetime.now(timezone.utc)
    if now < listing.cb_halted_until:
        return False
    last = await _last_price(db, listing.id)
    listing.status = "trading"
    listing.cb_halted_until = None
    listing.cb_ref_price = last
    listing.cb_ref_at = now
    await db.commit()
    _emit(
        "ExchangeListingHalted", listing.id,
        {"symbol": listing.symbol, "halted": "False", "reason": "circuit_breaker_resume"},
        key=f"exchange-cb-resume:{listing.id}:{now.strftime('%Y%m%d%H%M%S')}",
    )
    logger.info(f"[circuit_breaker] {listing.symbol} auto-resumed (cooldown elapsed)")
    return True


async def _circuit_breaker_react(db: AsyncSession, listing: ExchangeListing, new_last: Optional[Decimal]) -> bool:
    """§#84 — after a fill, roll the per-listing volatility reference and AUTO-HALT if `last`
    moved > cb_pct/1e4 from the reference within EXCHANGE_CB_WINDOW_SEC. Returns True if it
    halted. Δ-irrelevant: only flips status (trading→halted) + tracks a reference price/time;
    no money/share mutation. Gated: EXCHANGE_CB_ENABLED (master) AND per-listing cb_pct>0."""
    if not await _cb_enabled(db) or not listing.cb_pct or listing.cb_pct <= 0:
        return False
    if new_last is None or new_last <= ZERO:
        return False
    now = datetime.now(timezone.utc)
    win = int(os.getenv("EXCHANGE_CB_WINDOW_SEC", "300") or 300)
    ref, ref_at = listing.cb_ref_price, listing.cb_ref_at
    # (re)baseline when missing or the rolling window has elapsed
    if ref is None or ref <= ZERO or ref_at is None or (now - ref_at).total_seconds() > win:
        listing.cb_ref_price = new_last
        listing.cb_ref_at = now
        await db.commit()
        return False
    move = abs(new_last - ref) / ref
    if move > (Decimal(listing.cb_pct) / Decimal(10000)):
        cd = int(os.getenv("EXCHANGE_CB_COOLDOWN_SEC", "300") or 300)
        listing.status = "halted"
        listing.cb_halted_until = now + timedelta(seconds=cd)
        await db.commit()
        _emit(
            "ExchangeListingHalted", listing.id,
            {"symbol": listing.symbol, "halted": "True", "reason": "circuit_breaker",
             "move_pct": str(q18(move * Decimal(100))), "ref": str(ref), "last": str(new_last),
             "cooldown_sec": str(cd)},
            key=f"exchange-cb-halt:{listing.id}:{now.strftime('%Y%m%d%H%M%S')}",
        )
        logger.warning(
            f"[circuit_breaker] {listing.symbol} HALTED move={q18(move*Decimal(100))}% "
            f"ref={ref} last={new_last} cooldown={cd}s"
        )
        return True
    return False


async def resume_expired_circuit_breakers(db: AsyncSession) -> int:
    """§#84 time-based auto-resume — the settlement worker calls this each cycle to un-halt any
    listing whose circuit-breaker cooldown (cb_halted_until) has elapsed. This is the PRIMARY
    resume path: a halted listing receives no orders (discovery/sim skip it), so the order-time
    lazy-resume in place_order can't fire on its own. A NULL cb_halted_until (a MANUAL halt) is
    excluded by the `< now` predicate, so ONLY breaker-halts auto-resume. Re-baselines the
    reference on resume so the post-halt move is measured fresh. Δ-irrelevant (status/state only)."""
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.status == "halted",
                ExchangeListing.cb_halted_until < now,
            )
        )
    ).scalars().all()
    n = 0
    for listing in rows:
        last = await _last_price(db, listing.id)
        listing.status = "trading"
        listing.cb_halted_until = None
        listing.cb_ref_price = last
        listing.cb_ref_at = now
        _emit(
            "ExchangeListingHalted", listing.id,
            {"symbol": listing.symbol, "halted": "False", "reason": "circuit_breaker_resume"},
            key=f"exchange-cb-resume:{listing.id}:{now.strftime('%Y%m%d%H%M%S')}",
        )
        n += 1
    if n:
        await db.commit()
        logger.info(f"[circuit_breaker] auto-resumed {n} listing(s) (cooldown elapsed)")
    return n


async def place_order(
    db: AsyncSession,
    agent_did: str,
    listing_ref: str,
    side: str,
    order_type: str,
    qty: int,
    price: Optional[Decimal] = None,
    client_order_id: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
    tif: str = "gtc",
    post_only: bool = False,
) -> PlacedOrder:
    await _require_venue_open(db)
    listing = await _get_listing(db, listing_ref)
    await ensure_participant(db, agent_did)
    await _circuit_breaker_resume(db, listing)  # §#84 lazy auto-resume if a cb-halt cooldown elapsed

    # ---- validations (D16/D18) ----
    if listing.status != "trading" or not listing.approved:
        raise ExchangeError(409, f"listing not trading (status={listing.status})")
    if side not in ("buy", "sell"):
        raise ExchangeError(422, "side must be buy|sell")
    if order_type not in ("limit", "market"):
        raise ExchangeError(422, "order_type must be limit|market")
    if qty <= 0:
        raise ExchangeError(422, "qty must be > 0")
    # §2026-06-22 P5.1 advanced order types (opt-in; defaults = today's behavior).
    tif = (tif or "gtc").lower()
    if tif not in ("gtc", "ioc", "fok"):
        raise ExchangeError(422, "tif must be gtc|ioc|fok")

    # Idempotent placement replay (client_order_id).
    if client_order_id:
        prior = (
            await db.execute(
                select(ExchangeOrder).where(
                    ExchangeOrder.listing_id == listing.id,
                    ExchangeOrder.agent_did == agent_did,
                    ExchangeOrder.client_order_id == client_order_id,
                )
            )
        ).scalars().first()
        if prior:
            return PlacedOrder(order=prior)

    open_count = (
        await db.execute(
            select(func.count(ExchangeOrder.id)).where(
                ExchangeOrder.listing_id == listing.id,
                ExchangeOrder.agent_did == agent_did,
                ExchangeOrder.status.in_(("funding", "open", "partial")),
            )
        )
    ).scalar_one()
    if open_count >= MAX_OPEN_ORDERS_PER_AGENT:
        raise ExchangeError(429, f"max {MAX_OPEN_ORDERS_PER_AGENT} open orders per agent per listing")

    last = await _last_price(db, listing.id)

    if order_type == "limit":
        if price is None or price <= ZERO:
            raise ExchangeError(422, "limit orders require price > 0")
        # tick check (Decimal-exact)
        if (price % listing.tick) != ZERO:
            raise ExchangeError(422, f"price must be a multiple of tick {listing.tick}")
        if last is not None:
            lo, hi = _band_bounds(last, listing.band_pct)
            if not (lo <= price <= hi):
                raise ExchangeError(
                    422,
                    f"price outside ±{listing.band_pct}% band around last {last} (allowed {q18(lo)}..{q18(hi)})",
                )
        effective_cap = price
    else:  # market
        if last is None and listing.ipo_price and listing.ipo_price > ZERO:
            # §2026-06-18 opening price: a listing with no secondary trades yet opens at
            # its IPO price (the opening print — how IPOs actually work), so a market
            # order references it instead of a hard "virgin book" reject. Δ-safe: a
            # read-time reference, NOT a settling trade. Limit orders above keep their
            # unconstrained virgin-book band (price discovery), so this only affects the
            # market path + the display fallback below.
            last = listing.ipo_price
        if last is None:
            raise ExchangeError(409, "market order needs a last price (virgin book — place a limit order)")
        slip = last * MARKET_SLIPPAGE_PCT / Decimal(100)
        effective_cap = q18(last + slip) if side == "buy" else q18(max(listing.tick, last - slip))
        price = None

    notional_cap = q18(effective_cap * Decimal(qty))
    if notional_cap > MAX_ORDER_NOTIONAL:
        raise ExchangeError(422, f"max notional per order is {MAX_ORDER_NOTIONAL}")

    # §2026-06-22 P5.1 post-only + FOK gate — BOTH reject PRE-ESCROW / PRE-INSERT, so a
    # rejected order moves no money and inserts no row (Δ-neutral: nothing happened). The
    # book read here is the same advisory-lock-free read as the band/last checks above; a
    # benign TOCTOU vs the locked _match is acceptable (worst case an FOK rests a sliver, an
    # already-Δ-safe outcome — escrow refunds via the existing worker path).
    if post_only:
        # A post-only order MUST be a pure maker: reject if its limit would cross the best
        # opposite (buy price ≥ best ask, or sell price ≤ best bid). Only meaningful for
        # limit orders (a market order has no resting price → can't be post-only).
        if order_type != "limit":
            raise ExchangeError(422, "post_only requires a limit order")
        best_opp = await _best_opposite_price(db, listing.id, side, agent_did)
        if best_opp is not None and (
            (side == "buy" and price >= best_opp) or (side == "sell" and price <= best_opp)
        ):
            raise ExchangeError(422, "post_only would cross")
    if tif == "fok":
        # All-or-nothing: the FULL qty must be immediately fillable against resting
        # liquidity at the taker cap, else reject with no escrow and no partial.
        fillable = await _immediately_fillable_qty(db, listing.id, side, effective_cap, agent_did)
        if fillable < qty:
            raise ExchangeError(422, f"FOK not fully fillable (need {qty}, available {fillable})")

    ttl_at = (
        datetime.now(timezone.utc) + timedelta(seconds=int(ttl_seconds))
        if ttl_seconds and int(ttl_seconds) > 0
        else None
    )

    order = ExchangeOrder(
        listing_id=listing.id,
        agent_did=agent_did,
        side=side,
        order_type=order_type,
        price=price,
        qty=qty,
        remaining=qty,
        client_order_id=client_order_id,
        ttl_expires_at=ttl_at,
        tif=tif,
        post_only=post_only,
        status="funding" if side == "buy" else "open",
        escrow_amount=notional_cap if side == "buy" else ZERO,
    )

    if side == "buy":
        # ① durable order row → ② deposit leg → ③ lock+open+match
        db.add(order)
        await db.commit()
        await db.refresh(order)
        try:
            await mover.move(
                agent_did, EXCHANGE_ESCROW_SENTINEL, order.escrow_amount, "order_deposit", f"ord-{order.id}:dep"
            )
        except MoverError as e:
            order.status = "rejected"
            order.reject_reason = f"deposit failed: {e.detail}"[:255]
            await db.commit()
            raise _deposit_failed(e, "order deposit failed")
        await _listing_lock(db, listing.id)
        await db.refresh(order)
        if order.status != "funding":  # raced by a sweeper/cancel
            return PlacedOrder(order=order)
        order.status = "open"
        fills = await _match(db, listing, order, taker_cap=effective_cap)
        await db.commit()
    else:
        # SELL: single ACID tx — lock shares, insert, match.
        await _listing_lock(db, listing.id)
        pos = await _get_or_create_position(db, listing.id, agent_did)
        free = pos.qty - pos.locked_qty
        if free < qty:
            await db.rollback()
            raise ExchangeError(409, f"insufficient free points: have {free}, need {qty}")
        pos.locked_qty += qty
        db.add(order)
        await db.flush()
        fills = await _match(db, listing, order, taker_cap=effective_cap)
        await db.commit()

    await db.refresh(order)
    agora_order_placed(side, order_type)
    _emit(
        "ExchangeOrderPlaced",
        listing.id,
        {
            "order_id": order.id,
            "symbol": listing.symbol,
            "agent_did": agent_did,
            "side": side,
            "order_type": order_type,
            "price": str(price) if price is not None else None,
            "qty": str(qty),
            "remaining": str(order.remaining),
            "status": order.status,
        },
        key=f"exchange-order:{order.id}",
    )
    for t in fills:
        agora_trade_executed(float(t.notional))
        _emit(
            "ExchangeTradeExecuted",
            listing.id,
            {
                "trade_id": t.id,
                "seq": str(t.seq),
                "symbol": listing.symbol,
                "price": str(t.price),
                "qty": str(t.qty),
                "notional": str(t.notional),
                "buyer_did": t.buyer_did,
                "seller_did": t.seller_did,
                "currency": listing.currency,
            },
            key=f"exchange-trade:{t.id}",
        )
    if fills:  # §#84 circuit-breaker reacts to the realized price move (Δ-irrelevant)
        try:
            await _circuit_breaker_react(db, listing, fills[-1].price)
        except Exception as _cbe:
            logger.warning(f"[circuit_breaker] {listing.symbol} react failed: {str(_cbe)[:120]}")
    return PlacedOrder(order=order, fills=fills)


async def _match(
    db: AsyncSession, listing: ExchangeListing, taker: ExchangeOrder, taker_cap: Decimal
) -> List[ExchangeTrade]:
    """Price-time priority match loop. MUST run inside the listing advisory-lock
    transaction. Fills at the RESTING order's price. Market-taker remainder
    beyond the cap cancels (worker refunds buy residue)."""
    fills: List[ExchangeTrade] = []
    opposite = "sell" if taker.side == "buy" else "buy"
    while taker.remaining > 0:
        q = (
            select(ExchangeOrder)
            .where(
                ExchangeOrder.listing_id == listing.id,
                ExchangeOrder.side == opposite,
                ExchangeOrder.status.in_(("open", "partial")),
                ExchangeOrder.id != taker.id,
            )
        )
        if taker.side == "buy":
            q = q.where(ExchangeOrder.price <= taker_cap).order_by(
                ExchangeOrder.price.asc(), ExchangeOrder.created_at.asc(), ExchangeOrder.id.asc()
            )
        else:
            q = q.where(ExchangeOrder.price >= taker_cap).order_by(
                ExchangeOrder.price.desc(), ExchangeOrder.created_at.asc(), ExchangeOrder.id.asc()
            )
        resting = (await db.execute(q.limit(5))).scalars().all()
        resting = [r for r in resting if r.agent_did != taker.agent_did]  # D17 self-trade skip
        if not resting:
            break
        r = resting[0]
        px = r.price  # maker price
        fqty = min(taker.remaining, r.remaining)
        notional = q18(px * Decimal(fqty))
        fee_total, fee_org, fee_proto = fee_split(notional, listing.fee_bps, listing.fee_org_split_bps)
        # §2026-06-22 P2.2 maker-taker rebate. The resting order `r` is the MAKER. The
        # rebate is carved OUT of the protocol slice (fee_proto), never added on top, so
        # the four settlement legs still sum to notional → I-X3 unchanged, Δ=0. Off by
        # flag/config ⇒ rebate=0 and fee_proto is exactly as today.
        fee_maker_rebate = await _compute_maker_rebate(
            db, listing, notional, fee_total, fee_org, r.agent_did
        )
        if fee_maker_rebate > ZERO:
            fee_proto = fee_total - fee_org - fee_maker_rebate  # ≥0 by the min() bound
            if fee_proto < ZERO:  # defensive — bound guarantees this never trips
                fee_proto = ZERO

        buyer = taker if taker.side == "buy" else r
        seller = r if taker.side == "buy" else taker
        trade = ExchangeTrade(
            listing_id=listing.id,
            buy_order_id=buyer.id,
            sell_order_id=seller.id,
            buyer_did=buyer.agent_did,
            seller_did=seller.agent_did,
            price=px,
            qty=fqty,
            notional=notional,
            fee_total=fee_total,
            fee_org=fee_org,
            fee_proto=fee_proto,
            fee_maker_rebate=fee_maker_rebate,
            maker_did=r.agent_did,  # the resting order is the maker (∈ {buyer,seller}_did)
        )
        db.add(trade)

        # share legs — ACID with the book mutation
        bpos = await _get_or_create_position(db, listing.id, buyer.agent_did)
        _update_avg_cost(bpos, fqty, px)
        bpos.qty += fqty
        spos = await _get_or_create_position(db, listing.id, seller.agent_did)
        spos.qty -= fqty
        spos.locked_qty -= fqty

        for o in (taker, r):
            o.remaining -= fqty
        buyer.matched_notional = q18(buyer.matched_notional + notional)
        for o in (taker, r):
            if o.remaining == 0:
                o.status = "filled"
            elif o.status in ("open",):
                o.status = "partial"
        await db.flush()
        fills.append(trade)

    # §2026-06-22 P5.1: the unfilled remainder must NOT rest for a market order (beyond its
    # slippage cap) OR an IOC order (tif='ioc' — immediate-or-cancel). Both take the SAME
    # terminal-cancel path: unlock any held shares (SELL) and mark the order cancelled; a BUY's
    # residual escrow (escrow − matched) is then refunded by the refund_terminal_buys worker —
    # the EXISTING Δ-neutral refund path, NOT a new money flow. GTC limit remainder rests as
    # before. (FOK / post-only never reach an unwanted-rest state: they reject pre-escrow.)
    if taker.remaining > 0 and (taker.order_type == "market" or taker.tif == "ioc"):
        if taker.side == "sell":
            pos = await _get_or_create_position(db, listing.id, taker.agent_did)
            pos.locked_qty = max(0, pos.locked_qty - taker.remaining)
        if taker.remaining == taker.qty:  # nothing filled at all
            taker.status = "cancelled"
            taker.reject_reason = (
                "IOC: no immediate match" if taker.tif == "ioc" and taker.order_type != "market"
                else "market order: no fillable liquidity within slippage cap"
            )
        else:  # partially filled — cancel the unfilled remainder
            taker.status = "cancelled"
            reason = "IOC" if taker.tif == "ioc" and taker.order_type != "market" else "market remainder beyond slippage cap"
            taker.reject_reason = f"{reason}: remainder {taker.remaining} cancelled"
    return fills


async def cancel_order(db: AsyncSession, agent_did: str, order_id: str) -> ExchangeOrder:
    order = (
        await db.execute(select(ExchangeOrder).where(ExchangeOrder.id == order_id))
    ).scalar_one_or_none()
    if not order:
        raise ExchangeError(404, "order not found")
    if order.agent_did != agent_did:
        raise ExchangeError(403, "not your order")
    await _listing_lock(db, order.listing_id)
    await db.refresh(order)
    if order.status not in ("open", "partial", "funding", "armed"):
        raise ExchangeError(409, f"order is {order.status}")
    # §#86 an ARMED stop is a pure intent (no escrow/lock at placement) → cancel is just a status
    # flip; only escrowed/active SELL orders unlock shares (a buy refunds escrow via the worker).
    if order.side == "sell" and order.status != "armed":
        pos = await _get_or_create_position(db, order.listing_id, agent_did)
        pos.locked_qty = max(0, pos.locked_qty - order.remaining)
    order.status = "cancelled"
    await db.commit()
    _emit(
        "ExchangeOrderCancelled",
        order.listing_id,
        {"order_id": order.id, "agent_did": agent_did, "remaining": str(order.remaining)},
        key=f"exchange-cancel:{order.id}",
    )
    return order


async def place_stop_order(
    db: AsyncSession, agent_did: str, listing_ref: str, side: str, order_type: str,
    qty: int, stop_price: Decimal, price: Optional[Decimal] = None,
    client_order_id: Optional[str] = None, tif: str = "gtc",
) -> "PlacedOrder":
    """§#86 STOP / STOP-LIMIT. Records an ARMED intent (NO escrow/lock at placement) that the
    trigger_armed_stops worker fires as a normal place_order once `last` crosses stop_price
    ('a stop just delays entry'). order_type='market' ⇒ stop-market; 'limit'+price ⇒ stop-limit.
    Δ-NEUTRAL at placement — no money/share movement; escrow happens at trigger via place_order."""
    await _require_venue_open(db)
    listing = await _get_listing(db, listing_ref)
    await ensure_participant(db, agent_did)
    if listing.status != "trading" or not listing.approved:
        raise ExchangeError(409, f"listing not trading (status={listing.status})")
    if side not in ("buy", "sell"):
        raise ExchangeError(422, "side must be buy|sell")
    if order_type not in ("limit", "market"):
        raise ExchangeError(422, "order_type must be limit|market")
    if qty <= 0:
        raise ExchangeError(422, "qty must be > 0")
    if stop_price is None or stop_price <= ZERO:
        raise ExchangeError(422, "stop_price must be > 0")
    if (stop_price % listing.tick) != ZERO:
        raise ExchangeError(422, f"stop_price must be a multiple of tick {listing.tick}")
    if order_type == "limit":
        if price is None or price <= ZERO:
            raise ExchangeError(422, "stop-limit requires a limit price > 0")
        if (price % listing.tick) != ZERO:
            raise ExchangeError(422, f"price must be a multiple of tick {listing.tick}")
    else:
        price = None
    if client_order_id:
        prior = (
            await db.execute(
                select(ExchangeOrder).where(
                    ExchangeOrder.listing_id == listing.id,
                    ExchangeOrder.agent_did == agent_did,
                    ExchangeOrder.client_order_id == client_order_id,
                )
            )
        ).scalars().first()
        if prior:
            return PlacedOrder(order=prior)
    # A stop must arm on the FAR side of `last` (else it triggers instantly = just a normal order):
    # buy-stop ABOVE last (breakout / stop-in), sell-stop BELOW last (stop-loss).
    last = await _last_price(db, listing.id)
    if last is not None:
        if side == "buy" and stop_price <= last:
            raise ExchangeError(422, f"buy-stop stop_price {stop_price} must be ABOVE last {last}")
        if side == "sell" and stop_price >= last:
            raise ExchangeError(422, f"sell-stop stop_price {stop_price} must be BELOW last {last}")
    order = ExchangeOrder(
        listing_id=listing.id, agent_did=agent_did, side=side, order_type=order_type,
        price=price, qty=qty, remaining=qty, client_order_id=client_order_id,
        stop_price=stop_price, tif=(tif or "gtc"), status="armed", escrow_amount=ZERO,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    _emit(
        "ExchangeOrderPlaced", listing.id,
        {"order_id": order.id, "symbol": listing.symbol, "agent_did": agent_did, "side": side,
         "order_type": order_type, "stop_price": str(stop_price),
         "price": str(price) if price is not None else None, "status": "armed"},
        key=f"exchange-order:{order.id}",
    )
    return PlacedOrder(order=order)


async def trigger_armed_stops(db: AsyncSession, batch: int = 100) -> int:
    """§#86 — fire armed stop orders whose stop_price has been crossed by `last`. Called by the
    settlement worker each cycle. Marks the intent 'triggered' FIRST (idempotent — never double-
    fires / retry-storms) then fires a NORMAL place_order (full escrow + match + remainder handling,
    fully reused). Δ-safe (the armed intent moved nothing; place_order is Δ-safe). A trigger on a
    halted/delisted listing is skipped (the order stays armed, re-checked next cycle)."""
    armed = (
        await db.execute(
            select(ExchangeOrder).where(
                ExchangeOrder.status == "armed", ExchangeOrder.stop_price.isnot(None)
            ).limit(batch)
        )
    ).scalars().all()
    n = 0
    for a in armed:
        listing = await _get_listing(db, a.listing_id)
        if listing.status != "trading":
            continue
        last = await _last_price(db, listing.id)
        if last is None:
            continue
        crossed = (a.side == "buy" and last >= a.stop_price) or (a.side == "sell" and last <= a.stop_price)
        if not crossed:
            continue
        a.status = "triggered"  # commit FIRST → idempotent (no double-fire / retry storm)
        await db.commit()
        n += 1
        try:
            await place_order(
                db, agent_did=a.agent_did, listing_ref=a.listing_id, side=a.side,
                order_type=a.order_type, qty=a.remaining, price=a.price,
                client_order_id=f"stoptrig-{a.id}", tif=(a.tif or "gtc"),
            )
            _emit("ExchangeStopTriggered", a.listing_id,
                  {"order_id": a.id, "symbol": listing.symbol, "side": a.side,
                   "stop_price": str(a.stop_price), "last": str(last)},
                  key=f"exchange-stoptrig:{a.id}")
        except Exception as e:  # noqa: BLE001 — already 'triggered' (won't retry); fill best-effort
            try:
                await db.rollback()
            except Exception:
                pass
            logger.warning(f"[stop_trigger] {a.id} fired but place_order failed (band/funds?): {str(e)[:120]}")
    return n


# ── dividends ─────────────────────────────────────────────────────────────
async def declare_dividend(
    db: AsyncSession, developer: Developer, listing_ref: str, per_share: Decimal
) -> ExchangeDividend:
    # §BAFIN (2026-10-01): the share-like feature, switchable per registry (core/agora_gate.py)
    from ..core.agora_gate import distributions_enabled, DISTRIBUTIONS_DISABLED_SENTENCE
    if not distributions_enabled():
        raise ExchangeError(403, DISTRIBUTIONS_DISABLED_SENTENCE)
    await _require_venue_open(db)
    listing = await _get_listing(db, listing_ref)
    has_perm = await OrganizationService.check_member_permission(
        db, listing.organization_id, developer.id, "admin"
    )
    if not has_perm:
        raise ExchangeError(403, "org admin role required to declare distributions")
    if per_share <= ZERO:
        raise ExchangeError(422, "per_share must be > 0")

    await _listing_lock(db, listing.id)
    epoch = (
        (
            await db.execute(
                select(func.coalesce(func.max(ExchangeDividend.epoch), 0)).where(
                    ExchangeDividend.listing_id == listing.id
                )
            )
        ).scalar_one()
        + 1
    )
    snapshot_seq = (
        await db.execute(
            select(func.coalesce(func.max(ExchangeTrade.seq), 0)).where(
                ExchangeTrade.listing_id == listing.id
            )
        )
    ).scalar_one()
    holders = (
        await db.execute(
            select(OrgSharePosition).where(
                OrgSharePosition.listing_id == listing.id, OrgSharePosition.qty > 0
            )
        )
    ).scalars().all()
    # The org doesn't pay itself: treasury position is excluded from the payout.
    holders = [h for h in holders if h.agent_did != listing.treasury_agent_did]
    if not holders:
        raise ExchangeError(409, "no external holders at snapshot")

    div = ExchangeDividend(
        listing_id=listing.id,
        epoch=epoch,
        per_share=per_share,
        snapshot_seq=snapshot_seq,
        declared_by_dev=developer.id,
        status="paying",
    )
    db.add(div)
    await db.flush()
    total = ZERO
    for h in holders:
        amt = q18(per_share * Decimal(h.qty))
        total += amt
        db.add(
            ExchangeDividendLeg(
                dividend_id=div.id, agent_did=h.agent_did, qty_at_snapshot=h.qty, amount=amt
            )
        )
    div.total_amount = q18(total)
    await db.commit()
    await db.refresh(div)
    _emit(
        "ExchangeDividendDeclared",
        listing.id,
        {
            "dividend_id": div.id,
            "symbol": listing.symbol,
            "epoch": str(epoch),
            "per_share": str(per_share),
            "total": str(div.total_amount),
            "holders": str(len(holders)),
        },
        key=f"exchange-div:{div.id}",
    )
    return div


# ── worker drains (called by background_tasks/exchange_settlement.py) ────
async def settle_pending_trades(
    db: AsyncSession, batch: int = SETTLE_BATCH, deadline: Optional[float] = None
) -> Tuple[int, int]:
    """Trade money legs: escrow→seller (notional−fee), escrow→fee_collector,
    escrow→org treasury. All exref-replay-safe; settled only when all legs 200.

    Returns (done, failed). §settlement-resilience (2026-06-13): bounded by an
    optional `deadline` (monotonic secs) so a cycle NEVER outlives the 30s
    leader lease — partial progress is safe (the rest settle next cycle, exref
    idempotent). `failed` lets the worker back off when the TEG is convoyed
    instead of re-hammering the escrow hot row. Each leg uses the short
    SETTLE_LEG_TIMEOUT_S so one stuck leg can't blow the budget."""
    rows = (
        await db.execute(
            select(ExchangeTrade)
            .where(ExchangeTrade.settle_status == "pending_settlement")
            .order_by(ExchangeTrade.created_at.asc())
            .limit(batch)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    done = 0
    failed = 0
    for t in rows:
        if deadline is not None and time.monotonic() > deadline:
            break  # yield the lease before it expires; remaining rows next cycle
        listing = await _get_listing(db, t.listing_id)
        refs: Dict[str, Any] = dict(t.settle_tx_refs or {})
        try:
            pay = q18(t.notional - t.fee_total)
            # §2026-06-20 PASSPORT SELL (bidirectional): a FOREIGN seller has no local
            # balance on this frame — park proceeds on the gateway + register a repat
            # credit; repatriate_gateway_credits drains it home (reverse FX, auto at the
            # /teg/send edge). Mirrors the proven dividend/refund repat path. Δ-safe (one
            # escrow→gateway move + the home send is the credit's own leg). Locals settle
            # frame-local as before. `_foreign_home` is None for locals/unknown DIDs.
            _seller_home = await _foreign_home(db, t.seller_did)
            if _seller_home:
                r1 = await mover.move(EXCHANGE_ESCROW_SENTINEL, GATEWAY_DID, pay, "trade_payout_passport", f"trd-{t.id}:pay", timeout_s=SETTLE_LEG_TIMEOUT_S)
                await _add_gateway_credit(db, t.seller_did, _seller_home, pay, "passport_sell", f"trd-{t.id}:pay")
            else:
                r1 = await mover.move(EXCHANGE_ESCROW_SENTINEL, t.seller_did, pay, "trade_payout", f"trd-{t.id}:pay", timeout_s=SETTLE_LEG_TIMEOUT_S)
            refs["pay"] = r1.get("transaction_id")
            if t.fee_proto > ZERO:
                r2 = await mover.move(EXCHANGE_ESCROW_SENTINEL, FEE_COLLECTOR_SENTINEL, t.fee_proto, "trade_fee_proto", f"trd-{t.id}:feep", timeout_s=SETTLE_LEG_TIMEOUT_S)
                refs["feep"] = r2.get("transaction_id")
            if t.fee_org > ZERO:
                r3 = await mover.move(EXCHANGE_ESCROW_SENTINEL, listing.treasury_agent_did, t.fee_org, "trade_fee_org", f"trd-{t.id}:feeo", timeout_s=SETTLE_LEG_TIMEOUT_S)
                refs["feeo"] = r3.get("transaction_id")
            # §2026-06-22 P2.2 maker rebate leg — the 4th escrow→ leg, carved from fee_proto
            # at match (so pay+feep+feeo+rebate == notional → escrow nets to 0, I-X3
            # unchanged). FOREIGN maker: park on the gateway + register a repat credit (the
            # proven passport path, drained by repatriate_gateway_credits). Idempotent on
            # the trd-{id}:rebate key. fee_maker_rebate is 0 for all pre-P2.2 / flag-off
            # trades, so this branch is inert by default.
            _rebate = getattr(t, "fee_maker_rebate", ZERO) or ZERO
            _maker = getattr(t, "maker_did", None)
            if _rebate > ZERO and _maker:
                _maker_home = await _foreign_home(db, _maker)
                if _maker_home:
                    r4 = await mover.move(EXCHANGE_ESCROW_SENTINEL, GATEWAY_DID, _rebate, "trade_maker_rebate_passport", f"trd-{t.id}:rebate", timeout_s=SETTLE_LEG_TIMEOUT_S)
                    await _add_gateway_credit(db, _maker, _maker_home, _rebate, "maker_rebate", f"trd-{t.id}:rebate")
                else:
                    r4 = await mover.move(EXCHANGE_ESCROW_SENTINEL, _maker, _rebate, "trade_maker_rebate", f"trd-{t.id}:rebate", timeout_s=SETTLE_LEG_TIMEOUT_S)
                refs["rebate"] = r4.get("transaction_id")
            t.settle_tx_refs = refs
            t.settle_status = "settled"
            t.settled_at = datetime.now(timezone.utc)
            done += 1
            # §NOTIFV2 exchange.order_filled — wired at SETTLEMENT, not at the matcher. The
            # matcher flips `order.status='filled'` before any money has moved; a trade that
            # matches but fails to settle would otherwise notify a fill that never paid. Both
            # sides are told. Opt-in only with a 300s coalesce window, because an active trader
            # (or the sim) fills constantly — this is the noisiest type in the catalog.
            try:
                import asyncio as _aio_n
                from agentvault_registry.background_tasks.push_notify import notify_agent_owners
                _sides = [d for d in (t.buyer_did, t.seller_did) if d]
                if _sides:
                    _aio_n.create_task(notify_agent_owners(
                        "exchange.order_filled", _sides,
                        title="Order filled",
                        message=f"{t.qty} @ {t.price} settled.",
                        tags="chart_with_upwards_trend", priority="default",
                        click="/ui/#/agora"))
            except Exception as ne_:  # noqa: BLE001 — §S4 pass 4: a filled-order notification that never leaves is a WARNING, not a debug line
                logger.warning("[NOTIFY] exchange.order_filled emit failed for trade %s: %s: %s", getattr(t, "id", "?"), ne_.__class__.__name__, str(ne_)[:120])
        except ExchangeError as e:
            t.settle_attempts += 1
            t.settle_tx_refs = refs
            failed += 1
            logger.warning(f"[AGORA] trade {t.id} settle attempt {t.settle_attempts} failed: {e.detail}")
        await db.commit()
    return done, failed


# ── §V0064 P2 — Passport repatriation (AGORA_Exchange.md §10) ─────────────
async def _foreign_home(db: AsyncSession, did: str) -> Optional[str]:
    """The home registry of a FOREIGN participant with a KNOWN home, else None
    (locals + unknown DIDs settle frame-local as before).

    GA5 (2026-07-24): the dev_card gate is gone — any participant whose
    home_registry is known and non-local repatriates. Requiring dev_card paid
    dividends/rebates for otherwise-known foreign holders into unreachable
    frame-local balances (the §V0121 dead-slug class). Locals can't match:
    ensure_participant pins them to home_registry='local'."""
    p = (
        await db.execute(select(ExchangeParticipant).where(ExchangeParticipant.agent_did == did))
    ).scalar_one_or_none()
    if p and p.home_registry and p.home_registry not in ("local", "unknown"):
        return p.home_registry
    return None


async def _add_gateway_credit(
    db: AsyncSession, did: str, home: str, amount: Decimal, origin: str, ref: str
) -> None:
    """Idempotent (ref-unique) attributed credit; raw INSERT ON CONFLICT so a
    crash-rerun after the mover replay never double-credits."""
    await db.execute(
        text(
            "INSERT INTO exchange_gateway_credits (did, home_registry, currency, amount, origin, ref)"
            " VALUES (:did, :home, :ccy, :amt, :origin, :ref) ON CONFLICT (ref) DO NOTHING"
        ),
        {"did": did, "home": home, "ccy": os.getenv("FRAME_CURRENCY", "AVT"),
         "amt": str(q18(amount)), "origin": origin, "ref": ref},
    )


def _repat_key(credit_id: Any) -> str:
    """The per-credit pass's Idempotency-Key for one credit (stable for the credit's whole life)."""
    return f"repat-{credit_id}"


def _repat_bucket_key(ids: List[int]) -> str:
    """The aggregated pass's Idempotency-Key for one bundle: derived from the exact id set."""
    import hashlib as _hl
    return "repagg-" + _hl.sha1("|".join(str(i) for i in ids).encode()).hexdigest()[:20]


async def _apply_claimed(db: AsyncSession, ids: List[int], status: str, claim: str, sets: str,
                         params: Optional[Dict[str, Any]] = None) -> int:
    """One write after a send, landing ONLY on the rows this pass claimed: their status is still the claim's and their
    tx_ref is still the claim's own (it carries the pass's nonce). A write that finds nothing lost to an answer another
    pass applied in the meantime, and is never applied over it."""
    r = await db.execute(text(f"UPDATE exchange_gateway_credits SET {sets}"
                              " WHERE id = ANY(:ids) AND status=:claim_status AND tx_ref=:claim"),
                         {**(params or {}), "ids": ids, "claim_status": status, "claim": claim})
    return int(r.rowcount or 0)


async def _hold_rows(db: AsyncSession, ids: List[int], key: str, reason: str, *, status: str, claim: str) -> int:
    """Mark claimed credits 'unresolved' (never sent again on their own)."""
    return await _apply_claimed(db, ids, status, claim, "status='unresolved', tx_ref=:tr",
                                {"tr": payout_outcome.hold_ref(key, reason)})


async def _mark_paid_rows(db: AsyncSession, ids: List[int], tx_ref: str, *, status: str, claim: str) -> int:
    return await _apply_claimed(db, ids, status, claim, "status='paid', paid_at=now(), tx_ref=:tr", {"tr": tx_ref[:128]})


# §REPATLANE: every attempt V0603 makes leaves its mark (tx_ref RETRY_PREFIX, payout_outcome.retry_ref), so a credit with
# attempts or re-arms and no mark is one the lane before V0603 attempted. Only an unmarked-and-unattempted credit or a
# marked one may be sent, re-armed or bundled.
_SENDABLE_SQL = "((attempts = 0 AND rearm_count = 0) OR tx_ref LIKE :retry_mark)"
_RETRY_MARK = payout_outcome.RETRY_PREFIX + "%"
# A claim older than this belongs to a pass that died or raised (a live pass sends within the 45 s client timeout per
# credit: at most 5 rounds of 4 on the per-credit pass, 8 bundles one by one on the aggregated one).
REPAT_CLAIM_STALE_S = int(os.getenv("EXCHANGE_REPAT_CLAIM_STALE_SEC", "900"))
# the epoch in a claim's or a hold's tx_ref ("key|why|epoch"), cast inside a CASE: Postgres does not promise to test the
# regex before the cast in an AND. A tx_ref without one (a claim the lane before V0603 made) reads as 0.
_REF_EPOCH_SQL = ("CASE WHEN split_part(tx_ref, '|', 3) ~ '^[0-9]{1,12}$'"
                  " THEN split_part(tx_ref, '|', 3)::bigint ELSE 0 END")


async def _hold_legacy_attempted(db: AsyncSession) -> int:
    """§REPATLANE: a credit the lane before V0603 attempted and did not pay may already have reached its trader. That lane
    counted every non-200 answer as one more attempt (stranded FX routes among them), wrote 'failed' after six, and the
    keeper's recon re-armed 'failed' credits to attempts 0 (rearm_count shows it). Such a credit ('pending' or 'failed'
    with attempts or re-arms and no RETRY_PREFIX mark) holds for a ledger read instead of being sent again."""
    r = await db.execute(text(
        "UPDATE exchange_gateway_credits SET status='unresolved', tx_ref=:tr"
        " WHERE status IN ('pending', 'failed') AND (attempts > 0 OR rearm_count > 0)"
        " AND (tx_ref IS NULL OR tx_ref NOT LIKE :retry_mark)"),
        {"tr": payout_outcome.hold_ref("", "attempted by the lane before V0603"), "retry_mark": _RETRY_MARK})
    n = int(r.rowcount or 0)
    if n:
        await db.commit()
        agora_repat_outcome("legacy", payout_outcome.HOLD, n)
        logger.warning(
            "[AGORA-repat] %d credit(s) were attempted by the lane before V0603 and not paid: held as 'unresolved' "
            "(their attempts may include a payout that moved). Read the ledger for each before releasing it (status "
            "'pending', attempts 0, rearm_count 0, tx_ref NULL) or marking it 'paid'.", n)
    return n


async def _settle_from_store(db: AsyncSession) -> int:
    """§REPATLANE: two kinds of credit are settled by READING the registry's idempotency store, never by a send.

    1. A claim older than REPAT_CLAIM_STALE_S (status 'sending' or 'batched': its pass died or raised before applying
       the answer, or it is a claim the lane before V0603 left). Sending it again could pay twice, so: a stored success
       is paid; anything else (nothing stored, a non-success, a claim still held at the server, a store that cannot be
       read) holds it ('unresolved').
    2. A held credit ('unresolved') whose key the store, within its TTL, shows answered with a success: paid. Newest
       holds first.
    Every write lands only on the rows as they were read (status and tx_ref). Returns how many credits were paid."""
    from agentvault_registry.services.idempotency.cache import IDEMPOTENCY_TTL_SECONDS, agent_caller
    paid = 0
    now = int(time.time())
    # D6-777: the store keeps a send's record as the gateway's (the lane sends as GATEWAY_DID); a record of the key from
    # before records were the caller's is nobody's answer here ("unmatched": the credit holds)
    lane = (agent_caller(GATEWAY_DID),)
    groups = (await db.execute(text(
        "SELECT status, tx_ref, array_agg(id ORDER BY id) ids FROM exchange_gateway_credits"
        " WHERE status IN ('sending', 'batched') AND tx_ref IS NOT NULL AND " + _REF_EPOCH_SQL + " < :stale"
        " GROUP BY status, tx_ref ORDER BY min(id) LIMIT 100"), {"stale": now - REPAT_CLAIM_STALE_S})).all()
    for g in groups:
        ref, ids, st = str(g.tx_ref), list(g.ids), str(g.status)
        key = payout_outcome.parse_hold_ref(ref)[0] or ref  # a claim the lane before V0603 made is the bare key
        state, ans = await payout_outcome.stored_answer(key, callers=lane)
        o = payout_outcome.classify_stored(ans) if state == "stored" else None
        if o is not None and o.kind == payout_outcome.PAID:
            n = await _mark_paid_rows(db, ids, (o.tx or key) if st == REPAT_SENDING else f"{key}:{o.tx}",
                                      status=st, claim=ref)
            paid += n
            agora_repat_outcome("store", payout_outcome.PAID, n)
            logger.info(f"[AGORA-repat] {n} credit(s) under {key}: the store holds a success for a send whose "
                        f"answer was never applied: paid ({o.tx})")
        else:
            why = {"stored": f"unanswered send, stored {o.reason if o else '?'}",
                   "held": "unanswered send, the store keeps its held answer",
                   "none": "unanswered send, nothing stored",
                   "claimed": "unanswered send, still claimed at the server",
                   "unmatched": "unanswered send, the store holds a record from before keys were kept per caller",
                   "unknown": "unanswered send, the store could not be read"}.get(state, f"unanswered send, {state}")
            n = await _hold_rows(db, ids, key, why, status=st, claim=ref)
            if n:
                agora_repat_outcome("store", payout_outcome.HOLD, n)
                logger.warning(
                    f"[AGORA-repat] {n} credit(s) under {key} held as 'unresolved': a send whose answer this lane never "
                    f"applied ({why}); it may have moved. Read the ledger for {key} before releasing it.")
        await db.commit()
    held = (await db.execute(text(
        "SELECT tx_ref, array_agg(id ORDER BY id) ids FROM exchange_gateway_credits"
        " WHERE status='unresolved' AND split_part(tx_ref, '|', 1) <> '' AND " + _REF_EPOCH_SQL + " >= :cutoff"
        " GROUP BY tx_ref ORDER BY " + _REF_EPOCH_SQL + " DESC LIMIT 500"),
        {"cutoff": now - IDEMPOTENCY_TTL_SECONDS})).all()
    for h in held:
        key, _why, _at = payout_outcome.parse_hold_ref(h.tx_ref)
        if not key:
            continue
        state, ans = await payout_outcome.stored_answer(key, callers=lane)
        if state != "stored":
            continue
        o = payout_outcome.classify_stored(ans)
        if o.kind != payout_outcome.PAID:
            continue
        ids = list(h.ids)
        n = await _mark_paid_rows(db, ids, (o.tx or key) if key.startswith("repat-") else f"{key}:{o.tx}",
                                  status=REPAT_UNRESOLVED, claim=str(h.tx_ref))
        await db.commit()
        paid += n
        agora_repat_outcome("store", payout_outcome.PAID, n)
        logger.info(f"[AGORA-repat] {n} held credit(s) under {key}: the store holds a success: paid ({o.tx})")
    return paid


async def repatriate_gateway_credits(db: AsyncSession, batch: int = 20) -> int:
    """Batch I: drain pending foreign credits home — gateway agent sends via
    /teg/send (smart send: local / cross-registry / auto-FX picked at the edge),
    Idempotency-Key `repat-{id}`. Money stays on the gateway (safe, I-X5-accounted)
    until a send succeeds.

    §REPATLANE (V0603): each credit is claimed ('sending', tx_ref = the key, this pass's nonce and the time) before its
    send, and every answer is read by services/payout_outcome.classify and written only onto that claim: paid; retry
    (nothing reached the trader: one attempt, the RETRY_PREFIX mark, 'failed' at the limit so the keeper's recon can
    re-arm it); wait and sender_refused (no attempt, the credit as it was); hold ('unresolved', never sent again on its
    own). A retry is the only path that sends again, and it needs proof: the registry stores only a success under a
    key, so a send that failed AFTER money moved ran again under the same key once its claim expired (measured: 14
    traders paid twice on the sandbox in three weeks)."""
    await _ensure_gateway_role_once(db)
    await _hold_legacy_attempted(db)
    done = await _settle_from_store(db)
    rows = (
        await db.execute(
            select(ExchangeGatewayCredit)
            .where(
                ExchangeGatewayCredit.status == "pending",
                ExchangeGatewayCredit.amount >= REPAT_DUST,
                ExchangeGatewayCredit.attempts < REPAT_MAX_ATTEMPTS,
                or_(and_(ExchangeGatewayCredit.attempts == 0, ExchangeGatewayCredit.rearm_count == 0),
                    ExchangeGatewayCredit.tx_ref.like(_RETRY_MARK)),
            )
            .order_by(ExchangeGatewayCredit.created_at.asc())
            .limit(batch)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    if not rows:
        return done
    gw = (await db.execute(select(Agent).where(Agent.did == GATEWAY_DID))).scalar_one_or_none()
    if gw is None:
        return done
    from datetime import timedelta as _td

    from agentvault_registry.security import create_access_token

    jwt = create_access_token(
        # L3 — the registry mints AS the gateway to repatriate; the act claim records
        # that this token acts on the platform's behalf (attribution, not extra authority).
        {"sub": GATEWAY_DID, "type": "agent", "agent_id": str(gw.id),
         "act": {"sub": "service:exchange-gateway", "reason": "repatriation"}},
        expires_delta=_td(minutes=10),
    )
    # §REPATLANE: the claim is committed BEFORE any send, so a send whose answer is never applied (a crash, a recreate,
    # an error below) is found by _settle_from_store once it is stale instead of being sent again. The claim's tx_ref
    # carries this pass's nonce: every write below lands only on this pass's own claim.
    nonce, claimed_at = payout_outcome.claim_nonce(), time.time()
    prior: Dict[int, Optional[str]] = {}
    claims: Dict[int, str] = {}
    for cr in rows:
        prior[cr.id] = cr.tx_ref
        claims[cr.id] = payout_outcome.claim_ref(_repat_key(cr.id), nonce, claimed_at)
        cr.status = REPAT_SENDING
        cr.tx_ref = claims[cr.id]
    await db.commit()
    # §2026-06-20 V0117 CONCURRENT drain (was sequential one-at-a-time). Each credit is an
    # INDEPENDENT, idempotent (Idempotency-Key repat-{id}) gateway→home send; the gateway is
    # kept solvent by the float keeper and the TEG serialises the actual balance debits, so
    # firing a bounded batch concurrently is safe and lifts throughput from Σ(send) to
    # ~ceil(N/conc)·send. Bounded by a small semaphore (+ the server-side FX_ROUTE_MAX_CONCURRENCY)
    # so it never stampedes the FX rail. 45s (was 25s) so a slow cross-frame FX leg finishes
    # WITHIN the call; a send that still times out is held (payout_outcome: the server may still be moving it), and a
    # success the server stores later marks it paid (_settle_from_store).
    _conc = max(1, int(os.getenv("EXCHANGE_REPAT_CONCURRENCY", "4")))  # §V0118 8→4: 8 saturated the shared /teg/send path (503s); 4 still 4× the old sequential drain (which already outpaces creation), gentle on /teg/send.
    _sem = asyncio.Semaphore(_conc)
    async with httpx.AsyncClient(timeout=45.0) as c:
        async def _send_one(cr):
            async with _sem:
                try:
                    r = await c.post(
                        "http://localhost:8000/api/v1/teg/send",
                        json={
                            "receiver_did": cr.did,
                            "amount": str(q18(cr.amount)),
                            "message": f"AGORA repatriation ({cr.origin}) ref {cr.ref}",
                        },
                        headers={"Authorization": f"Bearer {jwt}", "Idempotency-Key": _repat_key(cr.id)},
                    )
                    return cr, r, None
                except httpx.HTTPError as e:
                    return cr, None, e
        results = await asyncio.gather(*[_send_one(cr) for cr in rows])
        # Apply results single-threaded (no concurrent ORM mutation) → one commit.
        perm_refused: Dict[str, int] = {}
        for cr, r, err in results:
            o = payout_outcome.classify(r, err)
            agora_repat_outcome("credit", o.kind)
            said = f"send {r.status_code}: {r.text[:120]}" if r is not None else f"transport: {err!r}"[:140]
            key, claim = _repat_key(cr.id), claims[cr.id]
            if o.kind == payout_outcome.PAID:
                n = await _mark_paid_rows(db, [cr.id], o.tx or key, status=REPAT_SENDING, claim=claim)
                done += n
                if n:
                    logger.info(f"[AGORA-repat] credit {cr.id} → {cr.did} ({cr.amount} {cr.currency}) sent")
            elif o.kind == payout_outcome.SENDER_REFUSED:
                # §GATEWAYROLE: the SENDER is not allowed; every credit meets the same wall. Not a delivery attempt.
                _perm = _permission_refused(r) or "?"
                perm_refused[_perm] = perm_refused.get(_perm, 0) + 1
                n = await _apply_claimed(db, [cr.id], REPAT_SENDING, claim, "status='pending', tx_ref=:tr",
                                         {"tr": prior[cr.id]})
            elif o.kind == payout_outcome.WAIT:
                # An earlier send under this key is still claimed at the server: no attempt; a later pass sends the
                # same key again and gets its stored answer, or runs it once the claim has expired.
                n = await _apply_claimed(db, [cr.id], REPAT_SENDING, claim, "status='pending', tx_ref=:tr",
                                         {"tr": prior[cr.id]})
                logger.debug(f"[AGORA-repat] credit {cr.id} waits: {o.reason}")
            elif o.kind == payout_outcome.RETRY:
                n = await _apply_claimed(
                    db, [cr.id], REPAT_SENDING, claim,
                    "attempts=attempts+1, tx_ref=:tr, status=CASE WHEN attempts + 1 >= :ma THEN 'failed' ELSE 'pending' END",
                    {"tr": payout_outcome.retry_ref(o.reason), "ma": REPAT_MAX_ATTEMPTS})
                logger.warning(f"[AGORA-repat] credit {cr.id} {said} (attempt {cr.attempts + 1}; nothing reached the "
                               f"trader: {o.reason})")
            else:
                n = await _hold_rows(db, [cr.id], key, o.reason, status=REPAT_SENDING, claim=claim)
                logger.warning(
                    f"[AGORA-repat] credit {cr.id} → {cr.did} ({cr.amount} {cr.currency}) HELD as 'unresolved', money "
                    f"may have moved ({o.reason}{', route ' + o.tx if o.tx else ''}): {said}. It is never sent again "
                    f"on its own: read the ledger for {key} before releasing it.")
            if not n:
                logger.warning(f"[AGORA-repat] credit {cr.id}: its claim was settled by another pass while its send "
                               f"ran, so this answer ({o.kind}: {o.reason}) was not applied over it")
        if perm_refused:
            logger.warning(
                "[AGORA-repat] IRONKEY refused the gateway %s (%s): %d credit(s) wait, attempts not counted; "
                "the gateway needs its role (§GATEWAYROLE)",
                GATEWAY_DID, ", ".join(sorted(perm_refused)), sum(perm_refused.values()))
        await db.commit()
    return done


async def repatriate_gateway_credits_aggregated(db: AsyncSession, bucket_batch: int = 8) -> int:
    """§CHATDESK C5b (§REPATAGG) — batch I for the FRAGMENTS.

    The per-credit sender deliberately skips credits below REPAT_DUST (a
    0.0002 BVT cross-frame send is not worth its FX legs) — which meant a
    foreign holder's DIVIDENDS, paid as many small legs, were structurally
    never delivered: measured 2026-08-28, 89.68 BVT of dividend credits and
    ~4.3K BVT of fragments overall sat terminally 'abandoned' on the gateway.
    The economics change when you SUM per holder: this pass groups pending
    sub-dust credits by (did, home), and once a holder's bucket clears the
    dust floor it goes home as ONE smart-send (auto-FX at the edge, same as
    every other repat).

    Idempotency is the whole design (the org_treasury doctrine — the key is
    deterministic and CLAIMED before the send):
      * a bucket is claimed by flipping its rows pending→'batched' with a tx_ref that names the key (derived from the
        exact id set), this pass's nonce and the time; the claim reports the rows it took (RETURNING), and a bundle
        that changed underneath is released row by row, only the rows this pass took;
      * the send carries the key as its Idempotency-Key;
      * §REPATLANE (V0603): every write after the send lands only on this pass's claim; a claim left behind (a pass
        that died or raised) is settled by reading the store once it is stale (_settle_from_store), never sent again
        (the store keeps only a success, so a send that failed after money moved would run again under the same key).
    Every answer is read by services/payout_outcome.classify: a retry (nothing reached the trader) reverts the rows to
    'pending' with attempts+1, the RETRY_PREFIX mark and 'failed' at the limit, so the failed→recon→abandoned ladder
    bounds a genuinely dead receiver; a wait or a sender refusal reverts them without an attempt; a hold marks them
    'unresolved'.
    """
    await _ensure_gateway_role_once(db)
    await _hold_legacy_attempted(db)
    done = await _settle_from_store(db)
    perm_refused: Dict[str, int] = {}
    gw = (await db.execute(select(Agent).where(Agent.did == GATEWAY_DID))).scalar_one_or_none()
    if gw is None:
        return done
    from datetime import timedelta as _td

    from agentvault_registry.security import create_access_token

    jwt = create_access_token(
        {"sub": GATEWAY_DID, "type": "agent", "agent_id": str(gw.id),
         "act": {"sub": "service:exchange-gateway", "reason": "repatriation-agg"}},
        expires_delta=_td(minutes=10),
    )
    nonce = payout_outcome.claim_nonce()
    # a bundle's rows return to 'pending' with no attempt; a row attempted before keeps a RETRY_PREFIX mark
    _RELEASE = "status='pending', tx_ref=CASE WHEN attempts > 0 OR rearm_count > 0 THEN :tr ELSE NULL END"

    async def _send_group(c, key: str, claim: str, did: str, total: Decimal, ids: list) -> bool:
        r, err = None, None
        try:
            r = await c.post(
                "http://localhost:8000/api/v1/teg/send",
                json={"receiver_did": did, "amount": str(q18(total)),
                      "message": f"AGORA repatriation (aggregated x{len(ids)})"},
                headers={"Authorization": f"Bearer {jwt}", "Idempotency-Key": key},
            )
        except httpx.HTTPError as e:
            err = e
        o = payout_outcome.classify(r, err)
        agora_repat_outcome("bundle", o.kind, len(ids))
        said = f"send {r.status_code}: {r.text[:120]}" if r is not None else f"transport: {err!r}"[:140]
        if o.kind == payout_outcome.PAID:
            n = await _mark_paid_rows(db, ids, f"{key}:{o.tx[:80]}", status=REPAT_BATCHED, claim=claim)
        elif o.kind in (payout_outcome.WAIT, payout_outcome.SENDER_REFUSED):
            # no attempt: a wait is an earlier send's claim; a refusal is the §GATEWAYROLE wall the SENDER meets
            n = await _apply_claimed(db, ids, REPAT_BATCHED, claim, _RELEASE,
                                     {"tr": payout_outcome.retry_ref(f"released: {o.reason}")})
            if o.kind == payout_outcome.SENDER_REFUSED:
                _perm = _permission_refused(r) or "?"
                perm_refused[_perm] = perm_refused.get(_perm, 0) + len(ids)
        elif o.kind == payout_outcome.RETRY:
            n = await _apply_claimed(
                db, ids, REPAT_BATCHED, claim,
                "attempts=attempts+1, tx_ref=:tr, status=CASE WHEN attempts + 1 >= :ma THEN 'failed' ELSE 'pending' END",
                {"tr": payout_outcome.retry_ref(o.reason), "ma": REPAT_MAX_ATTEMPTS})
            logger.warning(f"[AGORA-repat-agg] bucket {key} {said} (nothing reached the trader: {o.reason})")
        else:
            n = await _hold_rows(db, ids, key, o.reason, status=REPAT_BATCHED, claim=claim)
            logger.warning(
                f"[AGORA-repat-agg] bucket {key} ({len(ids)} credits → {did}, {q18(total)}) HELD as 'unresolved', money "
                f"may have moved ({o.reason}{', route ' + o.tx if o.tx else ''}): {said}. Never sent again on its own: "
                f"read the ledger for {key} before releasing it.")
        await db.commit()
        if n != len(ids):
            logger.warning(f"[AGORA-repat-agg] bucket {key}: {len(ids) - n} of its {len(ids)} rows were settled by "
                           f"another pass while its send ran, so this answer ({o.kind}: {o.reason}) was not applied "
                           f"over them")
        if o.kind == payout_outcome.PAID:
            logger.info(f"[AGORA-repat-agg] {n} credits → {did} ({q18(total)}) sent as {key}")
            return True
        return False

    async with httpx.AsyncClient(timeout=45.0) as c:
        # New buckets: pending sub-dust, grouped per holder, floor-clearing.
        buckets = (await db.execute(text(
            "SELECT did, home_registry, array_agg(id ORDER BY id) ids, sum(amount) total"
            " FROM exchange_gateway_credits"
            " WHERE status='pending' AND amount < :dust AND attempts < :ma AND " + _SENDABLE_SQL +
            " GROUP BY did, home_registry HAVING sum(amount) >= :dust"
            " ORDER BY sum(amount) DESC LIMIT :b"),
            {"dust": str(REPAT_DUST), "ma": REPAT_MAX_ATTEMPTS, "b": bucket_batch,
             "retry_mark": _RETRY_MARK})).all()
        for row in buckets:
            ids = list(row.ids)
            key = _repat_bucket_key(ids)
            claim = payout_outcome.claim_ref(key, nonce)
            took = sorted(int(i) for i in (await db.execute(text(
                "UPDATE exchange_gateway_credits SET status='batched', tx_ref=:claim"
                " WHERE id = ANY(:ids) AND status='pending' AND amount < :dust AND attempts < :ma AND " + _SENDABLE_SQL +
                " RETURNING id"),
                {"claim": claim, "ids": ids, "dust": str(REPAT_DUST), "ma": REPAT_MAX_ATTEMPTS,
                 "retry_mark": _RETRY_MARK})).scalars().all())
            await db.commit()
            if took != ids:
                # Part of the set moved under us: release exactly the rows THIS claim took and skip; the next cycle
                # re-buckets from live truth.
                if took:
                    await _apply_claimed(db, took, REPAT_BATCHED, claim, _RELEASE,
                                         {"tr": payout_outcome.retry_ref("released: the bundle changed")})
                    await db.commit()
                continue
            if await _send_group(c, key, claim, row.did, Decimal(str(row.total)), ids):
                done += len(ids)
    if perm_refused:
        logger.warning(
            "[AGORA-repat-agg] IRONKEY refused the gateway %s (%s): %d credit(s) wait, attempts not counted; "
            "the gateway needs its role (§GATEWAYROLE)",
            GATEWAY_DID, ", ".join(sorted(perm_refused)), sum(perm_refused.values()))
    return done


async def refund_terminal_buys(db: AsyncSession, batch: int = 50) -> int:
    """Residual escrow on terminal BUY orders → buyer. held = escrow − matched − refunded."""
    rows = (
        await db.execute(
            select(ExchangeOrder)
            .where(
                ExchangeOrder.side == "buy",
                ExchangeOrder.status.in_(("cancelled", "expired", "filled")),
                ExchangeOrder.escrow_amount
                > (ExchangeOrder.matched_notional + ExchangeOrder.escrow_refunded),
            )
            .order_by(ExchangeOrder.updated_at.asc())
            .limit(batch)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    done = 0
    for o in rows:
        held = q18(o.escrow_amount - o.matched_notional - o.escrow_refunded)
        if held <= ZERO:
            continue
        try:
            # §V0064 P2 repatriation: FOREIGN buyer's residue parks on the
            # GATEWAY as an attributed credit; batch I sends it home (auto-FX).
            home = await _foreign_home(db, o.agent_did)
            if home:
                await mover.move(EXCHANGE_ESCROW_SENTINEL, GATEWAY_DID, held, "order_refund_park", f"ord-{o.id}:refpark")
                await _add_gateway_credit(db, o.agent_did, home, held, "refund", f"refund-{o.id}")
            else:
                await mover.move(EXCHANGE_ESCROW_SENTINEL, o.agent_did, held, "order_refund", f"ord-{o.id}:ref1")
            o.escrow_refunded = q18(o.escrow_refunded + held)
            done += 1
        except ExchangeError as e:
            logger.warning(f"[AGORA] refund for order {o.id} failed: {e.detail}")
        await db.commit()
    return done


async def sweep_funding_orders(db: AsyncSession, batch: int = 50) -> int:
    """Orders stuck in 'funding' (crash between deposit and open): re-fire the
    deposit (replay no-op) then open+match under the lock."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=FUNDING_RETRY_AFTER_SEC)
    rows = (
        await db.execute(
            select(ExchangeOrder)
            .where(
                ExchangeOrder.status == "funding",
                ExchangeOrder.created_at < cutoff,
                # Passport (foreign) orders are funded gateway→escrow by the
                # passport sweeper, NOT buyer→escrow — the foreign buyer has no
                # local balance. Excluding them here stops this sweeper from
                # wrongly rejecting them. (AGORA Passport, 2026-06-12.)
                or_(
                    ExchangeOrder.client_order_id.is_(None),
                    ~ExchangeOrder.client_order_id.like("passport:%"),
                ),
            )
            .order_by(ExchangeOrder.created_at.asc())
            .limit(batch)
        )
    ).scalars().all()
    done = 0
    for o in rows:
        listing = (
            await db.execute(select(ExchangeListing).where(ExchangeListing.id == o.listing_id))
        ).scalar_one()
        try:
            await mover.move(o.agent_did, EXCHANGE_ESCROW_SENTINEL, o.escrow_amount, "order_deposit", f"ord-{o.id}:dep")
        except MoverError as e:
            o.status = "rejected"
            o.reject_reason = f"deposit failed: {e.detail}"[:255]
            await db.commit()
            continue
        await _listing_lock(db, o.listing_id)
        await db.refresh(o)
        if o.status != "funding":
            await db.commit()
            continue
        if listing.status != "trading":
            o.status = "cancelled"
            o.reject_reason = "listing not trading at funding completion"
            await db.commit()
            continue
        o.status = "open"
        cap = o.price if o.price is not None else o.escrow_amount / Decimal(o.qty)
        fills = await _match(db, listing, o, taker_cap=cap)
        await db.commit()
        for t in fills:
            _emit(
                "ExchangeTradeExecuted",
                listing.id,
                {
                    "trade_id": t.id, "seq": str(t.seq), "symbol": listing.symbol,
                    "price": str(t.price), "qty": str(t.qty), "notional": str(t.notional),
                    "buyer_did": t.buyer_did, "seller_did": t.seller_did, "currency": listing.currency,
                },
                key=f"exchange-trade:{t.id}",
            )
        done += 1
    return done


async def sweep_funding_ipo(db: AsyncSession, batch: int = 50) -> int:
    """IPO purchases stuck in 'funding' (crash between the deposit leg and the
    allocate-or-refund commit — e.g. a client disconnect cancels ipo_buy after
    the deposit landed): re-fire the deposit (exref replay no-op) then run the
    same allocate-or-refund tail as ipo_buy. Money is never stranded in escrow
    (§2026-07-02, frame-b I-X3 +6.25 trace). No passport exclusion needed —
    IPO purchases are always funded local buyer → escrow."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=FUNDING_RETRY_AFTER_SEC)
    rows = (
        await db.execute(
            select(ExchangeIpoPurchase)
            .where(
                ExchangeIpoPurchase.status == "funding",
                ExchangeIpoPurchase.created_at < cutoff,
            )
            .order_by(ExchangeIpoPurchase.created_at.asc())
            .limit(batch)
        )
    ).scalars().all()
    done = 0
    for p in rows:
        listing = (
            await db.execute(select(ExchangeListing).where(ExchangeListing.id == p.listing_id))
        ).scalar_one()
        try:
            await mover.move(p.agent_did, EXCHANGE_ESCROW_SENTINEL, p.amount, "ipo_deposit", f"ipo-{p.id}:dep")
        except MoverError as e:
            p.status = "rejected"
            await db.commit()
            logger.warning(f"[AGORA] ipo funding sweep: {p.id} deposit replay failed → rejected: {e.detail}")
            continue
        await _listing_lock(db, p.listing_id)
        await db.refresh(p)
        if p.status != "funding":  # raced by ipo_buy's own tail
            await db.commit()
            continue
        await db.refresh(listing)
        if listing.ipo_sold + p.qty <= listing.ipo_float and listing.status != "delisted":
            listing.ipo_sold += p.qty
            pos = await _get_or_create_position(db, listing.id, p.agent_did)
            _update_avg_cost(pos, p.qty, listing.ipo_price)
            pos.qty += p.qty
            p.status = "allocated"
        else:
            p.status = "refunding"  # worker refunds the deposit
        await db.commit()
        logger.info(f"[AGORA] ipo funding sweep: {p.id} → {p.status}")
        done += 1
    return done


async def expire_ttl_orders(db: AsyncSession, batch: int = 100) -> int:
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(ExchangeOrder)
            .where(
                ExchangeOrder.status.in_(("open", "partial")),
                ExchangeOrder.ttl_expires_at.is_not(None),
                ExchangeOrder.ttl_expires_at < now,
            )
            .limit(batch)
        )
    ).scalars().all()
    done = 0
    for o in rows:
        await _listing_lock(db, o.listing_id)
        await db.refresh(o)
        if o.status not in ("open", "partial"):
            await db.commit()
            continue
        if o.side == "sell":
            pos = await _get_or_create_position(db, o.listing_id, o.agent_did)
            pos.locked_qty = max(0, pos.locked_qty - o.remaining)
        o.status = "expired"
        await db.commit()
        done += 1
    return done


async def expire_stale_orders(db: AsyncSession, batch: int = 100) -> int:
    """§2026-06-24 — durable stale-order sweep. Force-expires resting (open/partial) orders older
    than a configured max-age REGARDLESS of ttl_expires_at/tif, then lets the existing pipeline
    refund them. Closes the GTC-passport leak: foreign passport BUYs are GTC (ttl_expires_at NULL)
    AND un-owner-cancellable (the foreign JWT can't auth locally), so expire_ttl_orders never touches
    them and they rest forever locking currency. Here we flip them to 'expired' (system sweep, no
    owner auth); refund_terminal_buys then returns the escrow — already foreign-aware (local→buyer,
    foreign→GATEWAY + repat). SELL shares are unlocked here (mirrors expire_ttl_orders). Δ-safe:
    reuses the proven refund/unlock paths, moves no money itself. DB-flag gated (key
    'stale_order_sweep' = {"enabled": bool, "hours": float}); absent/disabled → no-op (fleet default
    OFF; canary by setting the flag on a single frame, no recreate)."""
    import json
    raw = await get_flag(db, "stale_order_sweep")
    if not raw:
        return 0
    try:
        cfg = json.loads(raw)
    except (ValueError, TypeError):
        return 0
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return 0
    try:
        hours = float(cfg.get("hours", 48))
    except (ValueError, TypeError):
        hours = 48.0
    if hours <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        await db.execute(
            select(ExchangeOrder)
            .where(
                ExchangeOrder.status.in_(("open", "partial")),
                ExchangeOrder.created_at < cutoff,
            )
            .order_by(ExchangeOrder.created_at.asc())
            .limit(batch)
        )
    ).scalars().all()
    done = 0
    for o in rows:
        await _listing_lock(db, o.listing_id)
        await db.refresh(o)
        if o.status not in ("open", "partial"):
            await db.commit()
            continue
        if o.side == "sell":
            pos = await _get_or_create_position(db, o.listing_id, o.agent_did)
            pos.locked_qty = max(0, pos.locked_qty - o.remaining)
        o.status = "expired"
        await db.commit()
        done += 1
    if done:
        logger.info(
            f"[AGORA-stale-sweep] force-expired {done} resting orders older than {hours}h "
            f"(GTC/passport included; buys refund via refund_terminal_buys, sells share-unlocked)"
        )
    return done


async def settle_ipo_purchases(db: AsyncSession, batch: int = 50) -> int:
    """allocated → proceeds leg (escrow → org treasury) → settled ;
    refunding → refund leg (escrow → buyer) → refunded."""
    rows = (
        await db.execute(
            select(ExchangeIpoPurchase)
            .where(ExchangeIpoPurchase.status.in_(("allocated", "refunding")))
            .order_by(ExchangeIpoPurchase.created_at.asc())
            .limit(batch)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    done = 0
    for p in rows:
        listing = (
            await db.execute(select(ExchangeListing).where(ExchangeListing.id == p.listing_id))
        ).scalar_one()
        try:
            if p.status == "allocated":
                await mover.move(EXCHANGE_ESCROW_SENTINEL, listing.treasury_agent_did, p.amount, "ipo_proceeds", f"ipo-{p.id}:pro")
                p.status = "settled"
            else:
                await mover.move(EXCHANGE_ESCROW_SENTINEL, p.agent_did, p.amount, "ipo_refund", f"ipo-{p.id}:ref")
                p.status = "refunded"
            done += 1
        except ExchangeError as e:
            logger.warning(f"[AGORA] ipo {p.id} settle failed: {e.detail}")
        await db.commit()
    return done


async def process_dividends(db: AsyncSession, leg_batch: int = 50) -> int:
    """Fund the pot (treasury → escrow, once) then drain per-holder legs."""
    divs = (
        await db.execute(
            select(ExchangeDividend).where(ExchangeDividend.status == "paying").limit(5)
        )
    ).scalars().all()
    paid_legs = 0
    # §BAFIN (2026-10-01): switched off, no NEW pot is funded; a pot already in escrow is paid out to the end, so no
    # units are stranded there (core/agora_gate.py)
    from ..core.agora_gate import distributions_enabled
    dist_on = distributions_enabled()
    for d in divs:
        if not d.pot_funded and not dist_on:
            continue
        listing = (
            await db.execute(select(ExchangeListing).where(ExchangeListing.id == d.listing_id))
        ).scalar_one()
        if not d.pot_funded:
            try:
                await mover.move(
                    listing.treasury_agent_did, EXCHANGE_ESCROW_SENTINEL, d.total_amount,
                    "dividend_pot", f"div-{d.listing_id}-{d.epoch}:pot",
                )
                d.pot_funded = True
                await db.commit()
            except ExchangeError as e:
                logger.warning(f"[AGORA] dividend {d.id} pot funding failed: {e.detail}")
                await db.commit()
                continue
        legs = (
            await db.execute(
                select(ExchangeDividendLeg)
                .where(ExchangeDividendLeg.dividend_id == d.id, ExchangeDividendLeg.status == "pending")
                .limit(leg_batch)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        for leg in legs:
            try:
                import hashlib

                did_h8 = hashlib.sha256(leg.agent_did.encode()).hexdigest()[:8]
                # §V0064 P2 repatriation: a FOREIGN holder's dividend parks on
                # the GATEWAY as an attributed credit (batch I sends it home,
                # auto-FX) instead of becoming an unreachable frame-local balance.
                home = await _foreign_home(db, leg.agent_did)
                if home:
                    await mover.move(
                        EXCHANGE_ESCROW_SENTINEL, GATEWAY_DID, leg.amount,
                        "dividend_repat_park", f"divleg-{leg.id}:park",
                    )
                    await _add_gateway_credit(
                        db, leg.agent_did, home, leg.amount, "dividend", f"divleg-{leg.id}"
                    )
                else:
                    await mover.move(
                        EXCHANGE_ESCROW_SENTINEL, leg.agent_did, leg.amount,
                        "dividend_pay", f"div-{d.listing_id}-{d.epoch}:{did_h8}",
                    )
                leg.status = "paid"
                leg.paid_at = datetime.now(timezone.utc)
                paid_legs += 1
                # §NOTIFV2 exchange.dividend_received — wired in the PAYING worker, not in
                # declare_dividend: declaring only writes `status='paying'` legs, so notifying
                # there would announce money that has not moved (and would lie if a leg later
                # failed). Opt-in only (`default_enabled={}`) with a ≥1.0 amount threshold.
                try:
                    import asyncio as _aio_n
                    from agentvault_registry.background_tasks.push_notify import (
                        notify_agent_owners,
                    )
                    _famt = float(leg.amount or 0)
                    if _famt > 0:
                        _aio_n.create_task(notify_agent_owners(
                            "exchange.dividend_received", [leg.agent_did],
                            title="Distribution received",
                            message=f"{_famt:.4f} distribution paid on your points.",
                            amount=_famt, tags="moneybag", priority="default",
                            click="/ui/#/agora/listings"))
                except Exception:  # noqa: BLE001
                    logger.debug("[NOTIFY] exchange.dividend_received emit failed", exc_info=True)
            except ExchangeError as e:
                logger.warning(f"[AGORA] dividend leg {leg.id} failed: {e.detail}")
            await db.commit()
        remaining = (
            await db.execute(
                select(func.count(ExchangeDividendLeg.id)).where(
                    ExchangeDividendLeg.dividend_id == d.id, ExchangeDividendLeg.status == "pending"
                )
            )
        ).scalar_one()
        if remaining == 0:
            d.status = "paid"
            d.paid_at = datetime.now(timezone.utc)
            await db.commit()
            _emit(
                "ExchangeDividendPaid",
                d.listing_id,
                {"dividend_id": d.id, "symbol": listing.symbol, "epoch": str(d.epoch), "total": str(d.total_amount)},
                key=f"exchange-div-paid:{d.id}",
            )
    return paid_legs


async def settle_listing_fees(db: AsyncSession) -> int:
    """Finish interrupted listing-fee leg2 (escrow → fee_collector)."""
    rows = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.listing_fee_paid.is_(False),
                ExchangeListing.listing_fee_parked.is_(True),
            )
        )
    ).scalars().all()
    done = 0
    for listing in rows:
        try:
            await mover.move(EXCHANGE_ESCROW_SENTINEL, FEE_COLLECTOR_SENTINEL, LISTING_FEE, "listing_fee_settle", f"lst-{listing.id}:fees")
            listing.listing_fee_parked = False
            listing.listing_fee_paid = True
            done += 1
        except ExchangeError as e:
            logger.warning(f"[AGORA] listing fee settle for ${listing.symbol} failed: {e.detail}")
        await db.commit()
    return done


# ── invariants (I-X1..4) ─────────────────────────────────────────────────
async def compute_invariants(db: AsyncSession) -> Dict[str, Any]:
    out: Dict[str, Any] = {"listings": [], "ok": True, "checked_at": datetime.now(timezone.utc).isoformat()}

    listings = (await db.execute(select(ExchangeListing))).scalars().all()
    expected_escrow = ZERO

    for l in listings:
        pos_sum = (
            await db.execute(
                select(func.coalesce(func.sum(OrgSharePosition.qty), 0)).where(
                    OrgSharePosition.listing_id == l.id
                )
            )
        ).scalar_one()
        locked_sum = (
            await db.execute(
                select(func.coalesce(func.sum(OrgSharePosition.locked_qty), 0)).where(
                    OrgSharePosition.listing_id == l.id
                )
            )
        ).scalar_one()
        sell_remaining = (
            await db.execute(
                select(func.coalesce(func.sum(ExchangeOrder.remaining), 0)).where(
                    ExchangeOrder.listing_id == l.id,
                    ExchangeOrder.side == "sell",
                    ExchangeOrder.status.in_(("open", "partial")),
                )
            )
        ).scalar_one()
        expected_shares = ((l.total_shares - l.ipo_float) if l.approved else 0) + l.ipo_sold
        ix1 = int(pos_sum) == int(expected_shares)
        ix2 = int(locked_sum) == int(sell_remaining)
        out["listings"].append(
            {
                "symbol": l.symbol,
                "I-X1_share_conservation": ix1,
                "positions_sum": int(pos_sum),
                "expected": int(expected_shares),
                "I-X2_lock_honesty": ix2,
                "locked_sum": int(locked_sum),
                "open_sell_remaining": int(sell_remaining),
            }
        )
        out["ok"] = out["ok"] and ix1 and ix2

    # I-X3 components (venue-global)
    buy_holds = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(
                        ExchangeOrder.escrow_amount
                        - ExchangeOrder.matched_notional
                        - ExchangeOrder.escrow_refunded
                    ),
                    0,
                )
            ).where(
                ExchangeOrder.side == "buy",
                ExchangeOrder.escrow_amount > 0,
                # Only orders that ACTUALLY deposited into escrow hold money.
                # 'rejected' (deposit failed) and 'funding' (deposit in transit
                # — on the buyer or the Passport gateway, not in escrow yet) hold
                # nothing here. Counting them inflated I-X3 expected. (2026-06-12.)
                ExchangeOrder.status.notin_(("rejected", "funding")),
            )
        )
    ).scalar_one()
    unsettled_notional = (
        await db.execute(
            select(func.coalesce(func.sum(ExchangeTrade.notional), 0)).where(
                ExchangeTrade.settle_status == "pending_settlement"
            )
        )
    ).scalar_one()
    ipo_in_flight = (
        await db.execute(
            select(func.coalesce(func.sum(ExchangeIpoPurchase.amount), 0)).where(
                ExchangeIpoPurchase.status.in_(("allocated", "refunding"))
            )
        )
    ).scalar_one()
    unpaid_div_legs = (
        await db.execute(
            select(func.coalesce(func.sum(ExchangeDividendLeg.amount), 0))
            .select_from(ExchangeDividendLeg)
            .join(ExchangeDividend, ExchangeDividend.id == ExchangeDividendLeg.dividend_id)
            .where(ExchangeDividendLeg.status == "pending", ExchangeDividend.pot_funded.is_(True))
        )
    ).scalar_one()
    parked_fees = (
        await db.execute(
            select(func.count(ExchangeListing.id)).where(
                ExchangeListing.listing_fee_parked.is_(True)
            )
        )
    ).scalar_one()
    expected_escrow = q18(
        Decimal(buy_holds)
        + Decimal(unsettled_notional)
        + Decimal(ipo_in_flight)
        + Decimal(unpaid_div_legs)
        + (LISTING_FEE * Decimal(parked_fees))
    )

    try:
        actual_escrow = await mover.escrow_balance()
        delta = q18(actual_escrow - expected_escrow)
        out["I-X3_escrow"] = {
            "expected": str(expected_escrow),
            "actual": str(actual_escrow),
            "delta": str(delta),
            "ok": delta == ZERO,
        }
        out["ok"] = out["ok"] and (delta == ZERO)
        agora_set_invariants(escrow=float(actual_escrow), delta=float(delta))
    except ExchangeError as e:
        out["I-X3_escrow"] = {"error": e.detail, "expected": str(expected_escrow)}
        out["ok"] = False

    # Orders mid-funding are the ONE legitimate transient I-X3 window (deposit
    # may or may not have landed yet; the sweeper converges them within
    # FUNDING_RETRY_AFTER_SEC). Reported so a failing I-X3 can be triaged.
    funding_n = (
        await db.execute(
            select(func.count(ExchangeOrder.id)).where(ExchangeOrder.status == "funding")
        )
    ).scalar_one()
    out["funding_orders_in_transition"] = int(funding_n)

    stuck_cutoff = datetime.now(timezone.utc) - timedelta(seconds=SETTLE_SLO_SEC)
    stuck = (
        await db.execute(
            select(func.count(ExchangeTrade.id)).where(
                ExchangeTrade.settle_status == "pending_settlement",
                ExchangeTrade.created_at < stuck_cutoff,
            )
        )
    ).scalar_one()
    out["I-X4_settlement_liveness"] = {"stuck_over_slo": int(stuck), "ok": int(stuck) == 0}
    out["ok"] = out["ok"] and int(stuck) == 0

    # I-X5 (§V0064 P2): gateway solvency — pending foreign credits must be
    # covered by the gateway's actual balance (>= because the unattributed
    # FX-buffer pool legitimately sits there too). §REPATLANE (V0603): "pending" here is every credit still owed and
    # still on the gateway ('pending', and 'sending' / 'batched' while a send's answer is applied). A held payout
    # ('unresolved') may already have left the gateway, so it is reported beside the check and never fails it.
    pending_credits = (
        await db.execute(
            select(func.coalesce(func.sum(ExchangeGatewayCredit.amount), 0)).where(
                ExchangeGatewayCredit.status.in_(REPAT_OWED_STATUSES)
            )
        )
    ).scalar_one()
    held_n, held_sum = (
        await db.execute(
            select(func.count(ExchangeGatewayCredit.id), func.coalesce(func.sum(ExchangeGatewayCredit.amount), 0))
            .where(ExchangeGatewayCredit.status == REPAT_UNRESOLVED)
        )
    ).one()
    held = {"count": int(held_n or 0), "sum": str(q18(Decimal(held_sum or 0)))}
    if Decimal(pending_credits) > ZERO:
        try:
            gw_bal = await mover.agent_balance(GATEWAY_DID)
            ix5_ok = gw_bal >= q18(Decimal(pending_credits))
            out["I-X5_gateway_solvency"] = {
                "gateway_balance": str(gw_bal),
                "pending_credits": str(q18(Decimal(pending_credits))),
                "unresolved_credits": held,
                "ok": ix5_ok,
            }
            out["ok"] = out["ok"] and ix5_ok
        except (ExchangeError, MoverError) as e:
            out["I-X5_gateway_solvency"] = {"error": str(e), "pending_credits": str(pending_credits),
                                            "unresolved_credits": held}
            out["ok"] = False
    else:
        out["I-X5_gateway_solvency"] = {"pending_credits": "0", "unresolved_credits": held, "ok": True}

    agora_set_invariants(funding_n=int(funding_n), stuck=int(stuck))
    return out


# ── read side (book / tape / candles / stats / portfolio) ───────────────
async def listing_stats(db: AsyncSession, listing: ExchangeListing) -> Dict[str, Any]:
    last = await _last_price(db, listing.id)
    day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(ExchangeTrade.qty), 0),
                func.coalesce(func.sum(ExchangeTrade.notional), 0),
                func.count(ExchangeTrade.id),
                func.min(ExchangeTrade.price),
                func.max(ExchangeTrade.price),
            ).where(ExchangeTrade.listing_id == listing.id, ExchangeTrade.created_at >= day_ago)
        )
    ).one()
    first_24h = (
        await db.execute(
            select(ExchangeTrade.price)
            .where(ExchangeTrade.listing_id == listing.id, ExchangeTrade.created_at >= day_ago)
            .order_by(ExchangeTrade.seq.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    best_bid = (
        await db.execute(
            select(func.max(ExchangeOrder.price)).where(
                ExchangeOrder.listing_id == listing.id,
                ExchangeOrder.side == "buy",
                ExchangeOrder.status.in_(("open", "partial")),
            )
        )
    ).scalar_one_or_none()
    best_ask = (
        await db.execute(
            select(func.min(ExchangeOrder.price)).where(
                ExchangeOrder.listing_id == listing.id,
                ExchangeOrder.side == "sell",
                ExchangeOrder.status.in_(("open", "partial")),
            )
        )
    ).scalar_one_or_none()
    return _stats_from(listing, last, tuple(row), first_24h, best_bid, best_ask)


def _stats_from(listing: ExchangeListing, last, row, first_24h, best_bid, best_ask) -> Dict[str, Any]:
    """The stats a listing shows, from its five reads (the last print, the 24 h aggregate row, the first print of the
    24 h, the best bid and ask). One function for listing_stats and listings_stats, so the batch and the single read
    answer alike to the character."""
    # §2026-06-18 opening price: show the IPO price as the opening "last" until the first
    # secondary trade — the card shows the set price (not "—") + mcap reflects the IPO
    # opening cap; change% stays None (first_24h is None). Display-only: the order-path
    # band check reads _last_price directly, so this never constrains price discovery.
    if last is None and listing.ipo_price and listing.ipo_price > ZERO:
        last = listing.ipo_price
    change_pct = None
    if last is not None and first_24h not in (None, ZERO):
        change_pct = str(q18((last - first_24h) / first_24h * Decimal(100)))
    # market_cap: price × total_shares can exceed the Decimal context precision (28) when an
    # 18-dp price is multiplied by a large share count (→ 29+ digits → InvalidOperation → 500).
    # mcap needs no sub-unit precision, so fall back to 2 dp on overflow. (FLUX 500 fix, 2026-06-17)
    mcap = None
    if last is not None:
        try:
            mcap = str(q18(last * Decimal(listing.total_shares)))
        except ArithmeticError:
            mcap = str((last * Decimal(listing.total_shares)).quantize(Decimal("0.01"), rounding=ROUND_DOWN))
    return {
        "last": str(last) if last is not None else None,
        "best_bid": str(best_bid) if best_bid is not None else None,
        "best_ask": str(best_ask) if best_ask is not None else None,
        "volume_24h_qty": str(row[0]),
        "volume_24h_notional": str(row[1]),
        "trades_24h": int(row[2]),
        "low_24h": str(row[3]) if row[3] is not None else None,
        "high_24h": str(row[4]) if row[4] is not None else None,
        "change_24h_pct": change_pct,
        "market_cap": mcap,
        "ipo_remaining": int(listing.ipo_float - listing.ipo_sold),
    }


async def last_prices(db: AsyncSession, listing_ids) -> Dict[Any, Decimal]:
    """The last print of each listing in one read: what _last_price answers listing by listing, one probe of the
    (listing_id, seq DESC) index per listing asked.

    A DISTINCT ON over the listings' trades read and sorted every trade they ever printed, and grew with each one
    (2026-10-24: sbx-beta's 274,836 trades, an on-disk sort, 586 ms warm and 22 s under load behind /my-agents' AGORA
    chips; sbx-alpha 661 ms). The probe keeps listing_id in its ORDER BY behind a range, not an equality: with
    `listing_id = asked.id` the planner drops the column from the ordering and walks uq_exchange_trades_seq backwards,
    cheap only if every listing printed lately (two listings hold nearly all of sbx-beta's trades, so a quiet one cost
    137,362 skipped rows). Measured with this statement: 0.19 ms on sbx-beta, 0.78 ms for sbx-alpha's 189 listings,
    the same prices on both.
    """
    ids = list(dict.fromkeys(listing_ids))
    if not ids:
        return {}
    asked = values(column("id", String), name="asked").data([(i,) for i in ids])
    last = (
        select(ExchangeTrade.price)
        .where(ExchangeTrade.listing_id.between(asked.c.id, asked.c.id))
        .order_by(ExchangeTrade.listing_id, ExchangeTrade.seq.desc())
        .limit(1)
        .correlate(asked)
        .scalar_subquery()
    )
    rows = (await db.execute(select(asked.c.id, last))).all()
    return {lid: price for lid, price in rows if price is not None}


async def listings_stats(db: AsyncSession, listings) -> Dict[Any, Dict[str, Any]]:
    """listing_stats for many listings in five grouped reads.

    §COCKPITDESK (2026-10-15): GET /exchange/listings asked five reads per listing (875 for sbx-alpha's 175 listings) and
    the AGORA desk asks it every 30 s per open desk. The answer is listing_stats', listing by listing (_stats_from builds
    both); measured equal on sbx-alpha's 175 listings.
    """
    listings = list(listings)
    ids = [l.id for l in listings]
    if not ids:
        return {}
    day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    last = await last_prices(db, ids)
    agg = {
        r[0]: tuple(r[1:])
        for r in (
            await db.execute(
                select(
                    ExchangeTrade.listing_id,
                    func.coalesce(func.sum(ExchangeTrade.qty), 0),
                    func.coalesce(func.sum(ExchangeTrade.notional), 0),
                    func.count(ExchangeTrade.id),
                    func.min(ExchangeTrade.price),
                    func.max(ExchangeTrade.price),
                )
                .where(ExchangeTrade.listing_id.in_(ids), ExchangeTrade.created_at >= day_ago)
                .group_by(ExchangeTrade.listing_id)
            )
        ).all()
    }
    first = {
        lid: price
        for lid, price in (
            await db.execute(
                select(ExchangeTrade.listing_id, ExchangeTrade.price)
                .where(ExchangeTrade.listing_id.in_(ids), ExchangeTrade.created_at >= day_ago)
                .distinct(ExchangeTrade.listing_id)
                .order_by(ExchangeTrade.listing_id, ExchangeTrade.seq.asc())
            )
        ).all()
    }
    live = (ExchangeOrder.listing_id.in_(ids), ExchangeOrder.status.in_(("open", "partial")))
    bids = {
        lid: px
        for lid, px in (
            await db.execute(
                select(ExchangeOrder.listing_id, func.max(ExchangeOrder.price))
                .where(ExchangeOrder.side == "buy", *live)
                .group_by(ExchangeOrder.listing_id)
            )
        ).all()
    }
    asks = {
        lid: px
        for lid, px in (
            await db.execute(
                select(ExchangeOrder.listing_id, func.min(ExchangeOrder.price))
                .where(ExchangeOrder.side == "sell", *live)
                .group_by(ExchangeOrder.listing_id)
            )
        ).all()
    }
    quiet = (0, 0, 0, None, None)   # what the single read's coalesced aggregate answers for a listing with no 24 h trade
    return {
        l.id: _stats_from(l, last.get(l.id), agg.get(l.id, quiet), first.get(l.id), bids.get(l.id), asks.get(l.id))
        for l in listings
    }


async def order_book(db: AsyncSession, listing: ExchangeListing, depth: int = 12) -> Dict[str, Any]:
    async def _side(side: str, asc: bool):
        col = ExchangeOrder.price
        q = (
            select(col.label("price"), func.sum(ExchangeOrder.remaining).label("qty"))
            .where(
                ExchangeOrder.listing_id == listing.id,
                ExchangeOrder.side == side,
                ExchangeOrder.status.in_(("open", "partial")),
            )
            .group_by(col)
            .order_by(col.asc() if asc else col.desc())
            .limit(depth)
        )
        return [{"price": str(r.price), "qty": int(r.qty)} for r in (await db.execute(q)).all()]

    return {"bids": await _side("buy", asc=False), "asks": await _side("sell", asc=True)}


async def recent_trades(db: AsyncSession, listing: ExchangeListing, limit: int = 50) -> List[Dict[str, Any]]:
    rows = (
        await db.execute(
            select(ExchangeTrade)
            .where(ExchangeTrade.listing_id == listing.id)
            .order_by(ExchangeTrade.seq.desc())
            .limit(min(limit, 200))
        )
    ).scalars().all()
    return [
        {
            "seq": t.seq,
            "price": str(t.price),
            "qty": t.qty,
            "notional": str(t.notional),
            "at": t.created_at.isoformat(),
            "buyer_did": t.buyer_did,
            "seller_did": t.seller_did,
        }
        for t in rows
    ]


_TF_SECONDS = {"1m": 60, "15m": 900, "1h": 3600, "1d": 86400}


async def candles(db: AsyncSession, listing: ExchangeListing, tf: str = "1h", limit: int = 120) -> List[Dict[str, Any]]:
    sec = _TF_SECONDS.get(tf)
    if not sec:
        raise ExchangeError(422, f"tf must be one of {sorted(_TF_SECONDS)}")
    limit = min(max(limit, 1), 500)
    # epoch-floor bucketing — PG-version-proof
    q = text(
        """
        SELECT to_timestamp(floor(extract(epoch FROM created_at) / :sec) * :sec) AS bucket,
               (array_agg(price ORDER BY seq ASC))[1]  AS o,
               MAX(price)                              AS h,
               MIN(price)                              AS l,
               (array_agg(price ORDER BY seq DESC))[1] AS c,
               SUM(qty)                                AS v
        FROM exchange_trades
        WHERE listing_id = :lid
        GROUP BY 1 ORDER BY 1 DESC LIMIT :lim
        """
    )
    rows = (await db.execute(q, {"sec": sec, "lid": listing.id, "lim": limit})).all()
    return [
        {"t": r.bucket.isoformat(), "o": str(r.o), "h": str(r.h), "l": str(r.l), "c": str(r.c), "v": int(r.v)}
        for r in reversed(rows)
    ]


async def portfolio(db: AsyncSession, agent_did: str) -> Dict[str, Any]:
    positions = (
        await db.execute(
            select(OrgSharePosition, ExchangeListing)
            .join(ExchangeListing, ExchangeListing.id == OrgSharePosition.listing_id)
            .where(OrgSharePosition.agent_did == agent_did, OrgSharePosition.qty > 0)
        )
    ).all()
    out = []
    for pos, listing in positions:
        last = await _last_price(db, listing.id)
        if last is None and listing.ipo_price and listing.ipo_price > ZERO:
            last = listing.ipo_price  # §2026-06-18 opening price (PnL vs IPO = 0 pre-trade)
        upnl = (
            str(q18((last - pos.avg_cost) * Decimal(pos.qty))) if last is not None else None
        )
        out.append(
            {
                "symbol": listing.symbol,
                "listing_id": listing.id,
                "qty": pos.qty,
                "locked_qty": pos.locked_qty,
                "avg_cost": str(pos.avg_cost),
                "last": str(last) if last is not None else None,
                "unrealized_pnl": upnl,
                "currency": listing.currency,
            }
        )
    divs = (
        await db.execute(
            select(func.coalesce(func.sum(ExchangeDividendLeg.amount), 0)).where(
                ExchangeDividendLeg.agent_did == agent_did, ExchangeDividendLeg.status == "paid"
            )
        )
    ).scalar_one()
    return {"agent_did": agent_did, "positions": out, "dividends_received": str(divs)}


async def my_orders(db: AsyncSession, agent_did: str, listing_ref: Optional[str] = None) -> List[Dict[str, Any]]:
    q = select(ExchangeOrder, ExchangeListing.symbol).join(
        ExchangeListing, ExchangeListing.id == ExchangeOrder.listing_id
    ).where(ExchangeOrder.agent_did == agent_did)
    if listing_ref:
        listing = await _get_listing(db, listing_ref)
        q = q.where(ExchangeOrder.listing_id == listing.id)
    q = q.order_by(ExchangeOrder.created_at.desc()).limit(100)
    rows = (await db.execute(q)).all()
    return [
        {
            "id": o.id,
            "symbol": sym,
            "side": o.side,
            "type": o.order_type,
            "price": str(o.price) if o.price is not None else None,
            "qty": o.qty,
            "remaining": o.remaining,
            "status": o.status,
            "escrow_amount": str(o.escrow_amount),
            "created_at": o.created_at.isoformat(),
        }
        for o, sym in rows
    ]


async def top_traders(db: AsyncSession, hours: int = 24, limit: int = 10) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = text(
        """
        SELECT did, SUM(notional) AS vol, COUNT(*) AS trades FROM (
            SELECT buyer_did AS did, notional FROM exchange_trades WHERE created_at >= :cutoff
            UNION ALL
            SELECT seller_did AS did, notional FROM exchange_trades WHERE created_at >= :cutoff
        ) x GROUP BY did ORDER BY vol DESC LIMIT :lim
        """
    )
    rows = (await db.execute(q, {"cutoff": cutoff, "lim": limit})).all()
    return [{"agent_did": r.did, "volume": str(q18(Decimal(r.vol))), "trades": int(r.trades)} for r in rows]
