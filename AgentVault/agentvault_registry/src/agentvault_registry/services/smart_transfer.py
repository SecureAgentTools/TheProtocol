"""
Smart transfer route derivation — the unified `/teg/send` brain.

Lifts the PROVEN card-based route derivation from the IRONHAND probe panel
(routers/agent_mtls.py ironhand_probe, V0028/V0029) into a reusable service so
an agent-facing endpoint can auto-detect HOW to move value to any receiver:

    local  → POST /api/v1/teg/transfer                    (same registry, same ccy)
    2pc    → POST /api/v1/teg/cross-registry-transfer?backend=2pc   (same ccy, remote; sync)
    async  → POST /api/v1/teg/cross-registry-transfer?backend=async (same ccy, remote; locked→settled)
    fx     → POST /api/v1/teg/cross-registry-transfer     (cross-currency; the WS-C
             currency-match router inside that endpoint routes the FX swap booth /
             Model-C gateway delegation — it is the authoritative method engine)

The derivation here is ADVISORY (preview-grade): the inner endpoint re-resolves
the counterparty currency authoritatively and refuses on unresolvable (never a
silent 1:1 fallback). This module deliberately does NOT refactor ironhand_probe —
zero blast radius on the proven Theatre path; consolidation can come later.

No money moves in this module. Rule 13: all movement happens via the existing
/teg/* endpoints, fired by the caller's own JWT in routers/teg_send.py.
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models

logger = logging.getLogger(__name__)


@dataclass
class RouteDecision:
    """Where a transfer would go and how — preview-grade, engine-confirmed at fire time."""
    method: str                      # local | 2pc | async | fx | refused
    endpoint: str                    # inner endpoint path (incl. query) to fire
    body: dict                       # inner request body
    receiver_did: str = ""
    target_registry: str = ""        # display name (card origin_registry_name) or resolver id
    target_trust_domain: str = ""
    currency_sent: str = "AVT"
    currency_received: str = "AVT"
    currency_source: str = "heuristic"   # card | resolver | heuristic | local
    is_local: bool = False
    is_cross_currency: bool = False
    fx_capable: bool = False         # THIS frame may originate cross-currency routes
    refusal_detail: str = ""         # set when method == "refused"
    notes: list = field(default_factory=list)


def _fx_origination_capable() -> bool:
    """Mirror of the ironhand_probe FX-frame guard: cross-currency routes may only be
    ORIGINATED by an FX-capable frame (local booth FX_ENABLED or routing FX_ROUTE_ENABLED).
    FX mesh = Frame-A (west) <-> Frame-C (middle-east); Frame-B has FX deactivated."""
    _on = ("1", "true", "yes", "on")
    return (os.getenv("FX_ENABLED", "").strip().lower() in _on or
            os.getenv("FX_ROUTE_ENABLED", "").strip().lower() in _on)


async def derive_route(
    db: AsyncSession,
    sender_did: str,
    receiver_did: str,
    amount: str,
    message: str = "",
    backend_hint: Optional[str] = None,
) -> RouteDecision:
    """Derive the transfer route for receiver_did, mirroring ironhand_probe's
    card-cache-first resolution (agent_mtls.py:885-949)."""
    # Helpers live in the (large) teg_integration module — import at call time,
    # same pattern agent_mtls uses, to keep module import light and cycle-free.
    from ..routers.teg_integration import (
        _resolve_receiver_registry, _local_frame_currency, _get_local_registry_id,
    )

    local_ccy = _local_frame_currency()
    local_rid = _get_local_registry_id()
    dec = RouteDecision(
        method="local", endpoint="/api/v1/teg/transfer", body={},
        receiver_did=receiver_did, currency_sent=local_ccy, currency_received=local_ccy,
    )

    # ── LOCALITY FIRST (§POCKETBRIDGE2). A receiver registered in THIS
    # registry's agents table is local — a table fact — and a local receiver
    # settles in the local currency by definition. The old order derived the
    # currency BEFORE checking locality and let the guess veto the fact:
    # a local frame-b/frame-c agent whose card carries no spiffe_id (typical
    # for locally-created agents) fell through every trust-domain lookup —
    # the local registry is never a row in its own peer_registries — landed
    # on the "AVT" heuristic fallback, flipped is_cross_currency, and a
    # same-registry BVT→BVT send was dispatched down the FX rail, which then
    # correctly refused a local receiver ("Cannot resolve registry"). Local
    # wins outright and skips the remote derivation entirely. ──
    local_hit = (await db.execute(
        select(models.Agent.did).where(models.Agent.did == receiver_did)
    )).scalar_one_or_none()
    if local_hit:
        dec.is_local = True
        dec.is_cross_currency = False
        dec.currency_source = "local"
        dec.currency_sent = local_ccy
        dec.currency_received = local_ccy
        dec.target_registry = local_rid or "this registry"
        dec.fx_capable = _fx_origination_capable()
        dec.method = "local"
        dec.endpoint = "/api/v1/teg/transfer"
        dec.body = {"receiver_agent_id": receiver_did, "amount": amount}
        if message:
            dec.body["message"] = message
        if backend_hint:
            dec.notes.append("backend hint ignored for local transfers")
        return dec

    # ── Target home (trust domain + display registry) from the federated card cache —
    # reliable even for indirect child ops the resolver can't reach. ──
    target_td, dest_reg = "", ""
    card = (await db.execute(
        select(models.AgentCard.card_data).where(models.AgentCard.agent_did == receiver_did)
    )).scalar_one_or_none()
    if isinstance(card, dict):
        fm = card.get("federation_metadata") or {}
        sp = fm.get("spiffe_id") or ""
        try:
            target_td = sp.split("://", 1)[1].split("/", 1)[0]
        except Exception:
            target_td = ""
        dest_reg = fm.get("origin_registry_name") or ""
        if target_td:
            dec.currency_source = "card"
    if not target_td:
        try:
            _ttd, _trid = await _resolve_receiver_registry(db, receiver_did)
            target_td = str(_ttd or "")
            if not dest_reg:
                dest_reg = str(_trid or "")
            if target_td:
                dec.currency_source = "resolver"
        except Exception:
            target_td = ""
    dec.target_trust_domain = target_td
    dec.target_registry = dest_reg or target_td

    # Currency: prefer the ENGINE'S authoritative resolver (trust-domain → signed frame card) so the
    # PREVIEW matches what fires. Child ops resolve by their peer row's trust_domain (e.g. op-doha →
    # frame-c.theprotocol.cloud → BVT) — the old string heuristic misread them as AVT and quoted a
    # phantom FX conversion for a same-currency transfer (2026-07-09 fix). Heuristic stays as fallback.
    target_ccy = None
    try:
        from agentvault_registry.routers.teg_integration import _resolve_peer_currency
        _td = target_td
        if _td and "frame-" not in _td and "agentvault" not in _td:
            _td = ""  # not a trust domain (resolver returned a registry id/url) — look it up
        if not _td and dec.target_registry:
            _td = (await db.execute(sa_text(
                "SELECT trust_domain FROM peer_registries WHERE name = :n AND trust_domain IS NOT NULL LIMIT 1"
            ), {"n": dec.target_registry})).scalar() or ""
        if _td:
            target_ccy = await _resolve_peer_currency(db, trust_domain=_td)
            if target_ccy:
                dec.currency_source = "authoritative"
    except Exception:  # noqa: BLE001 — preview must never fail on currency lookup
        target_ccy = None
    if not target_ccy:
        target_ccy = "BVT" if "frame-c" in target_td else "AVT"
    dec.currency_received = target_ccy
    dec.is_cross_currency = (target_ccy != local_ccy)
    dec.fx_capable = _fx_origination_capable()

    # Receiver unknown EVERYWHERE (not local — that returned above — no card,
    # no resolver hit): refuse here with a helpful detail instead of letting
    # the inner endpoint 400 on a half-derived route.
    if not target_td:
        dec.method = "refused"
        dec.refusal_detail = (
            f"Receiver {receiver_did} is unknown to this registry: not a local agent and "
            f"no federated agent card is cached. If the agent was just created on a peer, "
            f"wait for federation card sync (or trigger it) and retry."
        )
        return dec

    # FX-frame guard — refuse cleanly BEFORE any leg fires (probe-identical semantics).
    if dec.is_cross_currency and not dec.fx_capable:
        dec.method = "refused"
        dec.refusal_detail = (
            f"{local_rid or 'this frame'} is not an FX frame — cross-currency "
            f"({local_ccy}→{target_ccy}) routes run only between Frame-A (west) and "
            f"Frame-C (middle-east). This frame has FX disabled."
        )
        return dec

    # ── Route map (probe-identical; local returned early above) ──
    if dec.is_cross_currency:
        dec.method = "fx"
        # No backend param: the WS-C currency-match router inside cross-registry-transfer
        # detects the cross-currency case and routes the FX booth / gateway delegation.
        dec.endpoint = "/api/v1/teg/cross-registry-transfer"
        dec.body = {"receiver_did": receiver_did, "amount": amount}
        if message:
            dec.body["message"] = message
        if backend_hint:
            dec.notes.append("backend hint ignored for cross-currency routes (engine decides)")
    else:
        be = (backend_hint or "2pc").lower()
        if be not in ("2pc", "async"):
            be = "2pc"
        dec.method = be
        dec.endpoint = f"/api/v1/teg/cross-registry-transfer?backend={be}"
        dec.body = {"receiver_did": receiver_did, "amount": amount}
        if message:
            dec.body["message"] = message
    return dec
