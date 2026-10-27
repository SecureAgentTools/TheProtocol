"""Background task for federation synchronization.

This module implements the federation sync worker that periodically
synchronizes agent cards with trusted peer registries.
"""
import asyncio
import os
import logging
import re
import time as _time_mod
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..es_ssl_helper import get_httpx_verify
from sqlalchemy import select, func

from .. import models
from ..config import settings
from ..crud import crud_peer_registry
from ..database import get_db, AsyncSessionLocal
from ..identity import svid_client
from ..services.bayesian_trust import derived_trust_for, refresh_derived_trust
from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Prometheus instrumentation (added 2026-04-30 — Grafana federation dash)
# ----------------------------------------------------------------------
try:
    from prometheus_client import Counter as _FedCounter, Gauge as _FedGauge

    FEDERATION_PEERS_TOTAL = _FedGauge(
        "federation_peers_total",
        "Total federation peers grouped by status (active|inactive|pending|...)",
        labelnames=["status", "registry"],
    )
    FEDERATION_LICENSE_PEERS_TOTAL = _FedGauge(
        "federation_license_peers_total",
        "Federation peers grouped by license state (active|suspended|revoked|none)",
        labelnames=["license_state", "registry"],
    )
    FEDERATION_SYNC_LAST_SUCCESS_TIMESTAMP = _FedGauge(
        "federation_sync_last_success_timestamp_seconds",
        "Unix timestamp of the last successful federation sync cycle",
        labelnames=["registry"],
    )
    # §pass29 Phase 6 — cycle observability metrics.
    FEDERATION_SYNC_CYCLE_TOTAL = _FedCounter(
        "federation_sync_cycle_total",
        "Federation sync cycles run (leader only)",
        labelnames=["registry"],
    )
    FEDERATION_SYNC_PEER_ATTEMPTS_TOTAL = _FedCounter(
        "federation_sync_peer_attempts_total",
        "Per-peer sync attempts by outcome (success | error | skipped)",
        labelnames=["registry", "peer", "outcome"],
    )
    FEDERATION_SYNC_ERRORS_TOTAL = _FedCounter(
        "federation_sync_errors_total",
        "Cycle-level errors by reason",
        labelnames=["registry", "reason"],
    )
    # §2026-07-26 — a peer skipped by the card-pull backoff is NOT an error and NOT a
    # success; without its own counter a deliberate skip is indistinguishable from
    # "nothing to sync", which is exactly how the 6k/day 401 loop stayed invisible.
    # Small fixed reason set — never label by peer name here (that lives on
    # FEDERATION_SYNC_PEER_ATTEMPTS_TOTAL, which is already peer-bounded).
    FEDERATION_CARD_PULL_BACKOFF_TOTAL = _FedCounter(
        "federation_card_pull_backoff_total",
        "Agent-card pulls skipped or deferred by the per-peer backoff, by reason",
        labelnames=["registry", "reason", "action"],
    )
    FEDERATION_SYNC_LAST_CYCLE_DURATION_MS = _FedGauge(
        "federation_sync_last_cycle_duration_ms",
        "Wall-clock duration of the most recent cycle, ms",
        labelnames=["registry"],
        multiprocess_mode="max",
    )
    # §SYNCPAGE (2026-08-03) — a FULL page means the delta window overflowed the
    # page limit: we are behind and the cursor walk is active. Before the walk
    # existed this state was INVISIBLE (the client took one page, stamped
    # last_synced_at=now() and silently skipped the rest — the first-sync
    # truncation cliff). Small fixed mode set; peer names stay in the logs.
    FEDERATION_SYNC_WINDOW_OVERFLOW_TOTAL = _FedCounter(
        "federation_sync_window_overflow_total",
        "Paged-sync windows that overflowed the page limit (walk continued), by mode",
        labelnames=["registry", "mode"],
    )
    # §FEDSYNCTRUTH (2026-09-03) — a peer row the card fan-out REFUSED to create, by reason
    # (infra_label | card_name_mismatch | empty_name). A refusal is the ghost class not
    # happening; it must be countable, never silent. Small fixed reason set.
    FEDERATION_FANOUT_PEER_REFUSED_TOTAL = _FedCounter(
        "federation_fanout_peer_refused_total",
        "Peer rows the registry-card fan-out refused to create, by reason",
        labelnames=["registry", "reason"],
    )
    # §DIDWIDEN (2026-09-06): the cross-frame DID collision class, made visible.
    # A mirrored card whose agent_did a LOCAL row already holds (a native agent or
    # another peer's mirror) trips uix_agent_cards_agent_did inside the per-card
    # savepoint and used to vanish as a DEBUG "skipped 1 card". holder = native|mirror|unknown.
    FEDERATION_CARD_DID_CONFLICT_TOTAL = _FedCounter(
        "federation_card_did_conflict_total",
        "Mirrored agent cards dropped because a local row already holds their agent_did, by peer and holder kind",
        labelnames=["registry", "peer", "holder"],
    )
    _FED_PROM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _FED_PROM_AVAILABLE = False
    FEDERATION_FANOUT_PEER_REFUSED_TOTAL = None  # type: ignore[assignment]
    FEDERATION_PEERS_TOTAL = None  # type: ignore[assignment]
    FEDERATION_LICENSE_PEERS_TOTAL = None  # type: ignore[assignment]
    FEDERATION_SYNC_LAST_SUCCESS_TIMESTAMP = None  # type: ignore[assignment]
    FEDERATION_SYNC_CYCLE_TOTAL = None  # type: ignore[assignment]
    FEDERATION_SYNC_PEER_ATTEMPTS_TOTAL = None  # type: ignore[assignment]
    FEDERATION_SYNC_ERRORS_TOTAL = None  # type: ignore[assignment]
    FEDERATION_SYNC_LAST_CYCLE_DURATION_MS = None  # type: ignore[assignment]
    FEDERATION_CARD_PULL_BACKOFF_TOTAL = None  # type: ignore[assignment]
    FEDERATION_SYNC_WINDOW_OVERFLOW_TOTAL = None  # type: ignore[assignment]
    FEDERATION_CARD_DID_CONFLICT_TOTAL = None  # type: ignore[assignment]


_DID_CONFLICT_INDEX = "uix_agent_cards_agent_did"


# §TRUSTPOLICY — a refusal nobody can count is a refusal nobody can audit.
try:
    from prometheus_client import Counter as _TPCounter

    FEDERATION_TRUST_INGEST_TOTAL = _TPCounter(
        "federation_trust_ingest_total",
        "Peer card batches seen by the peer-trust gate, by peer, state and outcome",
        labelnames=["peer", "state", "outcome"],  # outcome: refused|observed|failed_open
    )
    _TP_PROM = True
except ImportError:  # pragma: no cover
    _TP_PROM = False
    FEDERATION_TRUST_INGEST_TOTAL = None  # type: ignore[assignment]


def _trust_ingest_counter(peer_name: str, state: str, outcome: str) -> None:
    if _TP_PROM:
        try:
            FEDERATION_TRUST_INGEST_TOTAL.labels(
                peer=str(peer_name)[:64], state=state, outcome=outcome).inc()
        except Exception:  # pragma: no cover
            pass


async def _emit_trust_action(peer, verdict, card_count: int, *, refused: bool) -> None:
    """Put the decision on the ledger, with the evidence that produced it.

    ⚠ The event carries the DISCOUNT and the INTERACTION COUNT, not just the
    state: a peer withheld from for trust must be distinguishable afterwards from
    a peer that was merely quiet, and six months later the number is the only
    thing that can settle which it was.
    """
    try:
        from ..event_emitter import get_event_emitter
        emitter = get_event_emitter()
        if emitter is None:
            return
        from datetime import datetime as _dt, timezone as _tz
        await emitter.emit(  # §SILENT: keyed per peer and minute (one recorder run per cycle), emit_event takes no key
            aggregate_id=f"peer_registry:{getattr(peer, 'id', '?')}",
            event_type="PeerTrustActionApplied" if refused else "PeerTrustActionObserved",
            idempotency_key=f"peer-trust-action-{getattr(peer, 'id', '?')}-{_dt.now(_tz.utc).strftime('%Y%m%dT%H%M')}",
            data={
                "peer_id": getattr(peer, "id", None),
                "peer_name": getattr(peer, "name", None),
                "cards_withheld": card_count,
                **verdict.to_dict(),
            },
        )
    except Exception as exc:  # noqa: BLE001
        # §SILENT (2026-09-14): a trust decision that never reached the ledger is an ERROR, not a debug line
        logger.error("[EMIT-LOST] PeerTrustAction for peer=%s not recorded: %s", getattr(peer, "id", "?"), exc)


def classify_card_skip(exc: BaseException) -> str:
    """§DIDWIDEN — name WHY a per-card savepoint rolled back.

    ``did_conflict``: the unique index on agent_cards.agent_did refused the mirror
    (a local native agent or another mirror already holds that DID). Anything else
    is ``other`` and keeps today's DEBUG-level skip.
    """
    try:
        from sqlalchemy.exc import IntegrityError
    except Exception:  # pragma: no cover
        return "other"
    if isinstance(exc, IntegrityError) and _DID_CONFLICT_INDEX in str(getattr(exc, "orig", None) or exc):
        return "did_conflict"
    return "other"


def incoming_card_did(card: Any) -> Optional[str]:
    """The agent_did a peer's card envelope carries (top-level or inside card_data)."""
    if not isinstance(card, dict):
        return None
    did = card.get("agent_did")
    if not did:
        cd = card.get("card_data")
        did = cd.get("did") if isinstance(cd, dict) else None
    return str(did) if did else None


async def _local_did_holder(db, did: Optional[str]) -> str:
    """native | mirror | unknown — who holds the DID the mirror tried to take."""
    if not did:
        return "unknown"
    try:
        from sqlalchemy import select as _sel
        if (await db.execute(_sel(models.Agent.id).where(models.Agent.did == did).limit(1))).first() is not None:
            return "native"
        if (await db.execute(_sel(models.AgentCard.id).where(models.AgentCard.agent_did == did).limit(1))).first() is not None:
            return "mirror"
    except Exception:  # noqa: BLE001 — never let telemetry fail the batch
        pass
    return "unknown"


def _count_did_conflict(peer: str, holder: str) -> None:
    if FEDERATION_CARD_DID_CONFLICT_TOTAL is None:
        return
    try:
        FEDERATION_CARD_DID_CONFLICT_TOTAL.labels(
            registry=(settings.REGISTRY_NAME or "unknown"), peer=peer, holder=holder
        ).inc()
    except Exception:  # noqa: BLE001
        pass


def presenter_svid_for(peer) -> str:
    """The SPIFFE ID a peer presents under: ``spiffe://<its trust domain>/registry/<its name>``.

    A row without a trust domain (pre-§pass66.1 rows that never got the backfill) keeps the legacy
    template, which canonical_equals still resolves by name — never a guess about agentvault.com for
    a peer that told us where it lives.
    """
    td = (getattr(peer, "trust_domain", None) or "").strip().lower()
    name = str(getattr(peer, "name", "") or "").strip().lower().replace(" ", "-")  # a SPIFFE path segment carries no spaces
    if td:
        return f"spiffe://{td}/registry/{name}"
    return f"spiffe://agentvault.com/ns/agentvault/sa/registry-{name}"


def _fanout_refused(reason: str) -> None:
    """§FEDSYNCTRUTH — count a refused fan-out peer creation (best-effort, never raises)."""
    if FEDERATION_FANOUT_PEER_REFUSED_TOTAL is None:
        return
    try:
        FEDERATION_FANOUT_PEER_REFUSED_TOTAL.labels(
            registry=(settings.REGISTRY_NAME or "unknown"), reason=reason
        ).inc()
    except Exception:  # noqa: BLE001
        pass


# §pass29 Phase 6 — per-cycle snapshot, populated by _perform_sync_cycle.
_LAST_CYCLE_STATS: Dict[str, Any] = {
    "last_cycle_iso": None,
    "last_duration_ms": 0,
    "active_peers": 0,
    "license_gated_skipped": 0,
    "success_count": 0,
    "error_count": 0,
    "backoff_skipped": 0,       # §2026-07-26 peers deliberately not called this cycle
    "watermark_skipped": 0,     # §FEDSYNC-V2 peers with nothing newer than our cursor
    "cycle_error": None,        # cycle-level fatal error message
}


# ----------------------------------------------------------------------
# §2026-07-26 — per-peer agent-card-pull backoff
#
# Every registry in the fleet holds ACTIVE peer rows for cross-frame operators whose
# agent-card pull it will never be authorised for. That is BY DESIGN — see the §2026-06-24
# note at the 401/403 branch below: the legacy per-peer card pull has no fan-out carry, so
# registry cards reach these peers via the mainframe relay and agent cards simply do not.
#
# The defect was not the refusal, it was the RETRY. `last_synced_at` is only written on
# success, so a refused peer stayed NULL forever, every cycle re-sent the no-`since`
# "give me 10000 cards" request, and each rejection cost the RECEIVER three WARNING lines.
# Measured on the host nginx: ~6,000 rejected pulls/day, flat since at least 19 Jul —
# ~18,000 warning lines/day fleet-wide, the single loudest source on the estate.
#
# So: remember the refusal and stop asking for a while. This is deny-preserving — we drop
# requests, nobody gains authority — and it is never permanent: the backoff always expires
# and the peer is re-probed, so the day a peer IS authorised it heals on its own.
#
# Stored in Redis, not memory: the worker is leader-elected but the leader can move between
# workers and restarts, and an in-process dict would forget on every recreate (the same
# process-local-state trap that made the CROSS-REG resolver fail).
# ----------------------------------------------------------------------
_CARD_PULL_BACKOFF_PREFIX = "registry:federation:cardpull_backoff:"
# §2026-07-26b — the streak MUST live in its own key.
#
# It was originally packed into the suppression key as "<reason>:<streak>". That key's TTL
# *is* the suppression window, and we only re-probe once it has expired — so at the moment
# of the next refusal the previous value was always gone, the streak always read 0, and
# `streak += 1` always produced 1. Escalation was unreachable code: observed live on 9 nodes,
# every key `:1`, none ever `:2`, so the backoff sat flat at its base and never approached
# the 6 h / 1 h caps this module advertises.
#
# The streak key therefore has to OUTLIVE the suppression window by at least the gap between
# expiry and the next sync cycle. It still decays on its own, so a peer that genuinely goes
# quiet for a long stretch starts fresh rather than inheriting an ancient grudge.
_CARD_PULL_STREAK_PREFIX = "registry:federation:cardpull_streak:"

# base, cap (seconds). Unauthorised is a POLICY fact and stable, so back off hard.
# Unreachable is usually transient, so recover fast — peer_revival_prober (§V0150) owns
# genuine reachability; this only stops us hammering a peer that is refusing us right now.
_CARD_PULL_BACKOFF = {
    "unauthorized": (1800, 21600),   # 30 min → 6 h
    "unreachable":  (300, 3600),     # 5 min → 1 h
}


def _card_pull_backoff_enabled() -> bool:
    """Kill switch. Set FEDERATION_CARD_PULL_BACKOFF=0 to restore pre-fix behaviour."""
    return os.getenv("FEDERATION_CARD_PULL_BACKOFF", "1").strip().lower() not in ("0", "false", "no")


def _count_backoff(reason: str, action: str) -> None:
    if FEDERATION_CARD_PULL_BACKOFF_TOTAL is None:
        return
    try:
        FEDERATION_CARD_PULL_BACKOFF_TOTAL.labels(
            registry=_fed_registry_label(), reason=reason, action=action
        ).inc()
    except Exception:
        pass


async def _card_pull_backoff_reason(peer_name: str) -> Optional[str]:
    """Return the reason this peer's card pull is currently suppressed, else None.

    Fail-OPEN: any Redis problem means we sync as before. A broken cache must never
    be able to stop federation.
    """
    if not _card_pull_backoff_enabled():
        return None
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return None
        raw = await r.get(_CARD_PULL_BACKOFF_PREFIX + peer_name)
        if not raw:
            return None
        val = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        return val.split(":", 1)[0] or None
    except Exception:
        return None


async def _note_card_pull_refusal(peer_name: str, reason: str) -> None:
    """Record a refusal and (re)arm the backoff, doubling on each consecutive refusal.

    Logs at WARNING exactly ONCE — when the backoff is first armed — then stays quiet.
    The whole point is to stop generating noise, so escalations log at DEBUG.
    """
    if not _card_pull_backoff_enabled():
        return
    base, cap = _CARD_PULL_BACKOFF.get(reason, _CARD_PULL_BACKOFF["unreachable"])
    # Derive the floor from the MEASURED cycle interval rather than trusting the constant.
    # Canary caught this: a 300s "unreachable" base against the default 300s sync interval
    # meant the first backoff expired before the next cycle even ran, so 3 of 5 refused
    # peers re-armed instead of being skipped. A backoff shorter than one cycle is a no-op
    # by construction — floor it at two cycles so the very first refusal always buys silence.
    try:
        base = max(base, 2 * get_sync_interval())
        cap = max(cap, base)
    except Exception:
        pass
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return
        key = _CARD_PULL_BACKOFF_PREFIX + peer_name
        skey = _CARD_PULL_STREAK_PREFIX + peer_name
        # Read the streak from its OWN key — never from the suppression key, which by
        # definition has already expired by the time we are here. (§2026-07-26b)
        prev = await r.get(skey)
        streak = 0
        if prev:
            val = prev.decode() if isinstance(prev, (bytes, bytearray)) else str(prev)
            if val.isdigit():
                streak = int(val)
        streak += 1
        ttl = min(cap, base * (2 ** (streak - 1)))
        # Spread, not full jitter: these are periodic waits, and full jitter would halve
        # the mean and double the retry rate. See [[feedback_jitter_vs_spread_and_fix_the_class]].
        try:
            from agentvault_registry.services.pubsub_backoff import spread as _spread
            ttl = int(_spread(ttl, frac=0.15))
        except Exception:
            pass
        ttl = max(60, ttl)
        await r.set(key, f"{reason}:{streak}", ex=ttl)
        # The streak must survive the window between this backoff expiring and the next
        # cycle actually re-probing, or it resets and escalation dies (that was the bug).
        # ttl + 4 cycles of headroom, floored at 15 min. It still decays, so a peer that
        # goes quiet for a long stretch starts clean rather than inheriting an old grudge.
        try:
            streak_ttl = ttl + max(4 * get_sync_interval(), 900)
        except Exception:
            streak_ttl = ttl + 900
        await r.set(skey, str(streak), ex=streak_ttl)
        if streak == 1:
            logger.warning(
                f"Agent-card pull from {peer_name} refused ({reason}); backing off {ttl}s. "
                f"Peer stays ACTIVE and is re-probed when the backoff expires — registry "
                f"cards are unaffected (they arrive via the fan-out carry)."
            )
            _count_backoff(reason, "armed")
        else:
            logger.debug(
                f"Agent-card pull from {peer_name} still refused ({reason}), "
                f"streak={streak}, backing off {ttl}s"
            )
            _count_backoff(reason, "escalated")
    except Exception as e:
        logger.debug(f"[card-pull-backoff] could not arm backoff for {peer_name}: {e}")


async def _clear_card_pull_backoff(peer_name: str) -> None:
    """A successful pull clears the streak — the peer healed."""
    if not _card_pull_backoff_enabled():
        return
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return
        # Both keys: leaving the streak behind would make the next unrelated refusal
        # escalate straight to a long backoff on a peer that has demonstrably recovered.
        removed = await r.delete(_CARD_PULL_BACKOFF_PREFIX + peer_name)
        await r.delete(_CARD_PULL_STREAK_PREFIX + peer_name)
        if removed:
            logger.info(f"Agent-card pull from {peer_name} succeeded — backoff cleared")
            _count_backoff("recovered", "cleared")
    except Exception:
        pass


def _fed_registry_label() -> str:
    return os.getenv("REGISTRY_NAME", "registry")


# ----------------------------------------------------------------------
# §SYNCPAGE (2026-08-03) — cursor-true paged pull + periodic full reconcile.
#
# The old pull took ONE page (limit 10000) and stamped last_synced_at=now()
# regardless — so any delta window larger than a page (first sync of a fresh
# peer being the guaranteed case) was silently truncated FOREVER: the missing
# cards only ever arrived if they happened to be updated again at the source.
# The code even referred failures to "the periodic full-reconcile", which did
# not exist. Now: pages walk an ascending updated_at cursor (server support:
# `paged=1` on /federation/agent-cards — old servers ignore it and behave
# exactly as before, i.e. the mixed-fleet window is never WORSE than today),
# the cursor persists after every page (crash/budget = resume, not restart),
# and a slow jittered reconcile re-walks each peer from epoch every
# FEDERATION_FULL_RECONCILE_DAYS as the standing completeness guarantee
# (unchanged cards are no-ops under the §2026-06-16 delta idempotency).

def _sync_page_limit() -> int:
    # §FEDSYNC-V2 (2026-08-05): source default 10000 → 2000. 18 registries share
    # one 24-core host; a 10k-card page is ~15 MB of JSON serialized in one
    # request. With the updated_at index + watermark skip, page size only
    # matters on bootstrap/repair walks — smaller pages keep those polite.
    try:
        v = int(os.getenv("FEDERATION_SYNC_PAGE_LIMIT", "2000"))
    except ValueError:
        v = 2000
    return max(100, min(v, 20000))


def _sync_max_pages(reconcile: bool) -> int:
    env = "FEDERATION_RECONCILE_PAGES_PER_CYCLE" if reconcile else "FEDERATION_SYNC_MAX_PAGES_PER_CYCLE"
    default = 5 if reconcile else 25
    try:
        v = int(os.getenv(env, str(default)))
    except ValueError:
        v = default
    return max(1, min(v, 200))


def _reconcile_interval_seconds() -> float:
    """0 = reconcile disabled (kill switch)."""
    try:
        days = float(os.getenv("FEDERATION_FULL_RECONCILE_DAYS", "7"))
    except ValueError:
        days = 7.0
    return max(0.0, days) * 86400.0


# §FEDSYNC-V2 (2026-08-05) — watermark fast-path + digest completeness check.
#
# The mesh's steady state is ZERO changed cards per hour, yet every cycle every
# registry paged every peer ("Received 0 agent cards" × peers × 18 registries,
# all on one host). Two cheap questions now precede the expensive machinery:
#
#   watermark — before an incremental pull, ask the peer for max(updated_at).
#       Nothing newer than our cursor ⇒ skip the page walk entirely. The data
#       cursor (last_synced_at) is deliberately NOT advanced on a skip — it
#       still truthfully means "I have everything up to T", and stamping now()
#       on the strength of a point-in-time read is exactly the §SYNCPAGE
#       truncation bug shape. Corridor freshness is recorded separately.
#
#   digest — the periodic completeness guarantee. Instead of re-walking the
#       peer's whole corpus every FULL_RECONCILE_DAYS to answer "do we
#       differ?", fetch per-origin bucket digests and compare. Equal ⇒ the
#       walk is DEFERRED (that comparison IS the reconcile). Mismatch ⇒ run
#       the existing read-repair walk (unchanged machinery), then verify soon
#       after. Peers that 404 the endpoint (pre-§FEDSYNC-V2 code) keep the
#       legacy timed walk, exactly as before — never "assume in sync".
#
# Both fail OPEN to the pre-existing behavior on any error.

def _watermark_enabled() -> bool:
    """Kill switch. FEDERATION_SYNC_WATERMARK=0 restores unconditional pulls."""
    return os.getenv("FEDERATION_SYNC_WATERMARK", "1").strip().lower() not in ("0", "false", "no")


def _digest_interval_seconds() -> float:
    """Cadence of the digest completeness check. 0 = disabled (pure legacy
    timed reconcile). Default 1 day — checking is ~one query per side, so it
    can run far more often than the weekly walk it replaces."""
    try:
        days = float(os.getenv("FEDERATION_DIGEST_CHECK_DAYS", "1"))
    except ValueError:
        days = 1.0
    return max(0.0, days) * 86400.0


_DIGEST_NEXT_PREFIX = "registry:federation:digest_next:"
_DIGEST_UNSUP_PREFIX = "registry:federation:digest_unsupported:"
_DIGEST_MISS_PREFIX = "registry:federation:digest_missfails:"
# §DIGESTSTALL (2026-09-28): the image that last looked at a peer's digest. A different one gets one fresh look.
_DIGEST_IMAGE_PREFIX = "registry:federation:digest_image:"


def _running_image_tag() -> str:
    """The code this process runs (the constant every build bumps), or "" when it cannot be read."""
    try:
        from ..core.registry_identity import BUNDLED_IMAGE_TAG
        return str(BUNDLED_IMAGE_TAG or "")
    except Exception:  # noqa: BLE001 — a missing tag only means no fresh look is scheduled
        return ""


async def _compute_local_digest() -> Optional[tuple]:
    """(own_display_name, {bucket: {count, sum}}) over OUR corpus, or None on
    failure. Uses the SAME SQL constant the serving endpoint runs — one
    definition, so requester and responder can never drift."""
    try:
        from agentvault_registry.routers.federation_sync import (
            compute_digest_buckets, _get_display_name,
        )
        async with AsyncSessionLocal() as db:
            own_name = await _get_display_name(db)
            buckets = await compute_digest_buckets(db, own_name)
        return own_name, buckets
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[FED-SYNC] local digest computation failed: {e}")
        return None


async def _record_corridor_ok(peer_id: int) -> None:
    """Corridor freshness WITHOUT touching last_synced_at — the watermark skip
    proves the peer answered, not that we ingested anything."""
    try:
        from agentvault_registry.services import federation_reachability
        async with AsyncSessionLocal() as db:
            await federation_reachability.record_outcome(db, peer_id, ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[FED-SYNC] record_outcome(watermark ok) failed: {exc}")


_SYNC_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_card_updated_at(card: Any) -> Optional[datetime]:
    raw = card.get("updated_at") if isinstance(card, dict) else None
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _max_updated_at(cards: List[Any]) -> Optional[datetime]:
    best: Optional[datetime] = None
    for c in cards:
        dt = _parse_card_updated_at(c)
        if dt and (best is None or dt > best):
            best = dt
    return best


def _advance_cursor(prev: datetime, page_max: Optional[datetime]) -> Tuple[datetime, bool]:
    """Next `since` cursor after a FULL page. Returns (next_cursor, stalled).

    Normal: max(updated_at seen) − 1s — the overlap re-fetches boundary ties and
    costs nothing (unchanged cards are upsert NO-OPs). Stall (a bucket of cards
    denser than one page sharing ~the same second, or a page with no parseable
    timestamps): step STRICTLY past it so the walk always terminates; anything
    skipped is healed by the periodic reconcile."""
    if page_max is None:
        return prev + timedelta(seconds=1), True
    candidate = page_max - timedelta(seconds=1)
    if candidate <= prev:
        return page_max + timedelta(microseconds=1), True
    return candidate, False


def _count_overflow(mode: str) -> None:
    if FEDERATION_SYNC_WINDOW_OVERFLOW_TOTAL is None:
        return
    try:
        FEDERATION_SYNC_WINDOW_OVERFLOW_TOTAL.labels(
            registry=_fed_registry_label(), mode=mode
        ).inc()
    except Exception:
        pass


_EXPORT_VERSION_PREFIX = "registry:federation:export_version:"


async def _last_export_version(peer_name: str):
    """The export shape we last WALKED for this peer, or None the first time."""
    try:
        r = await _reconcile_redis()
        if r is None:
            return None
        v = await r.get(_EXPORT_VERSION_PREFIX + peer_name)
        return v.decode() if isinstance(v, (bytes, bytearray)) else v
    except Exception:  # noqa: BLE001 — never fail a sync on a bookkeeping read
        return None


async def _note_export_version(peer_name: str, version: str) -> None:
    try:
        r = await _reconcile_redis()
        if r is not None:
            await r.set(_EXPORT_VERSION_PREFIX + peer_name, version)
    except Exception:  # noqa: BLE001
        pass


_RECONCILE_NEXT_PREFIX = "registry:federation:reconcile_next:"
_RECONCILE_CURSOR_PREFIX = "registry:federation:reconcile_cursor:"


async def _reconcile_redis():
    """Fail-open Redis handle (same contract as the card-pull backoff: a broken
    cache must never stop — or start — federation work)."""
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        return await get_redis()
    except Exception:
        return None


async def _reconcile_get(key: str) -> Optional[str]:
    r = await _reconcile_redis()
    if r is None:
        return None
    try:
        raw = await r.get(key)
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
    except Exception:
        return None


async def _reconcile_set(key: str, value: str) -> None:
    r = await _reconcile_redis()
    if r is None:
        return
    try:
        await r.set(key, value)
    except Exception:
        pass


async def _reconcile_del(key: str) -> None:
    r = await _reconcile_redis()
    if r is None:
        return
    try:
        await r.delete(key)
    except Exception:
        pass


def is_peer_frames_operator(peer, peers) -> bool:
    """§BATCH8 item 4 (2026-09-06) — a `discovered` row that lives INSIDE a directly-federated peer
    FRAME's trust domain is that frame's own operator: its cards reach us through the frame's export
    (the hub-relay re-serves federated cards, §pass78c), and a direct pull of it is refused 401 every
    cycle by a proxy that never federated with us (measured on the fresh pair: `brrrop-a` on JUICE,
    `juiceop-a/b` on BRRR — parked 33 min per cycle, forever, the §9 residue). One predicate, module
    scope, like `is_own_reachable_op`: a row is skipped here iff it is tagged `discovered`, is not one
    of OUR own reachable ops, and its trust domain equals the trust domain of an ACTIVE `frame` row."""
    if (getattr(peer, "peer_type", "") or "").lower() != "discovered":
        return False
    if is_own_reachable_op(peer):
        return False
    td = (getattr(peer, "trust_domain", "") or "").strip().lower()
    if not td:
        return False
    frame_tds = {
        (getattr(p, "trust_domain", "") or "").strip().lower()
        for p in peers
        if (getattr(p, "peer_type", "") or "").lower() == "frame"
    }
    frame_tds.discard("")
    return td in frame_tds


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# §ECHO (2026-09-28) — how long after its last successful sync a peer still counts as our DIRECT source for its own
# cards. Past it (the peer stopped answering, or its walk is mid-overflow), relays are its source again, as before §ECHO.
DIRECT_SOURCE_FRESH_SEC = int(os.getenv("FEDERATION_DIRECT_SOURCE_FRESH_SEC", "600") or 600)


def direct_source_names(peers, now: Optional[datetime] = None) -> set:
    """§ECHO (2026-09-28) — the registries we pull agent cards from DIRECTLY and can rely on right now, case-folded.

    ACTIVE rows the cycle dials (a peer frame's own operators are served through their frame and never dialled,
    `is_peer_frames_operator`), with no failing streak, that answered a sync within DIRECT_SOURCE_FRESH_SEC. A card whose
    ORIGIN is one of these is taken only from that origin (see relayed_copy_of_direct_origin). Anything the rule cannot
    vouch for (never synced, gone quiet, failing) keeps the pre-§ECHO behaviour: relays are its source."""
    now = now or _utcnow()
    peers = list(peers or [])
    out = set()
    for p in peers:
        if (getattr(p, "status", "") or "").upper() != "ACTIVE":
            continue
        if is_peer_frames_operator(p, peers):
            continue
        if int(getattr(p, "consecutive_sync_failures", 0) or 0) > 0:
            continue
        ls = getattr(p, "last_synced_at", None)
        if not isinstance(ls, datetime):
            continue
        if ls.tzinfo is None:
            ls = ls.replace(tzinfo=timezone.utc)
        if (now - ls).total_seconds() > DIRECT_SOURCE_FRESH_SEC:
            continue
        name = (getattr(p, "name", "") or "").strip().casefold()
        if name:
            out.add(name)
    return out


def origin_name_of(agent_card) -> Optional[str]:
    """The card's HOME registry name: `federation_metadata.origin_registry_name`, stamped once at the home and kept
    through every relay (the same key the sync digest buckets by). None when the card names none."""
    cd = agent_card.get("card_data") if isinstance(agent_card, dict) else None
    fm = cd.get("federation_metadata") if isinstance(cd, dict) else None
    origin = fm.get("origin_registry_name") if isinstance(fm, dict) else None
    return origin.strip() if isinstance(origin, str) and origin.strip() else None


def is_origin_copy(agent_card, presenter_name) -> bool:
    """§ECHO — True when the presenter IS the card's home (names compared without case): the one copy that is the
    truth about the card, whatever the two registries' clocks say (see upsert_agent_cards_from_peer's from_origin)."""
    origin = origin_name_of(agent_card)
    return bool(origin) and origin.casefold() == (presenter_name or "").strip().casefold()


def relayed_copy_of_direct_origin(agent_card, presenter_name, direct_names) -> Optional[str]:
    """§ECHO (2026-09-28) — THE DIRECT COPY WINS. The card's origin name when this is a RELAYED copy (the presenter is
    not the origin) of a card whose origin we pull from directly; None for the origin's own copy, for an origin we do
    not pull from (a relay is its only source), and for a card that names no origin (as before).

    Measured on the sandbox pair: a frame took back from its OWN operator the stale copy of the other frame's card that
    the operator had pulled from it, over the fresh copy it had just taken from the card's home; a lifted suspension
    came back and stayed. The registry-card fan-out has had this rule since §FANOUTFIX; agent cards had none. The key
    is `federation_metadata.origin_registry_name` (origin_name_of), equal to our peer rows' names up to case ("ASIA"
    beside "asia"). A presenter we could not name ("") makes every copy of a direct origin a relay."""
    origin = origin_name_of(agent_card)
    if not origin or is_origin_copy(agent_card, presenter_name):
        return None
    return origin if origin.casefold() in (direct_names or ()) else None


async def peer_fetch_json(peer, path: str) -> Tuple[int, Any]:
    """§FEDLICENCE: GET `path` from a peer with the same auth the card sync uses (mTLS SVID on https, the licence or the
    internal secret on plain http). (status, json or None); 0 when no request could be made. Never raises."""
    base = (getattr(peer, "base_url", "") or "").rstrip("/")
    # the AUTHENTICATED lane's address (the one the agent-card sync dials): `_to_registry_dialable_url` is the card
    # pull's and strips an operator's parent's :8443 onto the public console, where no client certificate reaches the
    # registry (measured on V0478: both sandbox operators got 401 asking their parent for their licence). The card
    # pull's address stays as the fallback for a peer the mTLS lane cannot reach at all.
    from agentvault_registry.routers.teg_integration import _to_internal_mtls_url, _to_registry_dialable_url
    first = await _peer_get_json(_to_internal_mtls_url(base) + path)
    if first[0] != 0:
        return first
    alt = _to_registry_dialable_url(base) + path
    if alt == _to_internal_mtls_url(base) + path:
        return first
    return await _peer_get_json(alt)


async def _peer_get_json(url: str) -> Tuple[int, Any]:
    try:
        cfg: Dict[str, Any] = {"timeout": 8.0}
        headers: Dict[str, str] = {}
        if url.startswith("https://"):
            cert_cfg = svid_client.get_client_cert_config(target_url=url)
            if not cert_cfg:
                return 0, {"error": "no mTLS client certificate available"}
            cfg.update(cert_cfg)
        else:
            fed_license = os.environ.get("FEDERATION_LICENSE_KEY", "")
            if fed_license:
                headers["X-Federation-License"] = fed_license
            else:
                headers["X-Federation-Secret"] = os.environ.get("FEDERATION_INTERNAL_SECRET", "")
                headers["X-Federation-SPIFFE-ID"] = svid_client.get_spiffe_id() or ""
        async with httpx.AsyncClient(**cfg) as client:
            r = await client.get(url, headers=headers)
        try:
            body = r.json()
        except Exception:  # noqa: BLE001 — a non-JSON answer is reported by its status
            body = None
        return r.status_code, body
    except Exception as exc:  # noqa: BLE001 — a failed dial is a status, never an exception in a cycle
        return 0, {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}


async def licence_cycle() -> Dict[str, Any]:
    """§FEDLICENCE (2026-09-28): one verdict cycle. A FRAME refreshes the network root and the genesis's list and writes
    its own verdict and one per ACTIVE peer (services/federation_licence.refresh_frame_cycle) while its
    FEDERATION_LICENCE_MODE is not `off`. An OPERATOR asks its parent frame for its licence every cycle (the parent's own
    mode decides: it answers 409 while licensing is off there), so operators follow their frame with no env of their own."""
    from ..services import federation_licence as fl
    is_operator = bool((os.getenv("OPERATOR_DID") or "").strip())
    if not is_operator and fl.licence_mode() == "off":
        return {"skipped": "FEDERATION_LICENCE_MODE=off"}
    async with AsyncSessionLocal() as db:
        peers = list((await db.execute(
            select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE")
        )).scalars().all())
        if is_operator:
            parent = next((p for p in peers if is_my_parent_frame(p)), None)
            if parent is None:
                await db.rollback()
                return {"skipped": "an operator with no ACTIVE parent frame row"}
            status_code, body = await peer_fetch_json(parent, "/api/v1/federation/licence/mine")
            if status_code != 200 or not isinstance(body, dict):
                await db.rollback()
                return {"skipped": f"the parent frame answered HTTP {status_code}",
                        "detail": (body or {}).get("detail") if isinstance(body, dict) else None}
            out = await fl.install_from_parent(db, body)
            await db.commit()
            return {"mode": "operator", "self": {"state": (body.get("network") or {}).get("state")}, "installed": out}
        summary = await fl.refresh_frame_cycle(db, peers=peers, fetch_json=peer_fetch_json)
        await db.commit()
        await fl.save_summary(summary)
        return summary


def is_own_reachable_op(peer) -> bool:
    """Is this peer one of OUR OWN cloud-ops, i.e. dialable directly by us?

    True when its base_url host is `op-*.<our SPIRE_TRUST_DOMAIN>` — the identical
    dial path a correctly-tagged `cloud_operator` child uses. TRUE cross-frame ops
    live under someone else's trust domain and are False here (fan-out is their
    designed path).

    §MC-9 (2026-06-25) introduced this test to pull rename-artifact ops that are
    mis-tagged `peer_type='discovered'` (op-newyork / op-losangeles on frame-b)
    into the DIRECT registry-card sync. §FANOUTFIX (2026-08-05) hoists it to module
    scope because the fan-out's own protection guard MUST ask the same question —
    see the call site in the fan-out for the stale-beats-fresh loop that resulted
    from the two predicates disagreeing.
    """
    try:
        from urllib.parse import urlsplit
        own_td = (os.getenv("SPIRE_TRUST_DOMAIN") or "").strip().lower()
        host = (urlsplit(getattr(peer, "base_url", "") or "").hostname or "").lower()
        return bool(own_td) and host.startswith("op-") and host.endswith("." + own_td)
    except Exception:  # noqa: BLE001 — a predicate must never break a sync cycle
        return False


def is_my_parent_frame(peer) -> bool:
    """findings row 187's MIRROR (§TWOAGENT, 2026-09-24). Row 187 let a frame accept its OWN operators' cards, which
    declare the frame's issuer namespace by design; nothing let an operator accept its PARENT's card, which declares
    the same namespace for the same reason. Measured on production: every operator refused its parent's card
    `did_namespace_self` on every two-minute card-sync cycle (30 an hour each), so none of the four had ever held its parent's card,
    signature or logo, while each held the other frame's; the sandbox operators' parent cards froze on 09-12/13 the
    same way (with no namespace set the guard reads the trust domain).

    Decided by THIS registry's own configuration and OUR peer row, never by the card: we are an operator (OPERATOR_DID
    is set, which the provisioner writes on operators only, and we are not a mainframe), the row is a `frame`, and its
    trust domain is our own SPIFFE trust domain, which only our parent's can be (measured: one such row on each of the
    six running operators, its parent). V0440: V0439 also required FEDERATION_OPERATOR_ID, which every running
    operator carries EMPTY (a census of variable NAMES could not see it), so the allowance never applied anywhere.
    """
    try:
        if (getattr(peer, "peer_type", "") or "").lower() != "frame":
            return False
        if not (os.getenv("OPERATOR_DID") or "").strip():
            return False
        own_td = (os.getenv("SPIRE_TRUST_DOMAIN") or "").strip().lower()
        td = (getattr(peer, "trust_domain", "") or "").strip().lower()
        if not own_td or td != own_td:
            return False
        from ..core.mainframe_gate import is_mainframe
        return not is_mainframe()
    except Exception:  # noqa: BLE001 — a predicate must never break a sync cycle
        return False


def _reconcile_jitter_frac(peer_name: str) -> float:
    """Deterministic per-peer fraction in [0,1) — staggers due times without state."""
    import hashlib
    h = hashlib.sha256(peer_name.encode()).digest()
    return h[0] / 256.0


async def _walk_pages(*, fetch_page, process_page, stamp_progress, stamp_caught_up,
                      start_cursor: datetime, page_limit: int, max_pages: int,
                      mode: str, peer_name: str = "?") -> str:
    """Drive a cursor walk over /federation/agent-cards pages.

    Returns "caught_up" (delta fully consumed), "budget" (page budget hit —
    the cursor was persisted after every page, so the next cycle RESUMES), or
    "failed" (HTTP/processing error; nothing stamped beyond completed pages).
    Extracted module-level for testability: scripts/federation_paged_sync_test.py
    drives it against a synthetic server (§STREAKFIX rule — state machines get
    N-transition tests; the truncation bug lived exactly in transition 2+)."""
    cursor = start_cursor
    pages = 0
    while pages < max_pages:
        status, cards, srv_more, srv_cursor = await fetch_page(cursor)
        if status != 200:
            return "failed"
        pages += 1
        if cards and not await process_page(cards):
            return "failed"
        # End-of-data: prefer the server's truth header — the export's echo
        # filter shrinks pages AFTER the SQL limit, so a short (or even empty)
        # page can still have data behind it (live E2E: 484 of a 500-limit page
        # with 7.4k rows remaining). The len>=limit heuristic remains only as
        # the old-server fallback, where it degrades to pre-§SYNCPAGE behavior.
        has_more = srv_more or len(cards) >= page_limit
        if not has_more:
            await stamp_caught_up()
            return "caught_up"
        _count_overflow(mode)
        page_max = srv_cursor or _max_updated_at(cards)
        cursor, stalled = _advance_cursor(cursor, page_max)
        if stalled:
            logger.warning(
                f"Paged sync with {peer_name}: dense/unparseable updated_at bucket around "
                f"{page_max} — stepping strictly past it (the periodic reconcile heals any skipped ties)"
            )
        await stamp_progress(cursor)
    return "budget"


async def _refresh_federation_gauges(db: AsyncSession) -> None:
    """Refresh federation_* gauges from peer_registries + federation_licenses tables.

    Cheap query; runs alongside the sync cycle (every FEDERATION_SYNC_INTERVAL_SECONDS).
    """
    if not _FED_PROM_AVAILABLE:
        return
    registry = _fed_registry_label()
    try:
        # Peers grouped by status. DB stores statuses uppercase
        # (ACTIVE / INACTIVE / PENDING_APPROVAL / REJECTED / SUSPENDED / REVOKED);
        # gauge labels are emitted lowercase for downstream dashboards.
        stmt = select(models.PeerRegistry.status, func.count(models.PeerRegistry.id)).group_by(
            models.PeerRegistry.status
        )
        result = await db.execute(stmt)
        peers_by_status_raw = dict(result.all())
        peers_by_status = {
            (k.lower() if isinstance(k, str) else k): v
            for k, v in peers_by_status_raw.items()
        }
        # PENDING_APPROVAL → "pending" for dashboard symmetry
        if "pending_approval" in peers_by_status:
            peers_by_status["pending"] = peers_by_status.pop("pending_approval") + peers_by_status.get("pending", 0)
        # Reset known statuses + set actual values
        for st in ("active", "inactive", "pending", "suspended", "revoked"):
            FEDERATION_PEERS_TOTAL.labels(status=st, registry=registry).set(
                int(peers_by_status.get(st, 0))
            )

        # Federation license states (if model is present)
        try:
            from .. import models as _m
            if hasattr(_m, "FederationLicense"):
                stmt2 = select(_m.FederationLicense.status, func.count(_m.FederationLicense.id)).group_by(
                    _m.FederationLicense.status
                )
                r2 = await db.execute(stmt2)
                lic_by_state_raw = dict(r2.all())
                lic_by_state = {
                    (k.lower() if isinstance(k, str) else k): v
                    for k, v in lic_by_state_raw.items()
                }
                for st in ("active", "suspended", "revoked", "expired"):
                    FEDERATION_LICENSE_PEERS_TOTAL.labels(
                        license_state=st, registry=registry
                    ).set(int(lic_by_state.get(st, 0)))
        except Exception as e:
            logger.debug(f"[FederationGauges] license rollup failed: {e}")
    except Exception as e:
        logger.debug(f"[FederationGauges] refresh failed: {e}")


_REACH_WARNED_AT: List[Optional[float]] = [None]


async def _publish_reachability() -> None:
    """§REACHGAUGE (2026-09-28): publish the corridor reachability gauges once per sync cycle.

    FederationPeerNeverSynced, FederationPeerStale and FederationCorridorDegraded read gauges that
    only a USER read published (a federated discovery search, the compliance view). Measured
    2026-09-28: not one such series on EU, ASIA or their four operators, so the three alerts could
    not fire in production; and sbx-beta's froze at a 17:22Z read and kept firing on a row that went
    INACTIVE at 17:59Z. The cycle is the one clock every registry runs. Its own session, so a
    failure here cannot poison the cycle's; loud once per ten minutes, never fatal.
    """
    try:
        from agentvault_registry.services import federation_reachability
        async with AsyncSessionLocal() as rdb:
            await federation_reachability.build_report(rdb, include_ok=True)
    except Exception as exc:  # noqa: BLE001 — a metric must never break the cycle
        now_m = _time_mod.monotonic()
        if _REACH_WARNED_AT[0] is None or now_m - _REACH_WARNED_AT[0] > 600:
            _REACH_WARNED_AT[0] = now_m
            logger.warning(f"[FED-SYNC] reachability publish failed, the corridor gauges are "
                           f"not moving: {exc}")


_OPERATOR_IDENTITY_RE = re.compile(r"^spiffe://([^/\s]+)/operator/([^/\s]+)(?:/|$)", re.IGNORECASE)


def is_operator_peer(peer, own_trust_domain: str = "") -> bool:
    """A peer row the trust sync must not name by its trust domain: typed cloud_operator, stamped with an
    /operator/<name>/ SVID, or sharing this registry's own trust domain. On a frame such a row is one of its operators;
    on an operator it is its parent frame or a sibling operator. The bare domain names none of them alone (every operator
    of a frame shares it), so the payload names the peer by its own SVID or by nothing (operator_store_identity)."""
    if str(getattr(peer, "peer_type", None) or "").strip().lower() == "cloud_operator":
        return True
    if _OPERATOR_IDENTITY_RE.match(str(getattr(peer, "spiffe_id", None) or "").strip()):
        return True
    own = (own_trust_domain or "").strip().lower()
    return bool(own) and str(getattr(peer, "trust_domain", None) or "").strip().lower() == own


def operator_store_identity(peer, own_trust_domain: str = "") -> Optional[str]:
    """The SPIFFE identity an operator presents to its parent frame's event store: spiffe://<td>/operator/<name>/svid-writer,
    the SVID its cert-writer writes to the /certs volume that its registry and its TEG both present (es_ssl_helper; the
    operator compose mounts svid-certs:/certs into both), and the identity the provisioner's licence sync leaves on the
    store row (services/cloud_provisioner.py, the registry sync then the svid-writer sync). The <name> is read from the
    SVID the peer row was stamped with at activation (PeerRegistry.spiffe_id, S3: spiffe://<td>/operator/<name>/registry,
    the same <name> as the operator's SPIRE entries). None when the row carries no such stamp, or when the stamp's domain
    is not the peer's trust domain or this frame's own: no identity is better than a wrong one."""
    m = _OPERATOR_IDENTITY_RE.match(str(getattr(peer, "spiffe_id", None) or "").strip())
    if not m:
        return None
    domain, name = m.group(1).lower(), m.group(2)
    for expected in (getattr(peer, "trust_domain", None), own_trust_domain):
        exp = str(expected or "").strip().lower()
        if exp and exp != domain:
            return None
    return f"spiffe://{domain}/operator/{name}/svid-writer"


def trust_sync_payloads(peers, licences, own_trust_domain: str = "",
                        now: Optional[datetime] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """SF-5B's store updates (§MTLSHOPS (c)): one per licence this frame issued to a peer, keyed by the LICENCE id the event
    store holds. A peer matches a licence by name, exactly, or case-insensitively when that match is unique. Returns
    (payloads, skipped peer names). A revoked licence, an ambiguous name and a licence already claimed by an earlier peer
    are skipped. A payload carries id, operator_name, bayesian_discount and the peer's identity as spiffe_id (§TRUSTROW):
    a peer frame its trust domain, spiffe://<td>; one of this frame's own operators its own SVID (operator_store_identity),
    or no spiffe_id at all when that cannot be read from its row.

    SEC-20 (2026-10-17, his word: "it has to be dervied in a meaningful way. setting it manually doesnt make sense to
    me"): the bayesian_discount sent is DERIVED here from the peer's recorded outcomes and the clock
    (services/bayesian_trust.derived_trust_for), never read from the peer row's column, so a value written into that
    column by anything is never what the store weighs the peer's votes by. A peer with no record sends the prior, 0.5.

    2026-10-17: an own operator was sent spiffe://<td> as well, the frame's BARE domain, which every operator of the frame
    shares. The store finds a row by that id first, so one operator's row took every same-domain operator's update every
    cycle, its name flipping and its identity replaced by the bare domain (measured: lisbon's row on EU, shenzhen's on
    ASIA, sbxalphaop's and sbxbetaop's on the sandbox), and a store that accepts no operator without its record refuses
    that operator. Without a spiffe_id the store finds the row by the licence id alone and leaves its identity as the
    provisioner wrote it."""
    by_lower: Dict[str, List[Tuple[str, str]]] = {}
    for lid, lname, lstatus in licences:
        status = str(getattr(lstatus, "value", lstatus) or "").strip().lower()
        if not lid or not lname or status == "revoked":
            continue
        by_lower.setdefault(str(lname).strip().lower(), []).append((str(lid), str(lname)))
    payloads: List[Dict[str, Any]] = []
    skipped: List[str] = []
    seen = set()
    for peer in peers:
        name = str(getattr(peer, "name", None) or "").strip()
        cands = by_lower.get(name.lower(), [])
        exact = [c for c in cands if c[1] == name]
        pick = exact if len(exact) == 1 else (cands if len(cands) == 1 else [])
        if len(pick) != 1 or pick[0][0] in seen:
            skipped.append(name or "?")
            continue
        lid, lname = pick[0]
        seen.add(lid)
        payload = {"id": lid, "operator_name": lname, "bayesian_discount": derived_trust_for(peer, now)}
        # §TRUSTROW (2026-09-16, his word "approved ... dont change the overall mechanism"): name the peer as well as
        # the licence. The event store's vote weight resolves a voter by its SPIFFE id, so a payload carrying only the
        # licence id updates a row nothing reads (measured: EU held two rows for ASIA, the read one at the prior). The
        # licence still decides which row this is about; this only lets the store find the peer's own row.
        # An operator is named by its own SVID, never by the domain it shares with every other operator of the frame.
        if is_operator_peer(peer, own_trust_domain):
            ident = operator_store_identity(peer, own_trust_domain)
            if ident:
                payload["spiffe_id"] = ident
        else:
            td = str(getattr(peer, "trust_domain", None) or "").strip()
            if td:
                payload["spiffe_id"] = f"spiffe://{td}"
        payloads.append(payload)
    return payloads, skipped



def fanout_peer_row_match(peer_name, entry_base_url):
    """The predicates that tie a registry-card fan-out entry to an EXISTING peer row (§HELLOFRAME D3,
    2026-09-18): the name, compared case-insensitively, exactly as `fanout_peer_name_allowed`
    (core/operator_names.py) compares it, OR the base_url with or without a trailing slash (the join key
    that is stable across both frames' views, §2026-05-30). Returns a list for `or_(*...)`.

    Why the case: a frame's own card carries `identity.registry_name` (`REGISTRY_FEDERATION_NAME` or
    `REGISTRY_NAME`, e.g. `ASIA`) while the row the invitation rail wrote for it carries the invitation's
    `name` (e.g. `asia`), and the two base_urls differ too (the card's public console URL against the
    federation lane the row dials), so the old exact-name match plus the base_url match found nothing and
    the receiver inserted a `discovered` twin. Measured 2026-09-18: EU held `ASIA` beside `asia`, ASIA held
    `EU` beside `eu`, both twins parked INACTIVE as `duplicate_frame`. `lower()` on `peer_registries.name`
    is a per-entry query on a table of dozens of rows; no index is needed for it.
    """
    match = [func.lower(models.PeerRegistry.name) == str(peer_name or "").strip().lower()]
    base = (entry_base_url or "").rstrip("/")
    if base:
        match.append(models.PeerRegistry.base_url.in_([base, base + "/"]))
    return match



def _spiffe_td(spiffe: Optional[str]) -> str:
    v = (spiffe or "").strip().lower()
    return v[len("spiffe://"):].split("/", 1)[0] if v.startswith("spiffe://") else ""


async def _stock_card_row(db: AsyncSession, source_spiffe: str, peer_name: Optional[str]):
    """The FederatedStockCard row of this source: by its card spiffe; else the ONE row the same peer (same name, same
    trust domain) filed under another spiffe, re-keyed to this one; else None (the caller creates it).

    §MEMBERSHIP (V0560): a cloud operator's card spiffe moved from its container label to its federation name
    (registry_card_builder._build_spiffe_id), and source_spiffe_id is unique, so a new row would list the operator's
    catalog twice, the old copy going stale."""
    row = (await db.execute(select(models.FederatedStockCard).where(
        models.FederatedStockCard.source_spiffe_id == source_spiffe))).scalar_one_or_none()
    if row is not None:
        return row
    td = _spiffe_td(source_spiffe)
    name = (peer_name or "").strip().lower()
    if not td or not name:
        return None
    olds = [r for r in (await db.execute(select(models.FederatedStockCard).where(
        func.lower(models.FederatedStockCard.source_registry_name) == name))).scalars().all()
        if _spiffe_td(r.source_spiffe_id) == td]
    if len(olds) == 1:
        logger.info("[StockCardSync] peer=%s card spiffe moved %s -> %s: row re-keyed", peer_name,
                    olds[0].source_spiffe_id, source_spiffe)
        olds[0].source_spiffe_id = source_spiffe
        return olds[0]
    return None

class FederationSyncWorker(BackgroundWorker):
    """Manages periodic synchronization with federation peers
    (§pass29 Phase 6: BackgroundWorker)."""

    worker_id = "federation_sync"
    leader_key = "federation_sync"
    # Wait 10s after startup to let the server fully initialize.
    cold_start_delay_sec = 10

    def __init__(self):
        super().__init__()
        # Phase 4 reactor framework: read FEDERATION_SYNC_INTERVAL_SECONDS from env directly
        # so it can be tuned without modifying Pydantic Settings (Settings only binds declared fields).
        # Default 300s (5 min). With reactors driving the hot path, this is now a backup pull.
        env_override = os.getenv('FEDERATION_SYNC_INTERVAL_SECONDS')
        self.sync_interval = int(
            # §FEDSYNC-V2 (2026-08-05): source default 300 → 600. With the
            # watermark fast-path a cycle against quiet peers is ~one tiny
            # request each; the interval matters mostly for how fast a REAL
            # change propagates, and 10 min mesh-wide is plenty on one host.
            env_override if env_override else getattr(settings, 'FEDERATION_SYNC_INTERVAL_SECONDS', 600)
        )
        # Wire the base class's interval to the runtime-resolved one (must be
        # done in __init__ since the class attr is a static default).
        self.interval_sec = self.sync_interval
        self.httpx_timeout = 30.0  # Longer timeout for sync operations

        # P3-004: Use the existing async session factory instead of fragile URL string manipulation
        logger.info(f"FederationSyncWorker initialized: interval={self.sync_interval}s")

    async def _cycle_once(self) -> None:
        await self._perform_sync_cycle()
        # §TRUSTPOLICY — the clock. The ingest gate only sees a peer when cards
        # flow, so a QUIET peer could cross a threshold and nobody would hear it.
        # This sweep reports TRANSITIONS only; emitting every pass would make the
        # ledger a heartbeat nobody reads.
        try:
            from ..services.peer_trust_policy import sweep as _trust_sweep
            async with AsyncSessionLocal() as _tdb:
                await _trust_sweep(_tdb)
        except Exception as _ts_e:  # noqa: BLE001 — trust must never break the cycle
            logger.warning(f"[TRUSTPOLICY] sweep pass failed: {_ts_e}")
        # §SYNCPAGE — at most ONE peer reconciled per cycle, jitter-staggered.
        try:
            await self._maybe_reconcile_one_peer()
        except Exception as _rc_e:  # noqa: BLE001 — reconcile must never break the cycle
            logger.warning(f"[FED-SYNC] reconcile pass failed: {_rc_e}")
        self._stats = dict(_LAST_CYCLE_STATS)

    async def _stamp_walk_complete(self, peer_name: str, now_ts: float,
                                   legacy_interval: float, digest_interval: float) -> None:
        """A read-repair walk finished for this peer: push the legacy clock out a
        full interval, and (when digests are on) schedule a VERIFY check soon —
        a heal whose next digest still mismatches is how persistent divergence
        is detected. The missfail counter is deliberately NOT cleared here;
        only a digest_equal clears it.

        §DIGESTSTALL (2026-09-28): the verify check never pulls an already-later
        check EARLIER. A walk taken at the backed-off cadence scheduled its next
        check before it walked; a walk that paused on its budget and finished in
        a later cycle (branch 1) must not turn that back into a check every hour."""
        if legacy_interval > 0:
            await _reconcile_set(
                _RECONCILE_NEXT_PREFIX + peer_name,
                str(now_ts + legacy_interval * (0.9 + 0.2 * _reconcile_jitter_frac(peer_name))),
            )
        if digest_interval > 0:
            verify_at = now_ts + max(1800.0, digest_interval * 0.05)
            try:
                scheduled = float(await _reconcile_get(_DIGEST_NEXT_PREFIX + peer_name) or "")
            except ValueError:
                scheduled = None
            if scheduled is None or scheduled < verify_at:
                await _reconcile_set(_DIGEST_NEXT_PREFIX + peer_name, str(verify_at))
        logger.info(f"[FED-SYNC] reconcile walk for {peer_name} complete")

    async def _maybe_reconcile_one_peer(self) -> None:
        """§SYNCPAGE + §FEDSYNC-V2 — the standing completeness guarantee.

        Incremental sync can silently lose a card forever (a miss lands BEHIND
        the cursor and is never offered again — the §SYNCPAGE truncation
        class), so SOMETHING must periodically answer "do our corpora differ?".

        §SYNCPAGE answered it by re-walking each peer's entire corpus every
        FEDERATION_FULL_RECONCILE_DAYS — ~8,900 cards × every peer, to almost
        always discover nothing. §FEDSYNC-V2 answers it with a per-origin
        digest comparison (one query each side): equal ⇒ that comparison IS
        the reconcile and the walk is deferred a full legacy interval;
        mismatch ⇒ the UNCHANGED read-repair walk machinery runs, followed by
        a verify check. A mismatch that survives repeated heals (legitimate
        divergence: cross-frame reach asymmetry, GC windows) backs off with a
        WARN to a walk every 3-7 intervals instead of one every hour.

        §DIGESTSTALL (2026-09-28, measured on production after V0484): the back-off
        used to stop walking FOR GOOD. The miss counter clears only on an equal
        digest, a divergence that only a walk can heal never becomes equal, so
        after two walks that failed to heal (on older code) a peer was never
        walked again: ASIA's counters read 6 for every peer, EU's 4-6, the
        operators' 3-7, and a mirror stuck since 2026-09-12 could not heal on
        V0484, which WOULD heal it on the next walk. Now a backed-off check still
        walks once, at its own cadence, and a new image gets one fresh look per
        peer within hours (a fix that ships must get a chance to heal).

        Peers that 404 /sync-digest (pre-§FEDSYNC-V2 code) keep the legacy
        timed walk EXACTLY as before — the guarantee never degrades to
        "assume in sync". At most one peer is acted on per cycle; all clocks
        are per-peer jittered; fail-open on Redis loss (skip)."""
        legacy_interval = _reconcile_interval_seconds()
        digest_interval = _digest_interval_seconds()
        if legacy_interval <= 0 and digest_interval <= 0:
            return
        r = await _reconcile_redis()
        if r is None:
            return
        now_ts = _time_mod.time()
        try:
            async with AsyncSessionLocal() as db:
                peers = await crud_peer_registry.list_active_peer_registries_all(db, skip=0, limit=1000)
        except Exception as e:
            logger.debug(f"[FED-SYNC] reconcile peer listing failed: {e}")
            return
        our_spiffe_id = svid_client.get_spiffe_id() or "spiffe://agentvault.com/ns/agentvault/sa/registry-main"
        for peer in peers:
            # (1) A walk already in flight resumes before any clock is consulted
            #     (budget-paused cursors must never starve behind digest checks).
            cursor_left = await _reconcile_get(_RECONCILE_CURSOR_PREFIX + peer.name)
            if cursor_left is not None:
                result = await self._sync_with_peer(peer, our_spiffe_id, reconcile=True)
                still = await _reconcile_get(_RECONCILE_CURSOR_PREFIX + peer.name)
                if result is True and still is None:
                    await self._stamp_walk_complete(peer.name, now_ts, legacy_interval, digest_interval)
                return  # one peer per cycle, always

            # (2) Digest-first path.
            digest_capable = False
            if digest_interval > 0:
                unsup = await _reconcile_get(_DIGEST_UNSUP_PREFIX + peer.name)
                digest_capable = unsup is None
            if digest_capable:
                dkey = _DIGEST_NEXT_PREFIX + peer.name
                draw = await _reconcile_get(dkey)
                if draw is None:
                    # First sighting: check soon-ish (2–10% of the interval) so a
                    # fresh boot proves the path within hours, then settles to
                    # the full cadence.
                    seed = now_ts + digest_interval * (0.02 + 0.08 * _reconcile_jitter_frac(peer.name))
                    await _reconcile_set(dkey, str(seed))
                    continue
                try:
                    ddue = float(draw)
                except ValueError:
                    await _reconcile_set(dkey, str(now_ts + digest_interval))
                    continue
                # §DIGESTSTALL — a new image gets ONE fresh look at this peer within hours, whatever the back-off
                # says: the code that failed to heal a divergence may not be the code running now.
                image = _running_image_tag()
                if image and await _reconcile_get(_DIGEST_IMAGE_PREFIX + peer.name) != image:
                    await _reconcile_set(_DIGEST_IMAGE_PREFIX + peer.name, image)
                    soon = now_ts + digest_interval * (0.02 + 0.08 * _reconcile_jitter_frac(peer.name))
                    if ddue > soon:
                        ddue = soon
                        await _reconcile_set(dkey, str(soon))
                if now_ts < ddue:
                    continue
                verdict = await self._sync_with_peer(peer, our_spiffe_id, digest_probe=True)
                if verdict == "digest_equal":
                    await _reconcile_set(dkey, str(
                        now_ts + digest_interval * (0.9 + 0.2 * _reconcile_jitter_frac(peer.name))
                    ))
                    if legacy_interval > 0:
                        # The comparison IS the reconcile: defer the full walk.
                        await _reconcile_set(_RECONCILE_NEXT_PREFIX + peer.name,
                                             str(now_ts + legacy_interval))
                    await _reconcile_del(_DIGEST_MISS_PREFIX + peer.name)
                    return
                if verdict == "digest_mismatch":
                    miss_raw = await _reconcile_get(_DIGEST_MISS_PREFIX + peer.name)
                    miss = (int(miss_raw) + 1) if (miss_raw or "").isdigit() else 1
                    await _reconcile_set(_DIGEST_MISS_PREFIX + peer.name, str(miss))
                    if miss > 2:
                        backoff_mult = min(miss, 7)
                        logger.warning(
                            f"[FED-DIGEST] {peer.name}: mismatch persists after "
                            f"{miss - 1} repair walk(s) — likely legitimate divergence "
                            f"(cross-frame reach asymmetry / GC window); walking once more, next check in "
                            f"{backoff_mult}x the normal interval"
                        )
                        # §DIGESTSTALL — schedule the backed-off check FIRST, then walk: the walk's verify stamp
                        # never pulls a later check earlier (_stamp_walk_complete), so the cadence holds even when
                        # the walk pauses on its budget and finishes through branch (1).
                        await _reconcile_set(dkey, str(now_ts + digest_interval * backoff_mult))
                        result = await self._sync_with_peer(peer, our_spiffe_id, reconcile=True)
                        still = await _reconcile_get(_RECONCILE_CURSOR_PREFIX + peer.name)
                        if result is True and still is None:
                            await self._stamp_walk_complete(peer.name, now_ts, legacy_interval, digest_interval)
                        return
                    logger.info(f"[FED-SYNC] digest mismatch → read-repair walk starting for {peer.name}")
                    result = await self._sync_with_peer(peer, our_spiffe_id, reconcile=True)
                    still = await _reconcile_get(_RECONCILE_CURSOR_PREFIX + peer.name)
                    if result is True and still is None:
                        await self._stamp_walk_complete(peer.name, now_ts, legacy_interval, digest_interval)
                    # Budget-paused walks resume via branch (1) next cycle.
                    return
                if verdict == "digest_unsupported":
                    try:
                        await r.set(_DIGEST_UNSUP_PREFIX + peer.name, "1", ex=25 * 3600)
                    except Exception:
                        pass
                    await _reconcile_set(dkey, str(now_ts + digest_interval))
                    logger.info(
                        f"[FED-DIGEST] {peer.name} pre-dates the digest endpoint — "
                        f"keeping the legacy timed reconcile for it"
                    )
                    # Fall through to (3): the legacy clock governs this peer.
                else:
                    # False / "skipped" — network trouble or the card-pull
                    # backoff. Short retry so a transient blip doesn't cost a
                    # full check interval.
                    await _reconcile_set(dkey, str(now_ts + digest_interval * 0.1))
                    if verdict == "skipped":
                        continue  # backoff refused pre-flight: no action spent
                    return

            # (3) Legacy timed walk — digest disabled for us, or this peer
            #     doesn't serve digests. Byte-for-byte the §SYNCPAGE behavior.
            if legacy_interval <= 0:
                continue
            key = _RECONCILE_NEXT_PREFIX + peer.name
            raw = await _reconcile_get(key)
            if raw is None:
                # First sighting: seed a staggered due time (0.3–1.0 × interval)
                # so a fresh fleet doesn't reconcile everyone the same day.
                seed = now_ts + legacy_interval * (0.3 + 0.7 * _reconcile_jitter_frac(peer.name))
                await _reconcile_set(key, str(seed))
                continue
            try:
                due_ts = float(raw)
            except ValueError:
                await _reconcile_set(key, str(now_ts + legacy_interval))
                continue
            if now_ts < due_ts:
                continue
            logger.info(f"[FED-SYNC] reconcile walk starting for peer {peer.name}")
            result = await self._sync_with_peer(peer, our_spiffe_id, reconcile=True)
            cursor_left = await _reconcile_get(_RECONCILE_CURSOR_PREFIX + peer.name)
            if result is True and cursor_left is None:
                await self._stamp_walk_complete(peer.name, now_ts, legacy_interval, digest_interval)
            # else: budget-paused (cursor persists) or failed → stays due,
            # the next cycle resumes/retries.
            return  # one peer per cycle, always
    
    async def _perform_sync_cycle(self):
        """Perform a complete sync cycle with all active peers."""
        cycle_t0 = _time_mod.time()
        cycle_start_iso = datetime.now(timezone.utc).isoformat()
        logger.info("Starting federation sync cycle")

        # Reset stats for this cycle.
        _LAST_CYCLE_STATS.update({
            "last_cycle_iso": cycle_start_iso,
            "active_peers": 0,
            "license_gated_skipped": 0,
            "success_count": 0,
            "error_count": 0,
            "watermark_skipped": 0,
            "cycle_error": None,
        })
        registry_label = _fed_registry_label()
        if FEDERATION_SYNC_CYCLE_TOTAL is not None:
            try:
                FEDERATION_SYNC_CYCLE_TOTAL.labels(registry=registry_label).inc()
            except Exception:
                pass

        # §REACHGAUGE — before anything that can return early: a registry with no SPIFFE identity,
        # or no peer left to sync, is exactly the one whose corridors must go on being reported.
        await _publish_reachability()

        # Get our SPIFFE ID
        our_spiffe_id = svid_client.get_spiffe_id()
        if not our_spiffe_id:
            logger.error("Cannot perform federation sync without SPIFFE identity")
            _LAST_CYCLE_STATS["cycle_error"] = "no_spiffe_id"
            if FEDERATION_SYNC_ERRORS_TOTAL is not None:
                try:
                    FEDERATION_SYNC_ERRORS_TOTAL.labels(
                        registry=registry_label, reason="no_spiffe_id"
                    ).inc()
                except Exception:
                    pass
            return
        
        # P3-004: Use async session instead of sync SessionLocal
        async with AsyncSessionLocal() as db:
            try:
                # Refresh dashboard gauges (peers-by-status, licenses-by-state) before sync work
                await _refresh_federation_gauges(db)

                # Get all active peer registries using async CRUD.
                # §pass78c (2026-06-06): use the *_all variant (frame/direct_peer/
                # cloud_operator/discovered) — NOT the T8-filtered direct-only list.
                # The filtered list excludes parented cloud_operator children +
                # 'discovered' peers, which broke the peer-to-peer agent-card RELAY
                # chain: a frame never pulled the cards of its hop-depth ME-op
                # children (e.g. frame-c never pulled op-doha after the §pass78c
                # hop-depth parent_registry_id chain), so their cards never relayed
                # up the mesh → cross-frame op→op FX egress could not resolve the
                # foreign receiver (A→C 409). The OWL24/OWL30 hub-relay serving code
                # (get_agent_cards_for_sync) already re-serves federated cards to
                # non-source peers, so this is the intended multi-hop propagation.
                # Registry-card sync already uses *_all (:339); this restores parity.
                # NOTE: the T8 direct-only filter REMAINS on the public
                # /federation/peers advertise path (federation_peers.py) — we only
                # widen who WE pull from, not who we advertise (BFS determinism intact).
                active_peers = await crud_peer_registry.list_active_peer_registries_all(db, skip=0, limit=1000)

                if not active_peers:
                    logger.info("No active peer registries to sync with")
                    return

                # Option D-light Phase D6 (2026-04-21): skip peers whose federation
                # license is not active. Existing cached agent cards remain locally
                # (historical view preserved); fresh sync is blocked until the peer
                # is reinstated. Uses the silent variant + emits one audit event
                # per skipped peer per hour via assert helper.
                from agentvault_registry.services.federation_license_gate import (
                    resolve_peer_operator_did, is_peer_license_active, assert_peer_license_active,
                )
                gated_peers = []
                for peer in active_peers:
                    try:
                        operator_did = await resolve_peer_operator_did(db, peer)
                        if operator_did is None:
                            # No DID resolvable — keep peer (don't block on missing metadata)
                            gated_peers.append(peer)
                            continue
                        if await is_peer_license_active(db, operator_did):
                            gated_peers.append(peer)
                        else:
                            logger.info(
                                f"[FederationSync] Skipping peer {peer.name} "
                                f"({operator_did}) — license not active"
                            )
                            # Best-effort audit emission (hourly-deduped)
                            try:
                                await assert_peer_license_active(
                                    db=db, operator_did=operator_did,
                                    context="federation_sync",
                                )
                            except Exception:
                                # assert_peer_license_active raises by design; we only
                                # wanted the audit emission side-effect. Swallow so the
                                # sync cycle continues.
                                pass
                    except Exception as exc:
                        logger.warning(
                            f"[FederationSync] License gate check failed for peer "
                            f"{getattr(peer, 'name', '?')}: {exc} — including anyway"
                        )
                        gated_peers.append(peer)

                skipped = len(active_peers) - len(gated_peers)
                if skipped > 0:
                    logger.info(
                        f"[FederationSync] License gate: {skipped} peer(s) skipped, "
                        f"{len(gated_peers)} remaining"
                    )
                active_peers = gated_peers
                # §BATCH8 item 4 — the peer frame's own operators arrive through the frame; a direct
                # pull of them is a 401 and a 33-minute park, every cycle.
                _peer_ops = [p for p in active_peers if is_peer_frames_operator(p, active_peers)]
                if _peer_ops:
                    logger.info(
                        "[FederationSync] skipping %d peer-frame operator(s) (served through their frame): %s",
                        len(_peer_ops), ", ".join(getattr(p, "name", "?") for p in _peer_ops),
                    )
                    active_peers = [p for p in active_peers if p not in _peer_ops]
                if not active_peers:
                    logger.info("No license-active peer registries to sync with")
                    return

                logger.info(f"Syncing with {len(active_peers)} peer registries")
                
                # Sync with each peer concurrently
                # §2026-06-15 BOUNDED fan-out — cap concurrent peer syncs to
                # avoid the agent_cards FOR UPDATE convoy. Each peer batch takes
                # row locks on overlapping federated cards; an unbounded gather
                # over ~16 peers piled 100+ lock-waiters on hot rows under memory
                # pressure (pegged registry-a CPU). Mirrors the per-worker
                # FX_ROUTE_MAX_CONCURRENCY pattern. Tunable, no rebuild:
                # FEDERATION_SYNC_MAX_CONCURRENCY (default 3).
                # §2026-06-21 idle-in-txn fix: commit the prep-read transaction and
                # release the connection BEFORE the per-peer network fan-out, so no
                # connection sits idle-in-transaction during slow cross-frame I/O
                # (registry-a PG idle_in_transaction_session_timeout=60s was reaping it).
                await db.commit()
                _sync_sem = asyncio.Semaphore(
                    # §FEDSYNC-V2 (2026-08-05): default 3 → 2. This semaphore's own
                    # history says it exists because of "pegged registry-a CPU" —
                    # 18 registries × 3 = up to 54 concurrent pulls on one host.
                    max(1, int(os.getenv("FEDERATION_SYNC_MAX_CONCURRENCY", "2")))
                )

                async def _bounded_sync(_peer):
                    async with _sync_sem:
                        return await self._sync_with_peer(_peer, our_spiffe_id)

                tasks = [
                    _bounded_sync(peer)
                    for peer in active_peers
                ]
                
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Per-peer attempt metric + stats.
                success_count = 0
                error_count = 0
                backoff_skipped = 0
                watermark_skipped = 0
                for peer, r in zip(active_peers, results):
                    peer_label = (peer.name or "unknown")[:64]
                    if r is True:
                        success_count += 1
                        outcome = "success"
                    elif r == "watermark":
                        # §FEDSYNC-V2 — the peer answered and has nothing newer
                        # than our cursor: a successful sync that moved nothing,
                        # at the cost of one indexed read instead of a page walk.
                        success_count += 1
                        watermark_skipped += 1
                        outcome = "watermark_skip"
                    elif r == "skipped":
                        # §2026-07-26 — not called on purpose. Counting this as an error
                        # would make the cycle look broken while it is behaving correctly.
                        backoff_skipped += 1
                        outcome = "skipped"
                    else:
                        error_count += 1
                        outcome = "error"
                    if FEDERATION_SYNC_PEER_ATTEMPTS_TOTAL is not None:
                        try:
                            FEDERATION_SYNC_PEER_ATTEMPTS_TOTAL.labels(
                                registry=registry_label, peer=peer_label, outcome=outcome
                            ).inc()
                        except Exception:
                            pass
                _LAST_CYCLE_STATS["active_peers"] = len(active_peers)
                _LAST_CYCLE_STATS["license_gated_skipped"] = skipped
                _LAST_CYCLE_STATS["success_count"] = success_count
                _LAST_CYCLE_STATS["error_count"] = error_count
                _LAST_CYCLE_STATS["backoff_skipped"] = backoff_skipped
                _LAST_CYCLE_STATS["watermark_skipped"] = watermark_skipped

                logger.info(
                    f"Federation sync cycle completed: {success_count}/{len(active_peers)} successful"
                    + (f" ({watermark_skipped} watermark-quiet)" if watermark_skipped else "")
                    + (f" ({backoff_skipped} skipped by card-pull backoff)" if backoff_skipped else "")
                )

                # A1 (2026-07-24): federation.sync_completed was subscribable but
                # never fired. Broadcast one event per sweep with the cycle stats.
                try:
                    import asyncio as _aio
                    from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_event
                    _aio.create_task(dispatch_webhook_event(
                        "federation.sync_completed",
                        {"active_peers": len(active_peers),
                         "success_count": success_count,
                         "error_count": error_count,
                         "license_gated_skipped": skipped,
                         "backoff_skipped": backoff_skipped},
                        source_label="federation.sync_cycle"))
                except Exception:
                    pass

                if _FED_PROM_AVAILABLE:
                    import time as _time
                    FEDERATION_SYNC_LAST_SUCCESS_TIMESTAMP.labels(
                        registry=_fed_registry_label()
                    ).set(_time.time())

                # SF-5A (SEC-20): recompute each peer's trust value from its record (the one derivation,
                # services/bayesian_trust.derived_trust), inactivity pull included
                await self._refresh_derived_trust(db, active_peers)
                # §2026-06-21 idle-in-txn fix: flush any recompute writes + release the
                # connection before the next (network) pass.
                await db.commit()

                # SF-5B: Sync the derived bayesian_discount to EventStore for trust-weighted voting
                await self._sync_trust_to_eventstore(db, active_peers)

                # Registry Card v0.3.1 sync (§pass60.4, 2026-05-21) — DECOUPLED pass.
                # RC iterates ALL active peers regardless of parent_registry_id (chain
                # children included) because registry cards are cosmetic identity docs
                # — no echo / BFS-edge risk that justifies the agent-card "direct only"
                # filter above. Each peer's RC fetch is its own try; an HTTP 404 / 502
                # / timeout on one peer cannot block another. This loop ALSO doesn't
                # share auth wiring with agent-card sync: each peer rebuilds its own
                # mTLS/header config so we can hit URLs that agent-card sync wouldn't
                # touch.
                try:
                    all_active_peers = await crud_peer_registry.list_active_peer_registries_all(
                        db, skip=0, limit=1000
                    )
                    # §2026-05-30 — the DIRECT standalone RC dial only works for peers
                    # THIS registry can reach directly (our own frame / direct_peer /
                    # cloud_operator children). `discovered` peers are cross-frame /
                    # multi-hop: the direct dial resolves to a foreign internal host and
                    # 400s on SNI/cert mismatch (e.g. sandbox-A → sandboxdelta on
                    # sandbox-B's net). Those are pulled by the fan-out below instead
                    # (the path designed for them, §pass66). Skipping them here removes
                    # the wasted dials + the misleading `[RegistryCardSync] HTTP 400`
                    # noise. The fan-out (now base_url-keyed) is their authoritative path.
                    # §2026-06-25 (MC-9) — a 'discovered'-tagged peer that is actually THIS
                    # frame's OWN op (base_url host = op-*.<our SPIRE_TRUST_DOMAIN>) is directly
                    # reachable (identical dial path to a correctly-tagged cloud_operator op),
                    # so INCLUDE it in the direct RC sync → its registry-card + stock/market card
                    # refresh instead of going stale forever. Fixes rename-artifact ops mis-tagged
                    # 'discovered' (e.g. op-newyork/op-losangeles on frame-b vs the correctly-tagged
                    # op-chicago/op-houston). TRUE cross-frame ops (op-*.op.theprotocol.cloud) do
                    # NOT match our trust domain → stay excluded → fan-out (their designed path).
                    # §FANOUTFIX (2026-08-05) — predicate hoisted to module scope
                    # (is_own_reachable_op) so the fan-out guard can ask the SAME
                    # question. They must never disagree again.
                    rc_peers = [p for p in all_active_peers
                                if (p.peer_type or "").lower() != "discovered" or is_own_reachable_op(p)]
                    _skipped_disc = len(all_active_peers) - len(rc_peers)
                    logger.info(
                        f"[RegistryCardSync] iterating {len(rc_peers)} directly-reachable peers"
                        f" ({_skipped_disc} discovered → fan-out)"
                    )
                    # §2026-06-21 idle-in-txn fix: release the connection before the RC network gather.
                    await db.commit()
                    rc_tasks = [
                        self._sync_registry_card_standalone(peer, our_spiffe_id)
                        for peer in rc_peers
                    ]
                    await asyncio.gather(*rc_tasks, return_exceptions=True)
                except Exception as rc_e:
                    logger.warning(f"[RegistryCardSync] cycle error: {rc_e}")

                # §pass66 (2026-05-22) — Registry-card FAN-OUT pull.
                # Direct per-peer RC sync (above) silently fails for `discovered`
                # peers when this registry's container isn't on the central reg's
                # identity-net (typical for cloud-ops: their REGISTRY container is
                # on operator-net only, can't resolve `op-london.op.theprotocol.cloud`
                # via Docker DNS, so it loops to host nginx-a:8443 + SNI mismatch).
                # Solution: ask each DIRECT peer (mainframe) for the full fleet's
                # registry cards in one mTLS call. Mirror of the working agent-cards
                # fan-out pattern. Backend: routers/federation_sync.py
                # `/registry-cards` returns own card + all `cached_registry_card`
                # rows the peer knows about.
                try:
                    # §2026-06-05 — fan out from the parent FRAME + direct_peers,
                    # sourced from list_active_peer_registries_all, NOT the
                    # license-gated `active_peers`. `active_peers` (the agent-card
                    # list) drops (a) license-inactive peers AND (b) any peer with
                    # a non-NULL parent_registry_id (e.g. a frame parented into the
                    # op-chain display tree). That excluded the PARENT FRAME — the
                    # authoritative holder of the FULL fleet's registry cards — so a
                    # cloud-op fanned out only from a sibling direct_peer (partial
                    # ME-chain cards) and rendered plain-orb globes. The parent frame
                    # MUST always be a fan-out source regardless of its display
                    # parent or license row.
                    _fo_all = await crud_peer_registry.list_active_peer_registries_all(
                        db, skip=0, limit=1000
                    )
                    _fo_sources = [
                        p for p in _fo_all
                        if (p.peer_type or "").lower() in ("frame", "direct_peer")
                    ]
                    # §2026-06-21 idle-in-txn fix: release the connection before the fan-out network call.
                    await db.commit()
                    await self._pull_registry_cards_via_fanout(_fo_sources, our_spiffe_id)
                except Exception as fan_e:
                    logger.warning(f"[RegistryCardFanout] cycle error: {fan_e}")

                # §FEDLICENCE (2026-09-28) — the licence verdicts, AFTER the cards were refreshed (a peer's verdict is
                # read from its freshly verified card). Its own step: it can never cost the card sync above.
                try:
                    _lic = await licence_cycle()
                    if _lic and not _lic.get("skipped"):
                        logger.info("[fedlicence] cycle mode=%s self=%s counts=%s notes=%s",
                                    _lic.get("mode"), (_lic.get("self") or {}).get("state"),
                                    _lic.get("counts"), (_lic.get("notes") or [])[:3])
                except Exception as lic_e:
                    logger.warning(f"[fedlicence] cycle error: {type(lic_e).__name__}: {lic_e}")

            except Exception as e:
                logger.error(f"Error in federation sync cycle: {e}", exc_info=True)
                _LAST_CYCLE_STATS["cycle_error"] = str(e)[:240]
                if FEDERATION_SYNC_ERRORS_TOTAL is not None:
                    try:
                        FEDERATION_SYNC_ERRORS_TOTAL.labels(
                            registry=registry_label, reason="cycle_exception"
                        ).inc()
                    except Exception:
                        pass

        cycle_duration_ms = int((_time_mod.time() - cycle_t0) * 1000)
        _LAST_CYCLE_STATS["last_duration_ms"] = cycle_duration_ms
        if FEDERATION_SYNC_LAST_CYCLE_DURATION_MS is not None:
            try:
                FEDERATION_SYNC_LAST_CYCLE_DURATION_MS.labels(registry=registry_label).set(cycle_duration_ms)
            except Exception:
                pass
    
    async def _refresh_derived_trust(self, db, peers: list) -> None:
        """SF-5A (SEC-20, 2026-10-17): set each peer's bayesian_discount to its derivation from its record and the clock
        (services/bayesian_trust.refresh_derived_trust), so the column every surface reads equals what the trust sync
        sends. It replaced a second inactivity rule that moved the same column (0.01 per cycle after 90 idle days,
        applied to the stored value) beside the model's own (30 days, 5 % per day); the derivation is the only rule."""
        updated = refresh_derived_trust(peers)
        if updated:
            await db.commit()
            logger.info(f"SF-5A: trust value recomputed for {updated} peer(s)")

    async def _sync_trust_to_eventstore(self, db, peers: list) -> None:
        """SF-5B: Push bayesian_discount values to EventStore for trust-weighted voting.

        §MTLSHOPS (c), 2026-09-15: the event store keys `federation_operators` by the LICENCE id this frame issued, and
        this pass used to send the peer ROW id (1, 2, 3 ...), which no store row carries, so every call fell into the
        store's insert branch and was refused 400 for a missing licence hash (measured: every synced peer on EU, ASIA and
        both sandbox frames, every cycle; 0 successes in 4 hours). It now sends one update per licence this frame issued to
        a peer (trust_sync_payloads): the licence id, the licence's own operator_name and the peer's DERIVED trust value
        (SEC-20: services/bayesian_trust.derived_trust_for, never the stored column).
        Never a status (the store authenticates an operator on status == "active", and a peer row's "ACTIVE" would lock it
        out) and never a licence hash. A peer this frame issued no licence to (a peer frame federated through the
        invitation rail, a discovered operator) is skipped. Each payload names the peer: a peer frame by its trust domain,
        one of this frame's own operators by its own SVID (SPIRE_TRUST_DOMAIN says which domain is ours), never by the
        bare domain the operators share (2026-10-17, trust_sync_payloads).

        Auth: mTLS when EVENT_STORE_URL is HTTPS (the store's sidecar forwards the certificate; this frame's own registry
        keeps origin rights there), X-Internal-Key on a plain internal URL.
        """
        import os
        es_url = os.getenv("EVENT_STORE_URL", "http://event-store:8200")
        es_key = os.getenv("EVENT_STORE_API_KEY", "")
        if not es_key:
            return
        try:
            licences = (await db.execute(select(
                models.FederationLicense.id, models.FederationLicense.operator_name, models.FederationLicense.status,
            ))).all()
        except Exception as e:
            logger.debug(f"SF-5B: licence read failed (non-fatal): {e}")
            return
        finally:
            try:
                await db.commit()  # §2026-06-21 idle-in-txn: release the connection before the network pass
            except Exception:
                pass
        payloads, skipped = trust_sync_payloads(peers, licences, os.getenv("SPIRE_TRUST_DOMAIN", ""))
        if skipped:
            logger.debug(f"SF-5B: no licence issued here for {len(skipped)} peer(s), not synced: {', '.join(skipped[:5])}")
        if not payloads:
            return

        # §SOVKIT T5 (2026-09-14): the store's ONE TLS context (es_ssl_helper: the SPIRE bundle AND the system roots,
        # plus the SVID), which verifies the frame's own mTLS sidecar and an operator's LE-signed parent edge alike.
        synced = 0
        failed: List[str] = []
        try:
            async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
                for payload in payloads:
                    try:
                        resp = await client.post(
                            f"{es_url}/api/v1/events/operators/sync",
                            json=payload,
                            headers={"X-Internal-Key": es_key, "Content-Type": "application/json"},
                        )
                        if resp.status_code >= 400:
                            failed.append(f"{payload['operator_name']}: HTTP {resp.status_code}")
                        else:
                            synced += 1
                    except Exception as post_error:
                        failed.append(f"{payload['operator_name']}: {type(post_error).__name__}")
        except Exception as e:
            logger.debug(f"SF-5B: Trust sync to EventStore failed (non-fatal): {e}")
        if synced:
            logger.info(f"SF-5B: Synced bayesian_discount for {synced} peer(s) to EventStore")
        if failed:
            logger.warning(f"SF-5B: EventStore refused the trust sync for {len(failed)} peer(s): {'; '.join(failed[:5])}")

    async def _sync_with_peer(self, peer: models.PeerRegistry, our_spiffe_id: str,
                              reconcile: bool = False, digest_probe: bool = False):
        """Sync agent cards with a single peer registry.

        Args:
            peer: PeerRegistry instance to sync with
            our_spiffe_id: Our SPIFFE identity
            reconcile: §SYNCPAGE — read-repair mode: walk the peer from epoch
                (cursor kept in Redis, resumable across cycles) WITHOUT touching
                last_synced_at. Unchanged cards are upsert no-ops, so a full
                pass is cheap; it heals any historical gap regardless of cause.
            digest_probe: §FEDSYNC-V2 — do NOT sync; fetch the peer's
                /sync-digest, compare against our local digest, and return a
                verdict. Rides this function (rather than its own helper) so it
                reuses the exact URL-derivation + mTLS/license auth path.

        Returns:
            True   — sync succeeded
            False  — sync attempted and failed
            "skipped" — not attempted; the per-peer card-pull backoff is armed
            "watermark" — peer answered but has nothing newer than our cursor;
                page walk skipped, last_synced_at deliberately NOT advanced
            "digest_equal" | "digest_mismatch" | "digest_unsupported"
                — digest_probe=True verdicts (unsupported = pre-§FEDSYNC-V2 peer)
        """
        # §2026-07-26 — don't re-ask a peer that just refused us. Returns the sentinel
        # "skipped" (not False) so the cycle stats stop counting a deliberate skip as an
        # error. See the _CARD_PULL_BACKOFF block at module top for the rationale.
        _backoff = await _card_pull_backoff_reason(peer.name)
        if _backoff:
            logger.debug(
                f"Skipping agent-card pull from {peer.name} — backoff active ({_backoff})"
            )
            _count_backoff(_backoff, "skipped")
            return "skipped"

        logger.info(f"Starting sync with peer: {peer.name}")

        # Build the sync endpoint URL.
        # 2026-05-18: rewrite hostname to agentvault_identity_network alias via
        # _to_internal_mtls_url. See federation_helper.py for full rationale. For
        # Frame B operators stored as op-X.frame-b.theprotocol.cloud the helper
        # rewrites to op-X.op.theprotocol.cloud (DNS alias on agentvault_identity_network,
        # cert SAN match). No-op for other URLs.
        # §pass62.4 REVERTED (2026-05-21) — switching to _to_registry_dialable_url
        # made Frame B's federation_sync work, which caused Frame B's /public/topology
        # to return complete edges, which caused Frame A's BFS writeback in
        # main.py:1490 to flatten the chained-sibling parents Commander relies on
        # for the Federation Network tab tree rendering. Reverted to preserve
        # topology shape. Trade-off: Frame B loses v0.3 visuals for cross-frame
        # peers (acceptable). See SESSION_LOG_2026-05-21_PASS62_3_NETWORK_CHANGE_INCIDENT.md.
        from agentvault_registry.routers.teg_integration import _to_internal_mtls_url
        sync_url = _to_internal_mtls_url(peer.base_url.rstrip('/')) + '/api/v1/federation/agent-cards'
        
        # Build client config: use mTLS certs only for HTTPS peers
        # In Docker dev, peers use internal HTTP (trusted network).
        # In production, peers use HTTPS with SPIRE mTLS certs.
        client_config = {'timeout': self.httpx_timeout}
        extra_headers = {}
        
        if sync_url.startswith('https://'):
            # mTLS only — attach SPIRE SVID client certificates
            cert_config = svid_client.get_client_cert_config(target_url=sync_url)
            if cert_config:
                client_config.update(cert_config)
                logger.info(f"Using mTLS for sync with {peer.name}")
            else:
                logger.error(f"No mTLS certs available for HTTPS sync with {peer.name}")
                return False
        else:
            # HTTP mode: try federation license first, fall back to internal secret
            fed_license = os.environ.get("FEDERATION_LICENSE_KEY", "")
            if fed_license:
                extra_headers = {"X-Federation-License": fed_license}
                logger.info(f"Using federation license for sync with {peer.name} (HTTP)")
            else:
                fed_secret = os.environ.get(
                    "FEDERATION_INTERNAL_SECRET",
                    ""
                )
                extra_headers = {
                    "X-Federation-Secret": fed_secret,
                    "X-Federation-SPIFFE-ID": our_spiffe_id
                }
                logger.info(f"Using internal auth for sync with {peer.name} (HTTP)")
        
        if extra_headers:
            client_config['headers'] = extra_headers
        
        async with httpx.AsyncClient(**client_config) as client:
            try:
                # §FEDSYNC-V2 — digest probe mode: fetch + compare, never sync.
                if digest_probe:
                    return await self._digest_probe(client, peer, sync_url)

                # §FEDSYNC-V2 — watermark fast-path. Before paging an
                # incremental window, ask the peer whether ANYTHING is newer
                # than our cursor. The steady state of this mesh is zero
                # changed cards for hours; this turns those cycles into one
                # ~0.1 ms indexed read per peer instead of a page walk.
                # Fail-OPEN: any error (404 on an old peer, timeout, parse)
                # falls through to the normal pull unchanged. Bootstrap
                # (no last_synced_at) and reconcile walks never skip.
                if (not reconcile) and peer.last_synced_at and _watermark_enabled():
                    try:
                        wm_url = sync_url.rsplit('/agent-cards', 1)[0] + '/sync-watermark'
                        wresp = await client.get(wm_url)
                        if wresp.status_code == 200:
                            wraw = (wresp.json() or {}).get('max_updated_at')
                            wdt = None
                            if wraw:
                                wdt = datetime.fromisoformat(str(wraw).replace('Z', '+00:00'))
                                if wdt.tzinfo is None:
                                    wdt = wdt.replace(tzinfo=timezone.utc)
                            wm_cursor = peer.last_synced_at - timedelta(seconds=60)
                            if wm_cursor.tzinfo is None:
                                wm_cursor = wm_cursor.replace(tzinfo=timezone.utc)
                            # Empty corpus (None) or nothing past our overlap
                            # cursor ⇒ a page walk would return zero rows.
                            # §TRAVELREC — do not skip on a stale EXPORT SHAPE. The watermark
                            # only knows about stored rows; if the peer has started deriving a
                            # new field onto the cards it exports, nothing here can see it and
                            # this skip is how the feature reaches nobody. Measured exactly that.
                            _wver = (wresp.json() or {}).get('export_version')
                            _wseen = await _last_export_version(peer.name)
                            if _wver and _wver != _wseen:
                                logger.info(
                                    f"[FED-WATERMARK] {peer.name}: export shape changed "
                                    f"({_wseen!r} -> {_wver!r}) — walking despite the watermark"
                                )
                                await _note_export_version(peer.name, _wver)
                                # ⚠ AND WALK FROM EPOCH, not from the cursor. Bypassing the
                                # watermark only buys an INCREMENTAL page, which asks for cards
                                # newer than our cursor and gets none — nothing about those cards
                                # changed, only what the peer now says about them. §DIRFEED's rule
                                # is re-read EVERYTHING when the extract changes, so seed the
                                # reconcile cursor to epoch and let the reconcile walk carry it.
                                await _reconcile_set(
                                    _RECONCILE_CURSOR_PREFIX + peer.name, _SYNC_EPOCH.isoformat())
                            elif wdt is None or wdt <= wm_cursor:
                                logger.debug(
                                    f"Watermark skip for {peer.name}: peer max_updated_at="
                                    f"{wraw} <= cursor {wm_cursor.isoformat()}"
                                )
                                await _clear_card_pull_backoff(peer.name)
                                await _record_corridor_ok(peer.id)
                                return "watermark"
                    except Exception as _wm_e:  # noqa: BLE001 — fail-open
                        logger.debug(f"Watermark probe failed for {peer.name} (falling through): {_wm_e}")

                # §SYNCPAGE (2026-08-03) — cursor-true paged pull (module block above).
                page_limit = _sync_page_limit()
                if reconcile:
                    cur_raw = await _reconcile_get(_RECONCILE_CURSOR_PREFIX + peer.name)
                    try:
                        start_cursor = datetime.fromisoformat(cur_raw) if cur_raw else _SYNC_EPOCH
                    except ValueError:
                        start_cursor = _SYNC_EPOCH
                elif peer.last_synced_at:
                    # Small overlap buffer so boundary updates are never missed
                    start_cursor = peer.last_synced_at - timedelta(seconds=60)
                else:
                    start_cursor = _SYNC_EPOCH
                    logger.info(f"Bootstrap walk for never-synced peer {peer.name} (paged from epoch)")
                if start_cursor.tzinfo is None:
                    start_cursor = start_cursor.replace(tzinfo=timezone.utc)

                async def _fetch_page(cursor: datetime):
                    # `paged=1` asks a §SYNCPAGE-aware server for a pure ascending
                    # page (no flare-augmentation prepend, whose newer timestamps
                    # would poison the cursor). Old servers ignore the param and
                    # answer DESC exactly as before — the walk then terminates after
                    # its first page, which is BYTE-IDENTICAL to today's behaviour.
                    # §DARKSYNC (2026-09-22): we store unlisted mirrors and hide them from discovery, so ask for
                    # the full card of an unlisted agent (an older server ignores the parameter and sends tombstones).
                    params = {'since': cursor.isoformat(), 'limit': str(page_limit), 'paged': 'true', 'listing_carry': 'true'}
                    logger.debug(f"Fetching agent cards from {peer.name} with params: {params}")
                    response = await client.get(sync_url, params=params)
                    if response.status_code != 200:
                        # §2026-06-24 F1 fix — 401/403 = the peer does not register us as a
                        # federation peer. EXPECTED for cross-frame ops; DEBUG + backoff.
                        # 5xx/timeout stay ERROR so real breakage remains visible.
                        if response.status_code in (401, 403):
                            logger.debug(
                                f"Agent-card sync not authorized by {peer.name}: "
                                f"HTTP {response.status_code} (expected for cross-frame peers; "
                                f"registry cards still arrive via the fan-out carry)"
                            )
                            # §2026-07-26 — stop asking for a while instead of just
                            # not mentioning it (the receiver logs too).
                            await _note_card_pull_refusal(peer.name, "unauthorized")
                        else:
                            logger.error(f"Failed to fetch cards from {peer.name}: HTTP {response.status_code}")
                        return response.status_code, [], False, None
                    cards = response.json()
                    # §SYNCPAGE truth headers (new servers only; absent = old server
                    # and the walk falls back to the len>=limit heuristic).
                    srv_more = response.headers.get("x-sync-has-more") == "1"
                    srv_cursor = None
                    _raw_cur = response.headers.get("x-sync-next-cursor")
                    if _raw_cur:
                        try:
                            srv_cursor = datetime.fromisoformat(_raw_cur.replace("Z", "+00:00"))
                            if srv_cursor.tzinfo is None:
                                srv_cursor = srv_cursor.replace(tzinfo=timezone.utc)
                        except ValueError:
                            srv_cursor = None
                    logger.info(
                        f"Received {len(cards)} agent cards from {peer.name}"
                        + (" (reconcile)" if reconcile else "")
                        + (" [more]" if srv_more else "")
                    )
                    return 200, cards, srv_more, srv_cursor

                async def _process(cards):
                    return await self._process_peer_cards(peer, cards)

                if reconcile:
                    async def _progress(cursor: datetime):
                        await _reconcile_set(_RECONCILE_CURSOR_PREFIX + peer.name, cursor.isoformat())

                    async def _caught_up():
                        await _reconcile_del(_RECONCILE_CURSOR_PREFIX + peer.name)
                else:
                    async def _progress(cursor: datetime):
                        # FULL page ⇒ the window overflowed the page limit. Stamp the
                        # CURSOR, not now() — stamping now() here is exactly the old
                        # truncation bug (the skipped remainder never arrived again).
                        await self._update_peer_sync_status(peer.id, True, watermark=cursor)

                    async def _caught_up():
                        await self._update_peer_sync_status(peer.id, True)

                outcome = await _walk_pages(
                    fetch_page=_fetch_page,
                    process_page=_process,
                    stamp_progress=_progress,
                    stamp_caught_up=_caught_up,
                    start_cursor=start_cursor,
                    page_limit=page_limit,
                    max_pages=_sync_max_pages(reconcile),
                    mode=("reconcile" if reconcile
                          else ("bootstrap" if start_cursor == _SYNC_EPOCH else "incremental")),
                    peer_name=peer.name,
                )
                if outcome == "failed":
                    if not reconcile:
                        await self._update_peer_sync_status(peer.id, False)
                    return False
                # "caught_up", or "budget" (cursor persisted → next cycle resumes).
                await _clear_card_pull_backoff(peer.name)
                if outcome == "budget":
                    logger.info(
                        f"Paged sync with {peer.name}: page budget reached, cursor persisted — "
                        f"walk continues next cycle"
                    )

                # NOTE (§pass60.4): Registry Card sync was previously chained here
                # but that coupled it to the agent-card sync's pass/fail. Moved out
                # to a dedicated _sync_registry_card_standalone pass that iterates
                # ALL active peers (chain-children included) on its own — see
                # `list_active_peer_registries_all` + the rc_tasks loop in the main
                # sync cycle. The inline `_sync_registry_card` helper below is kept
                # for backward compat (callers that want auth context reuse) but
                # the main cycle now uses the standalone variant.

                return True

            except httpx.TimeoutException:
                logger.warning(f"Timeout syncing with peer {peer.name}")
                await _note_card_pull_refusal(peer.name, "unreachable")
                return False
            except httpx.ConnectError:
                # §2026-07-26 — this fired for the same 5 cross-frame ops every single
                # cycle, on the clock. Back off so an unreachable peer costs one line,
                # not one per cycle; peer_revival_prober (§V0150) still owns reachability.
                logger.warning(f"Failed to connect to peer {peer.name}")
                await _note_card_pull_refusal(peer.name, "unreachable")
                return False
            except Exception as e:
                logger.error(f"Unexpected error syncing with peer {peer.name}: {e}")
                return False

    async def _sync_registry_card(
        self,
        peer: models.PeerRegistry,
        client_config: Dict[str, Any],
        extra_headers: Dict[str, str],
    ) -> None:
        """Fetch peer's /.well-known/registry-card.json + cache it.

        ETag-driven (If-None-Match → 304 short-circuits). 3-way SPIFFE verify
        on sovereign-variant claims before write. Soft-rejects sovereign claim
        (strips visual.sovereign_variant) on mismatch; keeps rest of card.
        """
        # §pass67.1 (2026-05-23) — RC sync via _to_registry_dialable_url
        # (caller-aware). The §pass62.4 helper was REVERTED at the time
        # because of a BFS-writeback issue that overwrote chained-sibling
        # parents; that BFS writeback path has since been disabled (§pass62.5,
        # see main.py:1490-1495 — INSERT branch retained, UPDATE branch removed).
        # The §pass67.1 patch extends the helper with a cloud-op caller branch
        # (dials public :443 via Let's Encrypt) so Frame B operators on
        # operator-net can finally pull cross-frame RC v0.3 cards without the
        # cert-SAN-mismatch failure that was hidden by §pass66.2's
        # status='ACTIVE' filter (visible after §pass67 promoted peers).
        from agentvault_registry.routers.teg_integration import _to_registry_dialable_url
        from ..crud import crud_peer_registry
        from ..services import registry_card_validator

        rc_url = _to_registry_dialable_url(peer.base_url.rstrip('/')) + '/.well-known/registry-card.json'

        # Use prior etag for If-None-Match.
        headers = dict(extra_headers)
        if peer.card_etag:
            headers['If-None-Match'] = f'"{peer.card_etag}"'

        rc_config = dict(client_config)
        # Override timeout to be friendlier for the card endpoint (5s).
        rc_config['timeout'] = 5.0
        if headers:
            rc_config['headers'] = headers

        async with httpx.AsyncClient(**rc_config) as client:
            try:
                resp = await client.get(rc_url)
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.debug("[RegistryCardSync] peer=%s connect/timeout: %s", peer.name, e)
                return

        if resp.status_code == 304:
            # Cache is current; just bump last_pulled_at via a no-op upsert.
            async with AsyncSessionLocal() as db:
                await crud_peer_registry.upsert_registry_card_from_peer(
                    db, peer.id, peer.cached_registry_card or {},
                    etag=peer.card_etag,
                    signature_verified=bool(peer.card_signature_verified),
                    signature_kid=peer.card_signature_kid,
                )
            # Stock-card back-fill from the already-cached card (digest-gated → a
            # no-op once cached; this is what fills the table right after the flag
            # is flipped on, when peer cards are steady-state 304).
            await self._sync_stock_card(peer, peer.cached_registry_card or {}, client_config)
            return

        if resp.status_code != 200:
            logger.info("[RegistryCardSync] peer=%s HTTP %s", peer.name, resp.status_code)
            return

        try:
            card = resp.json()
        except Exception as e:
            logger.warning("[RegistryCardSync] peer=%s JSON parse failed: %s", peer.name, e)
            return

        # 3-way SPIFFE verify uses the peer's trust_domain + name to derive its
        # canonical SVID. federation_sync.py:553 has a legacy name-template
        # fallback used elsewhere; the canonical RC SVID is the cleaner
        # spiffe://<trust_domain>/registry/<name> form per RC v0.3 spec.
        peer_svid = ""
        if peer.trust_domain:
            peer_svid = f"spiffe://{peer.trust_domain}/registry/{peer.name}"

        body_bytes = len(resp.content or b"")
        # findings row 187 — the self-namespace guard must not refuse OUR OWN operators, which
        # share this frame's trust domain by design. The decision comes from OUR PEER ROW, never
        # from the card: a card that could assert its way past that guard is the attack it exists
        # to stop. `is_own_reachable_op` is the SAME predicate the direct-sync selection uses
        # (§FANOUTFIX hoisted it to module scope precisely so the two cannot drift apart).
        _own_op = (peer.peer_type or "").lower() == "cloud_operator" or is_own_reachable_op(peer)
        # ...and its mirror: an operator accepts ITS PARENT's card, which declares the namespace they share
        normalized = registry_card_validator.validate_and_normalize(
            card, body_bytes, peer_svid=peer_svid, peer_trust_domain=peer.trust_domain,
            allow_own_namespace=_own_op or is_my_parent_frame(peer),
        )
        if normalized is None:
            logger.warning("[RegistryCardSync] peer=%s validation failed; skip", peer.name)
            return

        # Phase 6 (2026-05-21) — verify the JWS against peer's JWKS.
        # AUDIT: reconstruct the payload from the card's OWN declared signed_canonical
        # (forward/backward-compatible as the signed set grows) + fold in the signed
        # freshness anchor, and REJECT an expired (replayed) card even if the EdDSA
        # signature itself is valid.
        sig = normalized.get("signature") or {}
        signature_kid = sig.get("kid")
        signature_present = bool(sig.get("value") and signature_kid)
        signature_verified = False
        if signature_present:
            try:
                from ..services.registry_card_signer import extract_paths, SIGNED_CANONICAL_PATHS
                from ..services.registry_card_signer_impl import verify_with_jwk

                # §pass67.1 — JWKS via the same caller-aware helper as RC URL above
                jwks_url = _to_registry_dialable_url(peer.base_url.rstrip('/')) + '/.well-known/registry-jwks.json'
                jwks_cfg = dict(client_config)
                jwks_cfg['timeout'] = 5.0
                async with httpx.AsyncClient(**jwks_cfg) as jwks_client:
                    jwks_resp = await jwks_client.get(jwks_url)
                if jwks_resp.status_code == 200:
                    jwks = jwks_resp.json()
                    matching = next(
                        (k for k in jwks.get("keys", []) if k.get("kid") == signature_kid),
                        None,
                    )
                    if matching:
                        declared = sig.get("signed_canonical") or SIGNED_CANONICAL_PATHS
                        # §DOCSFIX CB-399: the signature is checked on the card AS RECEIVED. The validator's normalising
                        # (a sovereign_variant this receiver cannot draw is set to null for display) changes a signed
                        # leaf, so resolving the paths on `normalized` recorded every card naming such a style as
                        # unverified. What is stored and shown stays the normalised copy.
                        payload = extract_paths(card, declared)
                        if sig.get("signed_at") is not None:
                            payload["_signed_at"] = sig.get("signed_at")
                        if sig.get("expires_at") is not None:
                            payload["_expires_at"] = sig.get("expires_at")
                        signature_verified = verify_with_jwk(payload, sig["value"], matching)
                        if signature_verified and sig.get("expires_at"):
                            try:
                                import datetime as _dt
                                _exp = _dt.datetime.fromisoformat(str(sig["expires_at"]))
                                if _exp.tzinfo is None:
                                    _exp = _exp.replace(tzinfo=_dt.timezone.utc)
                                if _exp < _dt.datetime.now(_dt.timezone.utc):
                                    logger.warning(
                                        "[RegistryCardSync] peer=%s signature EXPIRED at %s — rejecting",
                                        peer.name, sig["expires_at"],
                                    )
                                    signature_verified = False
                            except Exception:
                                pass
                        if signature_verified and isinstance(card.get("compliance"), dict):
                            # §DOCSFIX CB-401: spec 7.4 step 7. The signature covers compliance.digest, a hash of
                            # the block; only recomputing it from the block shows the block itself was not altered.
                            from ..services.regulatory_auth import compliance_digest as _compliance_digest
                            _comp = card["compliance"]
                            if _compliance_digest(_comp) != _comp.get("digest"):
                                logger.warning(
                                    "[RegistryCardSync] peer=%s compliance block does not match its signed digest",
                                    peer.name,
                                )
                                signature_verified = False
                        if not signature_verified:
                            logger.warning(
                                "[RegistryCardSync] peer=%s signature INVALID/EXPIRED for kid=%s",
                                peer.name, signature_kid,
                            )
            except Exception as e:
                logger.warning("[RegistryCardSync] peer=%s JWS verify error: %s", peer.name, e)

        # Strip-on-soft-reject already applied by validator; record whether
        # the card we're caching has a sovereign claim that DID survive verify.
        original_variant = (card.get("visual") or {}).get("sovereign_variant")
        normalized_variant = (normalized.get("visual") or {}).get("sovereign_variant")
        if original_variant and not normalized_variant:
            logger.info(
                "[RegistryCardSync] peer=%s sovereign_variant=%r stripped (3-way SPIFFE fail)",
                peer.name, original_variant,
            )

        new_etag = resp.headers.get("etag", "").strip('"')
        # AUDIT cross-cutting #2 — fail-CLOSED ingest (env FEDERATION_INGEST_FAIL_CLOSED,
        # default-off). A peer card that is unsigned OR fails signature/freshness
        # verification is REJECTED (keep the prior cached card) rather than cached
        # fail-open. Default-off preserves current behaviour for first-party fleets.
        if (os.getenv("FEDERATION_INGEST_FAIL_CLOSED", "") or "").strip().lower() in ("1", "true", "yes", "on") and not signature_verified:
            logger.warning(
                "[RegistryCardSync] FAIL-CLOSED: peer=%s card unsigned/unverified (sig_present=%s) — keeping prior cache",
                peer.name, signature_present,
            )
            return
        async with AsyncSessionLocal() as db:
            await crud_peer_registry.upsert_registry_card_from_peer(
                db, peer.id, normalized,
                etag=new_etag or None,
                signature_verified=signature_verified,
                signature_kid=signature_kid,
            )
            # WS-G: persist trust_domain from the signed card on first pull so a
            # newly-discovered peer becomes resolvable via the fast
            # peer.trust_domain path used by the refuse-on-null resolver (the
            # runtime card-fallback already covers it; this avoids a manual backfill).
            if not peer.trust_domain:
                _ident = normalized.get("identity") if isinstance(normalized.get("identity"), dict) else {}
                _ctd = _ident.get("trust_domain")
                if isinstance(_ctd, str) and _ctd.strip():
                    from sqlalchemy import update as _sa_update
                    await db.execute(
                        _sa_update(models.PeerRegistry)
                        .where(models.PeerRegistry.id == peer.id)
                        .values(trust_domain=_ctd.strip().lower())
                    )
                    await db.commit()
                    peer.trust_domain = _ctd.strip().lower()
                    logger.info(
                        "[RegistryCardSync] peer=%s trust_domain backfilled from card → %s",
                        peer.name, peer.trust_domain,
                    )
        logger.info(
            "[RegistryCardSync] peer=%s OK etag=%s sig_kid=%s sovereign_variant=%r",
            peer.name, (new_etag or "")[:24], signature_kid, normalized_variant,
        )

        # Federated Stock Cards (2026-06-17) — pull the peer's AGORA catalog if it
        # links one. Own try/except inside; cannot affect the card cache above.
        await self._sync_stock_card(peer, normalized, client_config)

    async def _sync_stock_card(
        self,
        peer: models.PeerRegistry,
        card: Dict[str, Any],
        client_config: Dict[str, Any],
    ) -> None:
        """Federated Stock Cards (2026-06-17) — pull + cache a peer's AGORA catalog.

        APPEND-ONLY + OWN try/except (can never touch the registry-card cache or
        BFS), DIGEST-GATED (no catalog change → no fetch, no write — the OWL24
        lesson), and FAIL-CLOSED (any verify failure keeps the prior cache).
        Gated OFF by default via STOCK_CARD_SYNC_ENABLED. Called from BOTH the 200
        and 304 branches of _sync_registry_card so a freshly-enabled registry
        back-fills from already-cached peer cards (304 steady state) as well as on
        fresh pulls. Δ-irrelevant: read-only metadata — a forged catalog can't move
        money (trading settles via passport + escrow + signed DevCard).
        """
        if (os.getenv("STOCK_CARD_SYNC_ENABLED", "false") or "false").strip().lower() not in ("1", "true", "yes", "on"):
            return
        try:
            sc = (((card or {}).get("fees") or {}).get("exchange") or {}).get("stock_card")
            if not isinstance(sc, dict):
                return  # peer advertises no stock card
            sc_url = sc.get("url")
            sc_digest = sc.get("digest")
            if not sc_url or not sc_digest:
                return

            # Source identity = the peer's signed-card SPIFFE (matches the signer).
            ident = card.get("identity") if isinstance(card.get("identity"), dict) else {}
            source_spiffe = ident.get("spiffe_id")
            if not source_spiffe and peer.trust_domain:
                source_spiffe = f"spiffe://{peer.trust_domain}/registry/{peer.name}"
            if not source_spiffe:
                return

            # §2026-06-25 the link also advertises a COARSE market_epoch; re-fetch when
            # it advances (the catalog digest is trade-invariant → it alone never would).
            sc_market_epoch = sc.get("market_epoch")
            # Digest-gate (idempotency): unchanged catalog AND market epoch → no fetch, no write.
            async with AsyncSessionLocal() as db:
                existing = (await db.execute(
                    select(models.FederatedStockCard).where(
                        models.FederatedStockCard.source_spiffe_id == source_spiffe
                    )
                )).scalar_one_or_none()
                if existing is not None and existing.digest == sc_digest \
                        and existing.market_epoch == sc_market_epoch:
                    return

            from agentvault_registry.routers.teg_integration import _to_registry_dialable_url
            base = _to_registry_dialable_url(peer.base_url.rstrip("/"))
            fetch_url = base + (sc_url if sc_url.startswith("/") else "/" + sc_url)

            sc_cfg = dict(client_config)
            sc_cfg["timeout"] = 5.0
            sc_cfg.pop("headers", None)  # public well-known doc
            async with httpx.AsyncClient(**sc_cfg) as client:
                resp = await client.get(fetch_url)
            if resp.status_code != 200:
                logger.info("[StockCardSync] peer=%s HTTP %s", peer.name, resp.status_code)
                return
            doc = resp.json()
            listings = doc.get("listings")
            if not isinstance(listings, list):
                return

            from agentvault_registry.services.stock_card_builder import (
                catalog_digest, extract_stock_canonical,
            )
            # (1) self-consistency: hash(catalog) == the doc's own digest.
            if catalog_digest(listings) != doc.get("digest"):
                logger.warning("[StockCardSync] peer=%s catalog/digest mismatch — drop (fail-closed)", peer.name)
                return
            # (2) freshness cross-check: doc digest == digest linked on the registry card.
            if doc.get("digest") != sc_digest:
                logger.warning("[StockCardSync] peer=%s card/doc digest disagree — drop", peer.name)
                return
            # (3) tamper anchor: verify the stock card's OWN EdDSA JWS vs the peer
            # JWKS (same keystore + verify path as the registry card).
            sig = doc.get("signature") or {}
            kid = sig.get("kid")
            verified = False
            if sig.get("value") and kid:
                try:
                    from agentvault_registry.services.registry_card_signer_impl import verify_with_jwk
                    jwks_url = base + "/.well-known/registry-jwks.json"
                    jwks_cfg = dict(client_config)
                    jwks_cfg["timeout"] = 5.0
                    jwks_cfg.pop("headers", None)
                    async with httpx.AsyncClient(**jwks_cfg) as jc:
                        jr = await jc.get(jwks_url)
                    if jr.status_code == 200:
                        match = next((k for k in jr.json().get("keys", []) if k.get("kid") == kid), None)
                        if match:
                            verified = verify_with_jwk(extract_stock_canonical(doc), sig["value"], match)
                except Exception as e:
                    logger.warning("[StockCardSync] peer=%s JWS verify error: %s", peer.name, e)
            if not verified:
                logger.warning("[StockCardSync] peer=%s signature unverified — drop (fail-closed)", peer.name)
                return

            # Content-idempotent upsert (digest-gated above → only real changes here).
            async with AsyncSessionLocal() as db:
                row = await _stock_card_row(db, source_spiffe, peer.name)
                now = datetime.now(timezone.utc)
                if row is None:
                    row = models.FederatedStockCard(source_spiffe_id=source_spiffe)
                    db.add(row)
                row.source_registry_name = peer.name
                row.currency = doc.get("currency")
                row.listings_json = listings
                row.digest = doc.get("digest")
                row.market_json = doc.get("market") if isinstance(doc.get("market"), dict) else None
                row.market_epoch = sc_market_epoch
                row.signature_verified = True
                row.via_fanout = False  # direct consume = AUTHORITATIVE (never clobbered by a carried copy)
                row.fetched_at = now
                row.updated_at = now
                await db.commit()
            logger.info(
                "[StockCardSync] peer=%s cached %d listing(s) ccy=%s digest=%s",
                peer.name, len(listings), doc.get("currency"), (doc.get("digest") or "")[:20],
            )
        except Exception as e:
            logger.warning("[StockCardSync] peer=%s unexpected (isolated): %s", getattr(peer, "name", "?"), e)

    async def _pull_registry_cards_via_fanout(
        self,
        direct_peers: List[models.PeerRegistry],
        our_spiffe_id: str,
    ) -> None:
        """§pass66 — fan-out pull of registry cards from a direct mainframe peer.

        For each DIRECT peer (typically just the parent mainframe), call
        `GET /api/v1/federation/registry-cards` over mTLS. The endpoint returns:
          - the peer's OWN current registry card (always fresh)
          - every `cached_registry_card` from the peer's `peer_registries`
            where status=ACTIVE
        Each returned card is upserted into THIS registry's `peer_registries`
        row matched by name. New names get an INSERT (peer_type='discovered').

        This makes cloud-ops see the full fleet's visual identity / sovereign
        variants / fee surfaces without needing direct mTLS reachability to
        every cloud-op (which they don't have on operator-net).
        """
        from agentvault_registry.routers.teg_integration import _to_registry_dialable_url
        from ..crud import crud_peer_registry

        # Only fan-out from direct peers (set by list_active_peer_registries).
        # Discovered peers we don't dial.
        #
        # §2026-05-30 — EXCLUDE cloud_operator peers as fan-out SOURCES. A
        # cloud-op child holds only a (possibly stale) MIRROR of cross-frame
        # peers; it is never authoritative for them. A mainframe that fanned
        # out from BOTH the other mainframe (authoritative, serves the FRESH
        # card) AND its own cloud-op children (stale mirror) let the
        # unconditional last-writer-wins upsert (upsert_registry_card_from_peer)
        # clobber the fresh card every cycle — cross-frame `discovered` peers
        # have NO precedence guard (the ~line-965 guard only protects
        # non-discovered / directly-synced children). Restricting RC fan-out
        # sources to authoritative mainframes (frame / direct_peer) makes
        # convergence deterministic. Cloud-ops keep working: their own fan-out
        # source is their PARENT mainframe (a frame/direct_peer from their POV),
        # so coverage is unchanged. See memory
        # feedback_registry_card_fanout_multisource_clobber.
        direct_peers = [
            p for p in direct_peers
            if (p.peer_type or "").lower() != "cloud_operator"
        ]
        if not direct_peers:
            return

        total_received = 0
        total_upserted = 0

        for parent in direct_peers:
            # Skip peers without an mTLS-routable base_url
            if not parent.base_url:
                continue

            # §pass67.1 — caller-aware URL rewrite (same helper as RC + JWKS
            # paths above). Cloud-op callers get public :443 via Let's Encrypt
            # wildcard; mainframes keep the prior internal-alias behavior.
            # §2026-06-05 FIX — the fan-out is the mTLS `/federation/registry-cards`
            # endpoint, served ONLY on the :8443 federation gateway. The §pass67.1
            # cloud-op rewrite to bare :443 is correct for the PUBLIC `.well-known`
            # card pull but 401s the mTLS fan-out (:443 public ingress does not do
            # the client-cert auth /federation/* requires) → cloud-ops received
            # ZERO discovered cards = plain-orb globes. For a cloud-op caller, dial
            # the parent FRAME's federation base_url (:8443) directly — proven
            # reachable cloud-op→parent-frame with the correct mTLS cert (returns
            # the full fleet's cards). Mainframe callers keep the alias rewrite.
            _co_caller = os.getenv("REGISTRY_NAME", "").startswith("cloud-op-")
            if _co_caller:
                # §2026-06-23 FIX — the fan-out is the mTLS /federation endpoint, served ONLY on
                # the :8443 gateway (where client-cert auth runs). A peer advertising the public
                # host with NO explicit port (mainframes api/frame-b/frame-c.theprotocol.cloud
                # default to :443) must be dialed on :8443 — at :443 public ingress drops the SVID
                # -> 401. Cloud-op peers already carry their explicit gateway port (:8443/:27xxx) ->
                # keep as-is. PROVEN: op->mainframe :8443+SVID=200, :443+SVID=401. mTLS-only, no license.
                _b = parent.base_url.rstrip('/')
                if ':' not in _b.split('://', 1)[-1]:
                    _b = _b + ':8443'
                fanout_url = _b + '/api/v1/federation/registry-cards'
            else:
                fanout_url = (
                    _to_registry_dialable_url(parent.base_url.rstrip('/'))
                    + '/api/v1/federation/registry-cards'
                )

            # Build mTLS auth — same as agent-cards sync path
            client_config: Dict[str, Any] = {'timeout': 10.0}
            extra_headers: Dict[str, str] = {}
            if fanout_url.startswith('https://'):
                cert_config = svid_client.get_client_cert_config(target_url=fanout_url)
                if cert_config:
                    client_config.update(cert_config)
                else:
                    logger.debug(
                        "[RegistryCardFanout] peer=%s no mTLS cert; skip", parent.name
                    )
                    continue
            else:
                fed_license = os.environ.get("FEDERATION_LICENSE_KEY", "")
                if fed_license:
                    extra_headers = {"X-Federation-License": fed_license}
            if extra_headers:
                client_config['headers'] = extra_headers

            try:
                async with httpx.AsyncClient(**client_config) as client:
                    resp = await client.get(fanout_url)
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.info(
                    "[RegistryCardFanout] peer=%s connect/timeout: %s",
                    parent.name, e,
                )
                continue
            except Exception as e:
                logger.warning(
                    "[RegistryCardFanout] peer=%s unexpected: %s",
                    parent.name, e,
                )
                continue

            if resp.status_code != 200:
                logger.info(
                    "[RegistryCardFanout] peer=%s HTTP %s (endpoint may not exist yet)",
                    parent.name, resp.status_code,
                )
                continue

            try:
                cards = resp.json()
            except Exception as e:
                logger.warning(
                    "[RegistryCardFanout] peer=%s JSON parse failed: %s",
                    parent.name, e,
                )
                continue

            if not isinstance(cards, list):
                logger.warning(
                    "[RegistryCardFanout] peer=%s unexpected payload shape (not list)",
                    parent.name,
                )
                continue

            total_received += len(cards)

            # Match each card to our local peer_registries row (by name).
            # Insert if we don't have the peer yet (peer_type='discovered').
            for entry in cards:
                try:
                    peer_name = entry.get("peer_name")
                    card = entry.get("card")
                    if not peer_name or not isinstance(card, dict):
                        continue

                    # Don't overwrite our OWN row (the fanout filters this out
                    # server-side but defense in depth).
                    # §pass66.9 (2026-05-23) — name-based check missed the
                    # qatest15/qatest16 class (REGISTRY_NAME differs from peer_name).
                    # §pass66.11 (2026-05-23) — SPIFFE-ID check needed a fallback
                    # because `svid_client.get_spiffe_id()` returns None on
                    # cloud-ops (SPIRE socket not always wired at the right time).
                    # Now derives SVID from REGISTRY_NAME + SPIRE_TRUST_DOMAIN env
                    # whenever the live SPIRE call fails — both forms always equal
                    # the canonical `spiffe://<td>/registry/<name>` shape that
                    # `registry_card_builder` writes into `identity.spiffe_id`.
                    # §ONESHOT (2026-09-12) — ONE rule recognises our own card coming back (core/operator_names
                    # .is_own_fanout_entry): the fan-out name, the card's spiffe_id against the live SVID AND
                    # the canonical form, the card's registry_name against our slug. The live-SVID-only check
                    # missed every fresh cloud operator (its SVID is the cert-writer's), and the operator then
                    # inserted itself and dialed itself every cycle (runbook §8.5's hand step).
                    import os as _os_se
                    from ..core.operator_names import is_own_fanout_entry
                    from ..services.registry_card_builder import federation_name as _fed_name_se
                    _is_self, _self_why = is_own_fanout_entry(
                        peer_name, card, own_registry_name=settings.REGISTRY_NAME, own_spiffe=our_spiffe_id,
                        trust_domain=_os_se.environ.get("SPIRE_TRUST_DOMAIN"), own_federation_name=_fed_name_se())
                    if _is_self:
                        logger.debug(f"[RegistryCardFanout] Skipping self-echo peer={peer_name} ({_self_why})")
                        continue

                    async with AsyncSessionLocal() as db:
                        # Lookup by name — no dedicated CRUD helper, inline
                        # select is fine here (one query per upsert, ~30 ops
                        # per cycle on a typical fleet).
                        from sqlalchemy import select as _sel_pn, or_ as _or_pn
                        # §2026-05-30 — match by name OR base_url. The fan-out reports a
                        # peer under its REGISTRY_NAME (e.g. "sandboxalpha"), which differs
                        # from our local display name ("Sandbox Alpha") → the name-only
                        # lookup missed → the INSERT branch violated the UNIQUE base_url
                        # constraint (`peer_registries_base_url_key`) every cycle. base_url
                        # is unique + stable across both frames' views, so it's the reliable
                        # join key; falling back to it lets the fan-out UPDATE the existing
                        # row (and the peer_type guard below then correctly skips overwriting
                        # our directly-synced children).
                        # §HELLOFRAME D3 residue 2 (2026-09-18) — the name half is CASE-INSENSITIVE, the rule
                        # fanout_peer_name_allowed already applies (core/operator_names.py): a peer row `asia`
                        # and a fan-out entry `ASIA` are one peer. Measured on EU and ASIA: each held an INACTIVE
                        # `duplicate_frame` twin (`ASIA` beside `asia`, `EU` beside `eu`) whose base_url was the
                        # card's public console URL while the invitation row's was the federation lane, so the
                        # base_url half could not see them as one peer either. ONE predicate builder
                        # (fanout_peer_row_match), pinned by tests/test_fanout_peer_row_match.py.
                        _match = fanout_peer_row_match(peer_name, entry.get("base_url"))
                        peer_row = (await db.execute(
                            _sel_pn(models.PeerRegistry).where(_or_pn(*_match))
                            .order_by(models.PeerRegistry.id).limit(1)
                        )).scalars().first()
                        if peer_row is None:
                            # §FEDSYNCTRUTH (2026-09-03) — a NEW peer row is created only under a name
                            # the peer itself answers to (not a container label; equal to the card's
                            # own identity.registry_name). This is the structural end of the ghost
                            # class: a `discovered` row named op-singapore carrying losangeles's card
                            # lived on all 16 nodes because every receiver inserted whatever name a
                            # sender's table happened to hold. Refusals are counted, never silent.
                            from ..core.operator_names import fanout_peer_name_allowed
                            _ok, _why = fanout_peer_name_allowed(peer_name, card)
                            if _ok:
                                # §DIDWIDEN item 1 — G4 on a RELAYED card: its namespace must be its own
                                # trust domain (and the table entry's), never ours. Refusals are counted.
                                from ..services.registry_card_validator import check_card_namespace as _ns_check
                                _ns_why = _ns_check(card, peer_trust_domain=entry.get("trust_domain"))
                                if _ns_why:
                                    _ok, _why = False, _ns_why
                            if not _ok:
                                _fanout_refused(_why)
                                logger.info(
                                    f"[RegistryCardFanout] refused to create peer '{peer_name}' "
                                    f"({_why}; card says "
                                    f"{((card.get('identity') or {}).get('registry_name') if isinstance(card.get('identity'), dict) else None)!r})"
                                )
                                continue
                            # New peer discovered via fan-out — create a minimal
                            # row so subsequent BFS / federation_sync iterations
                            # see it. Cards-only context, peer_type='discovered'.
                            # owner_developer_id is NOT NULL on the table.
                            # §pass69.3 (2026-05-24) — was hardcoded =1 which
                            # fails FK on frames where dev_id=1 doesn't exist
                            # (Frame A's commander is id=10). Look up the
                            # lowest-id admin developer dynamically.
                            admin_id = (await db.execute(
                                select(models.Developer.id)
                                .where(models.Developer.is_admin == True)
                                .order_by(models.Developer.id)
                                .limit(1)
                            )).scalar_one_or_none() or 1
                            peer_row = models.PeerRegistry(
                                name=peer_name,
                                base_url=entry.get("base_url") or "",
                                status="ACTIVE",
                                peer_type="discovered",
                                trust_domain=entry.get("trust_domain"),
                                owner_developer_id=admin_id,
                                admin_contact_email="admin@local",
                                discovery_auth_info={},
                                health_check_failure_count=0,
                                total_interactions=0,
                                disputes_lost_with=0,
                                bayesian_discount=1.0,
                            )
                            db.add(peer_row)
                            await db.flush()
                        else:
                            # §pass66.1 (2026-05-23) — backfill trust_domain on
                            # existing peer rows that BFS discovered before the
                            # fan-out shipped (trust_domain on those was NULL).
                            # main.py:_build_topology_tiers reads trust_domain to
                            # surface visuals/fees; without this populated, the
                            # cached_registry_card payload never reaches the FE.
                            entry_td = entry.get("trust_domain")
                            if entry_td and not peer_row.trust_domain:
                                peer_row.trust_domain = entry_td
                            # §incident-2026-05-30 — the fan-out is a FALLBACK for
                            # peers this registry cannot reach directly (cross-frame
                            # `discovered` peers). It must NOT overwrite the card of a
                            # peer we sync DIRECTLY (our own frame / direct_peer /
                            # cloud_operator children): `_sync_registry_card` already
                            # wrote the authoritative fresh card for those, and a
                            # parent peer's cross-frame MIRROR of them is stale — it
                            # just bounces our own older card back. Without this guard
                            # the fan-out reverted a cloud-op child (Sandbox Alpha) to
                            # its stale mirror every cycle, immediately after the
                            # direct sync had fixed it. Commit any trust_domain
                            # backfill, then skip the card overwrite for our own
                            # directly-synced (non-discovered) peers.
                            #
                            # §FANOUTFIX (2026-08-05) — `peer_type != discovered` was
                            # the WRONG question. §MC-9 had already widened the DIRECT
                            # sync to include `discovered`-tagged peers that are really
                            # our own reachable ops (rename artifacts: op-newyork /
                            # op-losangeles on frame-b), but this guard was never
                            # widened to match. The two predicates disagreeing produced
                            # a permanent stale-beats-fresh loop, measured 2026-08-05:
                            # frame-b pulled op-losangeles DIRECTLY and logged
                            # `OK etag=4f22e548`, then ~4 s later the fan-out upserted a
                            # peer's older MIRROR over it and the row reverted to
                            # `ce2c11fe`. Since no other registry pulls those two
                            # directly, that stale card was then relayed mesh-wide and
                            # re-clobbered frame-b every cycle — the card had been
                            # frozen for weeks (it still lacked the jurisdiction block
                            # hours after every node had declared one). Ask the same
                            # question the direct sync asks.
                            if peer_row.peer_type != "discovered" or is_own_reachable_op(peer_row):
                                await db.commit()
                                continue

                        await crud_peer_registry.upsert_registry_card_from_peer(
                            db,
                            peer_row.id,
                            card,
                            etag=entry.get("card_etag"),
                            signature_verified=bool(entry.get("card_signature_verified")),
                            signature_kid=entry.get("card_signature_kid"),
                        )
                        await db.commit()
                        total_upserted += 1

                    # §2026-06-18 Federated Stock Cards CARRY: ingest this peer's
                    # relayed catalog (transitive cross-frame propagation). Own
                    # session, digest-anchored against the card we just cached,
                    # direct-wins guarded — see _ingest_carried_stock_card.
                    await self._ingest_carried_stock_card(card, entry.get("stock_card"), peer_name)
                except Exception as e:
                    logger.warning(
                        "[RegistryCardFanout] upsert failed peer=%s: %s",
                        entry.get("peer_name", "?"), e,
                    )

        if total_received > 0 or total_upserted > 0:
            logger.info(
                "[RegistryCardFanout] received=%d upserted=%d (across %d direct peer(s))",
                total_received, total_upserted, len(direct_peers),
            )

    async def _ingest_carried_stock_card(
        self,
        card: Dict[str, Any],
        sc_entry: Optional[Dict[str, Any]],
        peer_name: str,
    ) -> None:
        """§2026-06-18 Federated Stock Cards CARRY (consume side).

        Ingest a peer's catalog that arrived TRANSITIVELY on the registry-card
        fan-out (a parent frame relayed its cached copy) — the cross-frame case a
        direct pull can't reach. Trust is the digest ANCHOR: the catalog hash must
        equal the `fees.exchange.stock_card.digest` SIGNED into this same peer's
        relayed registry card (the card we just cached), so no origin JWKS fetch is
        needed. Guards: gated by STOCK_CARD_SYNC_ENABLED, own try/except (never
        touches the card cache / BFS / Δ), digest-gated (no churn), and DIRECT-WINS
        — a locally direct-consumed row (via_fanout=False) is authoritative and is
        never clobbered by a carried (possibly staler) copy.
        """
        if (os.getenv("STOCK_CARD_SYNC_ENABLED", "false") or "false").strip().lower() not in ("1", "true", "yes", "on"):
            return
        try:
            if not isinstance(sc_entry, dict):
                return
            listings = sc_entry.get("listings")
            if not isinstance(listings, list):
                return
            ident = card.get("identity") if isinstance(card.get("identity"), dict) else {}
            source_spiffe = ident.get("spiffe_id")
            if not source_spiffe:
                return
            # Never ingest our OWN catalog relayed back to us: a parent frame echoes
            # this registry's card on its fan-out, and the requester self-skip there can
            # miss when our live SVID or FEDERATION_NAME differs from our card spiffe /
            # REGISTRY_NAME (e.g. renamed ops: REGISTRY_NAME=cloud-op-op-london but
            # FEDERATION_NAME=op-london). Belt-and-suspenders self-skip by spiffe + name,
            # and proactively delete any self row a prior cycle mis-ingested.
            _own_spiffes = set()
            _rn = (os.getenv("REGISTRY_NAME") or "").strip()
            _td = (os.getenv("SPIRE_TRUST_DOMAIN") or "").strip().lower()
            if _rn and _td:
                _own_spiffes.add(f"spiffe://{_td}/registry/{_rn}".lower())
            _fn = (os.getenv("REGISTRY_FEDERATION_NAME") or "").strip()
            if _fn and _td:   # the card's spiffe since V0560 (registry_card_builder._build_spiffe_id)
                _own_spiffes.add(f"spiffe://{_td}/registry/{_fn}".lower())
            try:
                _live = (svid_client.get_spiffe_id() or "").strip().lower()
                if _live:
                    _own_spiffes.add(_live)
            except Exception:
                pass
            _own_names = {n for n in (
                (os.getenv("REGISTRY_NAME") or "").strip().lower(),
                (os.getenv("REGISTRY_FEDERATION_NAME") or "").strip().lower(),
            ) if n}
            if (source_spiffe or "").strip().lower() in _own_spiffes or (peer_name or "").strip().lower() in _own_names:
                try:
                    async with AsyncSessionLocal() as _dbself:
                        _selfrow = (await _dbself.execute(
                            select(models.FederatedStockCard).where(
                                models.FederatedStockCard.source_spiffe_id == source_spiffe
                            )
                        )).scalar_one_or_none()
                        if _selfrow is not None and _selfrow.via_fanout:
                            await _dbself.delete(_selfrow)
                            await _dbself.commit()
                            logger.info("[StockCardCarry] removed self-echo row peer=%s", peer_name)
                except Exception:
                    pass
                return
            anchor = (((card.get("fees") or {}).get("exchange") or {}).get("stock_card") or {}).get("digest")
            from agentvault_registry.services.stock_card_builder import catalog_digest
            cd = catalog_digest(listings)
            # Digest anchor (fail-closed): catalog hash == carried digest == the digest
            # signed into this peer's relayed registry card. Any mismatch → drop.
            if not anchor or cd != sc_entry.get("digest") or cd != anchor:
                logger.warning("[StockCardCarry] peer=%s digest anchor mismatch — drop (fail-closed)", peer_name)
                return
            async with AsyncSessionLocal() as db:
                row = await _stock_card_row(db, source_spiffe, peer_name)
                if row is not None:
                    if not row.via_fanout:
                        return  # direct row is AUTHORITATIVE — never clobber with a carry
                    # §2026-06-25 write on a catalog change OR a strictly-newer market epoch
                    # (never regress to a staler carried sparkline).
                    _in_ep = sc_entry.get("market_epoch")
                    _newer_market = (_in_ep is not None and (row.market_epoch is None or _in_ep > row.market_epoch))
                    if row.digest == cd and not _newer_market:
                        return  # digest-gate: catalog unchanged AND no newer market → skip
                now = datetime.now(timezone.utc)
                if row is None:
                    row = models.FederatedStockCard(source_spiffe_id=source_spiffe)
                    db.add(row)
                row.source_registry_name = peer_name
                row.currency = sc_entry.get("currency")
                row.listings_json = listings
                row.digest = cd
                _in_market = sc_entry.get("market")
                if isinstance(_in_market, dict):  # keep prior market on a pre-feature/empty relay
                    row.market_json = _in_market
                    row.market_epoch = sc_entry.get("market_epoch")
                row.signature_verified = bool(sc_entry.get("signature_verified"))
                row.via_fanout = True
                row.fetched_at = now
                row.updated_at = now
                await db.commit()
            logger.info(
                "[StockCardCarry] peer=%s carried %d listing(s) via fan-out digest=%s",
                peer_name, len(listings), (cd or "")[:20],
            )
        except Exception as e:
            logger.warning("[StockCardCarry] peer=%s isolated error: %s", peer_name, e)

    async def _sync_registry_card_standalone(self, peer: models.PeerRegistry, our_spiffe_id: str) -> bool:
        """Decoupled RC sync (§pass60.4) — builds its own auth context per call.

        Unlike `_sync_registry_card` which expected to be called within an open
        `_sync_with_peer` context (reusing `client_config` + `extra_headers`),
        this variant builds fresh auth from scratch for every peer. That way
        RC sync runs independently of agent-card sync's iteration constraints
        + failure modes.

        Returns True on cache update (200 / 304), False on any error.
        """
        # §pass67.1 (2026-05-23) — use the caller-aware helper to match the
        # URL that `_sync_registry_card` actually dials (line 620). Otherwise
        # cert_config gets built for an internal-alias URL while the request
        # goes to the public URL → cert chain validation fails silently.
        from agentvault_registry.routers.teg_integration import _to_registry_dialable_url

        sync_url = _to_registry_dialable_url(peer.base_url.rstrip('/'))

        # Build auth — same pattern as _sync_with_peer but isolated here.
        client_config: Dict[str, Any] = {'timeout': self.httpx_timeout}
        extra_headers: Dict[str, str] = {}

        if sync_url.startswith('https://'):
            cert_config = svid_client.get_client_cert_config(target_url=sync_url)
            if cert_config:
                client_config.update(cert_config)
            else:
                logger.warning("[RegistryCardSync] peer=%s no mTLS cert available; skip", peer.name)
                return False
        else:
            fed_license = os.environ.get("FEDERATION_LICENSE_KEY", "")
            if fed_license:
                extra_headers = {"X-Federation-License": fed_license}
            else:
                fed_secret = os.environ.get("FEDERATION_INTERNAL_SECRET", "")
                extra_headers = {
                    "X-Federation-Secret": fed_secret,
                    "X-Federation-SPIFFE-ID": our_spiffe_id,
                }

        try:
            await self._sync_registry_card(peer, client_config, extra_headers)
            return True
        except Exception as e:
            logger.warning("[RegistryCardSync] peer=%s standalone error: %s", peer.name, e)
            return False

    async def _digest_probe(self, client, peer: models.PeerRegistry, sync_url: str):
        """§FEDSYNC-V2 — fetch the peer's /sync-digest and compare against ours.

        Runs inside _sync_with_peer's client context so it inherits the exact
        auth (mTLS SVID / federation license / internal secret) and URL
        derivation of the card pull. Returns a verdict string; never raises.

        Comparison skips OUR OWN bucket: we are authoritative for our natives,
        and a peer whose view of them is stale heals it when ITS digest check
        against us fires — walking the peer cannot fix the peer's copy."""
        digest_url = sync_url.rsplit('/agent-cards', 1)[0] + '/sync-digest'
        try:
            resp = await client.get(digest_url)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[FED-DIGEST] fetch failed for {peer.name}: {e}")
            return False
        if resp.status_code in (404, 405):
            return "digest_unsupported"
        if resp.status_code in (401, 403):
            # Cross-frame peers refuse card pulls by design; same story here.
            await _note_card_pull_refusal(peer.name, "unauthorized")
            return "skipped"
        if resp.status_code != 200:
            logger.warning(f"[FED-DIGEST] {peer.name} answered HTTP {resp.status_code}")
            return False
        try:
            body = resp.json() or {}
            remote = body.get("buckets") or {}
            algo = body.get("algo")
        except Exception:  # noqa: BLE001
            return False
        if algo != "fedsync-digest-v1":
            # A peer speaking a digest algo we don't know is NOT comparable —
            # treat as unsupported so the legacy walk keeps the guarantee.
            logger.info(f"[FED-DIGEST] {peer.name} speaks unknown digest algo {algo!r}")
            return "digest_unsupported"
        local = await _compute_local_digest()
        if local is None:
            return False
        own_name, mine = local
        diffs: List[str] = []
        for bucket in set(mine) | set(remote):
            if bucket == own_name:
                continue
            m = mine.get(bucket)
            rb = remote.get(bucket)
            if (m is None or rb is None
                    or m.get("count") != rb.get("count")
                    or m.get("sum") != rb.get("sum")):
                diffs.append(bucket)
        # §TRAVELREC — a matching digest means the STORED corpora agree. It says nothing about
        # whether the peer has started deriving a new field onto what it exports, because that
        # changes no stored row. Agreeing on the cards and disagreeing on the projection is
        # exactly the state that made the work record invisible: the walk was deferred, so the
        # feed carrying the new extension was never read at all.
        _ver = body.get("export_version")
        _seen = await _last_export_version(peer.name)
        if _ver and _ver != _seen:
            logger.info(
                f"[FED-DIGEST] {peer.name}: export shape changed ({_seen!r} -> {_ver!r}) — "
                f"walking despite an equal digest"
            )
            await _note_export_version(peer.name, _ver)
            diffs = diffs or ["<export-shape-changed>"]
        if not diffs:
            logger.info(
                f"[FED-DIGEST] {peer.name}: corpora agree across "
                f"{len(remote)} origin buckets — reconcile walk deferred"
            )
            return "digest_equal"
        shown = ", ".join(sorted(diffs)[:6]) + ("…" if len(diffs) > 6 else "")
        logger.warning(f"[FED-DIGEST] {peer.name}: {len(diffs)} origin bucket(s) differ: {shown}")
        return "digest_mismatch"

    async def _process_peer_cards(self, peer: models.PeerRegistry, agent_cards: List[Dict[str, Any]]) -> bool:
        """Process agent cards received from a peer.
        
        Args:
            peer: The peer registry that sent the cards
            agent_cards: List of agent card data from the peer
            
        Returns:
            True if processing was successful
        """
        logger.info(f"Processing {len(agent_cards)} cards from peer {peer.name}")

        # ── §TRUSTPOLICY (2026-09-11) — THE SITE WHERE THE TRUST NUMBER BITES ──
        # Until now `bayesian_discount` was written by the settlement reactor,
        # rendered on three surfaces, and consumed for a decision in exactly ONE
        # place in the system (the EventStore's federation vote weight). A peer
        # could settle badly for a month and nothing happened but a smaller number
        # on a page. This is the one rail where withholding changes an outcome: a
        # peer this frame has come to distrust stops putting agents into this
        # frame's discovery.
        #
        # ⚠ DEFAULT IS `observe`: the verdict is computed and reported and NOTHING
        # is refused. Fail-open is correct until the frame opts in, exactly like
        # ENFORCEMENT_SLASH_MODE. And UNMEASURED is never actionable, so a peer
        # nobody has transacted with (sitting at the Beta(1,1) prior of 0.5) is
        # never mistaken for a peer that has behaved badly.
        try:
            from ..services import peer_trust_policy as _ptp
            from ..services.frame_policy import load as _load_frame_policy
            async with AsyncSessionLocal() as _pdb:
                _pol = await _load_frame_policy(_pdb)
            _verdict = _ptp.evaluate(peer, _pol)
            if _verdict.is_actionable:
                if _verdict.enforced:
                    logger.warning(
                        "[TRUSTPOLICY] REFUSED %d card(s) from peer=%s: %s",
                        len(agent_cards), peer.name, _verdict.reason)
                    _trust_ingest_counter(peer.name, _verdict.state, "refused")
                    await _emit_trust_action(peer, _verdict, len(agent_cards), refused=True)
                    return True   # handled deliberately — not an error, and not a retry
                logger.warning(
                    "[TRUSTPOLICY] observe: WOULD refuse %d card(s) from peer=%s: %s",
                    len(agent_cards), peer.name, _verdict.reason)
                _trust_ingest_counter(peer.name, _verdict.state, "observed")
                await _emit_trust_action(peer, _verdict, len(agent_cards), refused=False)
        except Exception as _e:  # noqa: BLE001
            # A trust evaluation that fails must never stop federation: fail OPEN,
            # but LOUDLY — a silent exception here would make the gate look like it
            # was passing every peer when it was in fact never running.
            logger.error("[TRUSTPOLICY] evaluation failed for peer=%s — ingesting anyway: %s",
                         getattr(peer, "name", "?"), _e, exc_info=True)
            _trust_ingest_counter(getattr(peer, "name", "?"), "error", "failed_open")

        # The presenter's SPIFFE ID = the peer ROW's trust domain + name (the canonical form the direct
        # registry-card sync already uses). §DIDWIDEN-1 closer (findings row 59): this used to be a legacy
        # `spiffe://agentvault.com/ns/agentvault/sa/registry-<name>` template, so every presenter on every
        # non-Frame-A network read as agentvault.com and anything keyed on it was wrong (the first G5 count
        # fired on honest relays). The flare-origin check compares NAMES (spiffe_canonical.canonical_equals),
        # so the canonical form is accepted exactly where the legacy one was.
        peer_spiffe_id = presenter_svid_for(peer)

        # §pass69.3 (2026-05-24) — Sort by id (UUID) BEFORE iterating so that
        # parallel _sync_with_peer tasks lock agent_cards rows in canonical
        # order. Without this, peer A locks card X then waits for Y while
        # peer B locks Y then waits for X → PostgreSQL DeadlockDetectedError
        # on the FOR UPDATE in upsert_agent_cards_from_peer (crud_peer_registry
        # :470). The FOR UPDATE itself is load-bearing (§pass34 flare merge),
        # so we serialize the lock order instead of removing it.
        agent_cards = sorted(agent_cards, key=lambda c: str(c.get('id', '')))

        # P3-004: Use async session
        async with AsyncSessionLocal() as db:
            try:
                cards_created = 0
                cards_updated = 0
                cards_skipped = 0
                cards_relay_ignored = 0

                # §ECHO (2026-09-28) — THE DIRECT COPY WINS: a relayed copy of a card whose origin we pull from
                # directly is not ingested (relayed_copy_of_direct_origin). A failure to read our peers leaves the
                # batch as it was before §ECHO: every copy goes to the ingest.
                try:
                    _direct = direct_source_names(
                        await crud_peer_registry.list_active_peer_registries_all(db, skip=0, limit=1000))
                except Exception as _dexc:  # noqa: BLE001
                    logger.warning("[FederationSync] could not read our direct sources (%s); relayed copies from %s "
                                   "are ingested this batch, as before", _dexc, peer.name)
                    _direct = set()

                for card_data in agent_cards:
                    if relayed_copy_of_direct_origin(card_data, peer.name, _direct):
                        cards_relay_ignored += 1
                        continue
                    # §2026-06-15 per-card SAVEPOINT: one bad card (e.g. a system card
                    # whose agent_did already exists locally → uix_agent_cards_agent_did
                    # IntegrityError) must NOT roll back the WHOLE peer batch. Isolate
                    # each upsert so the rest of the peer's cards still import.
                    try:
                        async with db.begin_nested():
                            result = await crud_peer_registry.upsert_agent_cards_from_peer(
                                db=db,
                                peer_svid=peer_spiffe_id,
                                agent_card=card_data,
                                peer_trust_domain=peer.trust_domain,
                                from_origin=is_origin_copy(card_data, peer.name),
                            )
                        if result == "created":
                            cards_created += 1
                        elif result == "updated":
                            cards_updated += 1
                        else:
                            cards_skipped += 1
                    except Exception as _card_exc:
                        cards_skipped += 1
                        if classify_card_skip(_card_exc) == "did_conflict":
                            # §DIDWIDEN: the collision class is a WARN + a counter, never a DEBUG line
                            _cdid = incoming_card_did(card_data)
                            _holder = await _local_did_holder(db, _cdid)
                            _count_did_conflict(peer.name, _holder)
                            logger.warning(
                                "[FederationSync] DID CONFLICT peer=%s did=%s card_id=%s is already held "
                                "locally by a %s row — mirror dropped, batch continues",
                                peer.name, _cdid, (card_data.get("id") if isinstance(card_data, dict) else None), _holder,
                            )
                        else:
                            logger.debug(
                                f"[FederationSync] skipped 1 card from {peer.name} "
                                f"({type(_card_exc).__name__}); batch continues"
                            )

                await db.commit()
                
                logger.info(
                    f"Sync with {peer.name} complete: "
                    f"{cards_created} created, {cards_updated} updated, {cards_skipped} skipped"
                    + (f", {cards_relay_ignored} relayed copies of a direct origin ignored" if cards_relay_ignored else "")
                )

                return True
                
            except Exception as e:
                logger.error(f"Error processing cards from peer {peer.name}: {e}")
                await db.rollback()
                return False
    
    async def _update_peer_sync_status(self, peer_id: int, success: bool,
                                       watermark: Optional[datetime] = None):
        """Update the sync status for a peer.

        Args:
            peer_id: ID of the peer registry
            success: Whether the sync was successful
            watermark: §SYNCPAGE — when the delta window OVERFLOWED the page
                limit, stamp last_synced_at with the walk cursor (max updated_at
                seen − 1s) instead of now(), so the next cycle resumes the walk.
                None (the caught-up case) keeps the historical now() semantics.
        """
        # P3-004: Use async session
        async with AsyncSessionLocal() as db:
            try:
                peer = await crud_peer_registry.get_peer_registry_by_id(db, peer_id)
                if peer and success:
                    # §CONSULFIX (2026-07-27): a SUCCESSFUL sync must also clear the failure
                    # bookkeeping. This path used to stamp `last_synced_at` and nothing else, so
                    # `last_sync_error` / `consecutive_sync_failures` kept whatever the last
                    # failure wrote — FOREVER. CONSUL's corridor view diagnoses from
                    # `last_sync_error`, so four corridors that had been healed and were syncing
                    # every cycle still rendered UNREACHABLE / certificate_mismatch with
                    # `fails=23`. A healed corridor that still reads broken is worse than no
                    # signal: it trains you to ignore the panel.
                    #
                    # Delegated to services/federation_reachability.record_outcome so there is ONE
                    # implementation of "a corridor answered" (it also stamps
                    # `last_sync_attempt_at`, which is why that column had been frozen).
                    # FAILURE is deliberately NOT delegated here: `success` at this call site can
                    # be a card-PROCESSING failure, and counting that as a corridor failure would
                    # misattribute an application error to network/TLS health. The helper path
                    # (federation_helper.py) remains the recorder of real corridor failures.
                    peer.last_synced_at = watermark or datetime.now(timezone.utc)
                    await db.commit()
                    try:
                        from agentvault_registry.services import federation_reachability
                        await federation_reachability.record_outcome(db, peer_id, ok=True)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("[FED-SYNC] record_outcome(ok) failed: %s", exc)
            except Exception as e:
                logger.error(f"Error updating peer sync status: {e}")


# Global instance
federation_sync_worker = FederationSyncWorker()


async def start_federation_sync():
    """Start the federation sync worker."""
    # Ensure SVID client is initialized for mTLS
    if not svid_client.is_initialized():
        logger.warning("SVID client not initialized, attempting to initialize for federation sync...")
        if not svid_client.initialize():
            logger.error("Failed to initialize SVID client - federation sync will not work without mTLS")
            return
    
    await federation_sync_worker.start()


async def stop_federation_sync():
    """Stop the federation sync worker."""
    await federation_sync_worker.stop()


def get_last_cycle_stats() -> Dict[str, Any]:
    """§pass29 Phase 6: read-only accessor for the most recent cycle stats."""
    return dict(_LAST_CYCLE_STATS)


def get_sync_interval() -> int:
    """§pass29 Phase 6: read-only accessor for the configured cycle interval."""
    return federation_sync_worker.sync_interval
