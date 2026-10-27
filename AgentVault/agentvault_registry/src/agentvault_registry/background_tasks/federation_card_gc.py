"""W4 — Defunct-card garbage collector.

Daily worker that marks `is_active=false` on agent_cards whose
`federation_metadata.source_registry` doesn't canonically match any peer
currently in `peer_registries`, AND haven't been refreshed in 30 days.

Why this exists:
  - Federation sync stamps `source_registry` once on first arrival and never
    rewrites it. When a peer is decommissioned (status=INACTIVE or removed
    from peer_registries entirely), its cards continue living in our DB
    forever. They re-propagate via federation sync to every new peer, take
    up index space, and pollute /discover results.
  - We had ~196 such cards on Frame A (22 dead registries) + ~200 on Frame B
    (10 INACTIVE Frame B operators) at the time this worker shipped.

Behavior:
  1. Build the set of canonical (trust_domain, name) tuples for live peers.
  2. Iterate cards with `is_active=true AND updated_at < NOW() - 30d AND
     source_registry IS NOT NULL`.
  3. For each: extract canonical from source_registry. If no live peer matches
     → mark `is_active=false` (soft delete — preserves audit trail).
  4. Emit `federation_cards_gc_marked_inactive_total{source}` Prometheus
     counter.

Gating: `FEDERATION_CARD_GC_ENABLED=true|false` (default true since §V0052,
GC_ENABLED below). Cycle interval defaults to 24h. A second pass,
`FEDERATION_CARD_GC_HARD_DELETE` (also default true), deletes a sourced card
that has stayed inactive past `FEDERATION_CARD_GC_HARD_DELETE_GRACE_DAYS` (30).

Recovery: a defunct card whose source registry rejoins the federation can be
manually re-activated via admin endpoint (or just wait — when sync brings
fresh data from the rejoined source, upsert clears is_active=false).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Set, Tuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..database import AsyncSessionLocal
from ..services.spiffe_canonical import extract_canonical, _normalize_name
from .leader import run_with_leadership

logger = logging.getLogger(__name__)

# Configuration
# §V0052 (2026-06-10): default-ON. The shadow-bookkeeping audit found ~404 orphan
# cards replicated ×16 (6.4k rows) because this worker shipped dark. Now on by
# default so the federation card cache self-maintains.
GC_ENABLED: bool = os.environ.get("FEDERATION_CARD_GC_ENABLED", "true").lower() == "true"
GC_INTERVAL_SECONDS: float = float(os.environ.get("FEDERATION_CARD_GC_INTERVAL", "86400"))  # 24h
GC_GRACE_DAYS: int = int(os.environ.get("FEDERATION_CARD_GC_GRACE_DAYS", "30"))
GC_BATCH_SIZE: int = int(os.environ.get("FEDERATION_CARD_GC_BATCH_SIZE", "500"))
# §V0052 hard-delete phase: soft-delete (is_active=false) alone leaves rows in place
# forever — they still replicate to new peers. After a card has stayed defunct for
# the hard grace, physically remove it. ONLY ever touches sourced (foreign-shadow)
# cards whose source is NOT a live peer — never native cards, never live shadows.
# Defunct rows re-sync if their origin rejoins → safe + self-healing.
GC_HARD_DELETE: bool = os.environ.get("FEDERATION_CARD_GC_HARD_DELETE", "true").lower() == "true"
GC_HARD_DELETE_GRACE_DAYS: int = int(os.environ.get("FEDERATION_CARD_GC_HARD_DELETE_GRACE_DAYS", "30"))

# Optional Prometheus instrumentation
try:
    from prometheus_client import Counter as _Counter
    GC_MARKED_INACTIVE = _Counter(
        "federation_cards_gc_marked_inactive_total",
        "Cards marked inactive by the defunct-source GC (per-source)",
        labelnames=["source"],
    )
    GC_HARD_DELETED = _Counter(
        "federation_cards_gc_hard_deleted_total",
        "Defunct cards physically deleted by the GC hard-delete phase (per-source)",
        labelnames=["source"],
    )
    _PROM_OK = True
except ImportError:  # pragma: no cover
    _PROM_OK = False
    GC_MARKED_INACTIVE = None
    GC_HARD_DELETED = None


async def _build_live_peer_state(
    db: AsyncSession,
) -> Tuple[Set[Tuple[str, str]], Set[str], Set[str], str]:
    """Returns four facts about the current live federation:
      - td_name_pairs: {(trust_domain, normalized_name)} (strict match)
      - names: {normalized_name} (legacy-stamp fallback — name across any td)
      - external_trust_domains: known trust_domains OTHER than our own
        (Frame B mainframe / Frame B operators viewed from Frame A side; we
        can't enumerate every name there so trust_domain match is sufficient)
      - own_trust_domain: this registry's own trust_domain — within OUR td we
        require name match (we authoritatively know our peers; mismatched
        names → defunct), outside our td we trust the foreign frame.

    INACTIVE peers stay "live" — their cards are legitimate audit-trail data;
    operators may rejoin. Only fully-deleted peer_registries rows trigger GC.
    """
    from collections import defaultdict
    rows = (await db.execute(
        select(models.PeerRegistry.name, models.PeerRegistry.trust_domain)
    )).all()
    td_name_pairs: Set[Tuple[str, str]] = set()
    names: Set[str] = set()
    all_tds: Set[str] = set()
    for name, td in rows:
        norm_name = _normalize_name(name) if name else ""
        td_norm = (td or "").lower() if td else ""
        if norm_name:
            names.add(norm_name)
        if td_norm:
            all_tds.add(td_norm)
        if norm_name and td_norm:
            td_name_pairs.add((td_norm, norm_name))

    own_td = os.environ.get("SPIRE_TRUST_DOMAIN", "").lower()
    external_trust_domains = {td for td in all_tds if td != own_td}
    return td_name_pairs, names, external_trust_domains, own_td


def _is_card_source_live(
    source_spiffe: str,
    td_name_pairs: Set[Tuple[str, str]],
    names: Set[str],
    external_trust_domains: Set[str],
    own_trust_domain: str,
) -> bool:
    """True when the card's source matches a live peer.

    Match precedence:
      1. (trust_domain, name) tuple — exact strict match, any td
      2. name-only — legacy stamps where SPIFFE td differs from peer.td
         (e.g., Frame B mainframe legacy stamp under agentvault.com)
      3. external trust_domain match — the SPIFFE is from a foreign frame
         we know about; we trust the foreign frame's own peer governance
         (avoids over-aggressive GC of Frame B operators from Frame A's view).

    NOT covered → defunct:
      - Source under OUR own trust_domain whose name doesn't match any peer
        (e.g., `spiffe://agentvault.com/registry-capetown-registry` — we're
        on agentvault.com and authoritatively know our peers; capetown is gone)
    """
    canonical = extract_canonical(source_spiffe)
    if canonical is None:
        return True  # unparseable — be conservative, keep
    td, name = canonical
    td_norm = (td or "").lower()
    name_norm = _normalize_name(name)
    if td_norm and name_norm and (td_norm, name_norm) in td_name_pairs:
        return True
    if name_norm and name_norm in names:
        return True
    if td_norm and td_norm != own_trust_domain and td_norm in external_trust_domains:
        return True
    return False


async def _run_gc_cycle() -> None:
    """One garbage-collection pass."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=GC_GRACE_DAYS)

    async with AsyncSessionLocal() as db:
        td_name_pairs, live_names, external_tds, own_td = await _build_live_peer_state(db)

        logger.info(
            f"[federation_card_gc] live peers: {len(td_name_pairs)} (td,name) pairs, "
            f"{len(live_names)} names, {len(external_tds)} external trust_domains, "
            f"own_td={own_td}; grace={GC_GRACE_DAYS}d"
        )

        offset = 0
        total_inactive = 0
        per_source: dict = {}

        while True:
            stmt = (
                select(models.AgentCard.id, models.AgentCard.card_data)
                .where(models.AgentCard.is_active == True)  # noqa: E712
                .where(models.AgentCard.updated_at < cutoff.replace(tzinfo=None))
                .order_by(models.AgentCard.id)
                .limit(GC_BATCH_SIZE)
                .offset(offset)
            )
            rows = (await db.execute(stmt)).all()
            if not rows:
                break

            to_mark_ids = []
            for card_id, card_data in rows:
                fed_meta = (card_data or {}).get("federation_metadata") or {}
                source = fed_meta.get("source_registry") or fed_meta.get("first_synced_from")
                if not source:
                    # Native card — never GC'd
                    continue
                if _is_card_source_live(source, td_name_pairs, live_names, external_tds, own_td):
                    continue
                to_mark_ids.append(card_id)
                per_source[source] = per_source.get(source, 0) + 1

            if to_mark_ids:
                await db.execute(
                    update(models.AgentCard)
                    .where(models.AgentCard.id.in_(to_mark_ids))
                    .values(is_active=False)
                )
                await db.commit()
                total_inactive += len(to_mark_ids)

            offset += len(rows)

        # Emit metrics + log summary
        if _PROM_OK and GC_MARKED_INACTIVE is not None:
            for source, count in per_source.items():
                # Truncate label cardinality (Prom counters explode with too many label values)
                label = (source or "unknown")[:128]
                GC_MARKED_INACTIVE.labels(source=label).inc(count)

        logger.info(
            f"[federation_card_gc] cycle complete: {total_inactive} cards marked inactive "
            f"across {len(per_source)} distinct sources"
        )

        # ── §V0052 hard-delete phase ──────────────────────────────────────────
        # Physically remove cards that have stayed defunct: is_active=false AND
        # aged past the hard grace AND source still not a live peer. Re-checks the
        # live-peer set (a re-activated/rejoined source is skipped). Native cards
        # (no source) are never selected. Done as a SECOND pass so the same cycle
        # that soft-deletes won't also hard-delete in one go (a row must persist
        # >= hard grace in the inactive state first).
        if GC_HARD_DELETE:
            hard_cutoff = datetime.now(timezone.utc) - timedelta(days=GC_HARD_DELETE_GRACE_DAYS)
            offset = 0
            total_deleted = 0
            del_per_source: dict = {}
            while True:
                stmt = (
                    select(models.AgentCard.id, models.AgentCard.card_data)
                    .where(models.AgentCard.is_active == False)  # noqa: E712
                    .where(models.AgentCard.updated_at < hard_cutoff.replace(tzinfo=None))
                    .order_by(models.AgentCard.id)
                    .limit(GC_BATCH_SIZE)
                    .offset(offset)
                )
                rows = (await db.execute(stmt)).all()
                if not rows:
                    break
                to_del_ids = []
                for card_id, card_data in rows:
                    fed_meta = (card_data or {}).get("federation_metadata") or {}
                    source = fed_meta.get("source_registry") or fed_meta.get("first_synced_from")
                    if not source:
                        continue  # native / unsourced — never hard-delete
                    if _is_card_source_live(source, td_name_pairs, live_names, external_tds, own_td):
                        continue  # source rejoined — leave it (sync will reactivate)
                    to_del_ids.append(card_id)
                    del_per_source[source] = del_per_source.get(source, 0) + 1
                if to_del_ids:
                    from sqlalchemy import delete as _delete
                    await db.execute(
                        _delete(models.AgentCard).where(models.AgentCard.id.in_(to_del_ids))
                    )
                    await db.commit()
                    total_deleted += len(to_del_ids)
                    offset = 0  # rows removed → restart from the top of the shrinking set
                else:
                    offset += len(rows)  # nothing deleted this page → advance
            if _PROM_OK and GC_HARD_DELETED is not None:
                for source, count in del_per_source.items():
                    GC_HARD_DELETED.labels(source=(source or "unknown")[:128]).inc(count)
            logger.info(
                f"[federation_card_gc] hard-delete phase: {total_deleted} defunct cards "
                f"removed across {len(del_per_source)} sources (grace={GC_HARD_DELETE_GRACE_DAYS}d)"
            )


async def start_federation_card_gc() -> None:
    """Long-running coroutine — leader-elected daily GC loop."""
    if not GC_ENABLED:
        logger.info("[federation_card_gc] disabled (FEDERATION_CARD_GC_ENABLED=false)")
        return
    logger.info(
        f"[federation_card_gc] starting; interval={GC_INTERVAL_SECONDS}s, "
        f"grace_days={GC_GRACE_DAYS}, batch_size={GC_BATCH_SIZE}"
    )
    try:
        async for _ in run_with_leadership("federation_card_gc", interval=GC_INTERVAL_SECONDS):
            try:
                await _run_gc_cycle()
            except Exception as exc:
                logger.error(f"[federation_card_gc] cycle failed: {exc}", exc_info=True)
    except asyncio.CancelledError:
        logger.info("[federation_card_gc] stopped (cancellation)")
        raise
