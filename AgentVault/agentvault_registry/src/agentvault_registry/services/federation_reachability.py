"""Federation reachability — is each corridor actually carrying traffic?

Born from a seven-week blind spot: frame-c could federate with only 6 of its 16 peers, and
every surface said healthy. `peer_registries` rows were `ACTIVE` with
`health_check_failure_count = 0`, `peer_sweep.sh` reported clean, the revival prober only
revives rows already marked INACTIVE, and the compliance overview tracked licence adherence
with no notion of whether a peer had ever answered. The single visible symptom — a smaller
federated agent list — reads as a product difference, not a fault.

The principle this module encodes:

    A peer is not healthy because it exists and was never marked bad.
    It is healthy because it ANSWERED RECENTLY.

So "never synced" becomes its own state rather than a NULL that sorts as fine, and every
finding carries a **diagnosis** — the difference between "op-london returns 401" and
"op-london does not list our trust domain", which is the difference between seven weeks and
one screen.

Read-only and side-effect free: it classifies rows that `federation_helper` records. It never
deactivates a peer or cuts a corridor — compliance here is observe-only
(`FEDERATION_ENFORCEMENT_ACTIVE=false`), and a metric going red must not sever federation.
"""
import datetime
import logging
import os
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models

logger = logging.getLogger(__name__)

# A corridor that has not carried traffic in this long is stale. Federation sync runs far
# more often than this, so the window is deliberately forgiving — we want "this corridor is
# dead", not "this corridor was briefly slow".
STALE_HOURS = float(os.getenv("FEDERATION_SYNC_STALE_HOURS", "6"))
# Grace before a freshly registered peer counts as NEVER_SYNCED: registration and first sync
# are not simultaneous, and a peer added minutes ago is not yet evidence of anything.
NEVER_GRACE_HOURS = float(os.getenv("FEDERATION_NEVER_SYNCED_GRACE_HOURS", "24"))
UNREACHABLE_FAILURES = int(os.getenv("FEDERATION_UNREACHABLE_FAILURES", "3"))

STATE_OK = "OK"
STATE_STALE = "STALE"
STATE_NEVER_SYNCED = "NEVER_SYNCED"
STATE_UNREACHABLE = "UNREACHABLE"
STATE_PENDING = "PENDING"          # registered inside the grace window — not yet a finding
# ── §DRIFTSKIP (2026-09-09) ──────────────────────────────────────────────────────────────────
# A peer this registry DELIBERATELY does not dial. §BATCH8 item 4: a `discovered` row whose trust
# domain belongs to an ACTIVE `frame` row is that frame's own operator — its cards reach us through
# the frame's export, and a direct pull is refused 401 every cycle by a proxy that never federated
# with us. Its `last_synced_at` can never advance, so before this state it read as STALE for ever
# and counted against "corridors reachable" (EU showed 3/5 with two rows that were never corridors).
# It is NOT a finding and NOT a corridor; it is listed so nobody thinks it was silenced.
STATE_NOT_DIALLED = "NOT_DIALLED"

SEVERITY = {
    STATE_OK: "ok",
    STATE_PENDING: "info",
    STATE_NOT_DIALLED: "info",
    STATE_STALE: "warning",
    STATE_UNREACHABLE: "warning",
    STATE_NEVER_SYNCED: "critical",
}


def diagnose(error: Optional[str]) -> Dict[str, Optional[str]]:
    """Turn a raw error string into an actionable cause.

    Ordered most-specific first. The trust-domain case is deliberately the first thing we
    look for: it is what actually happened, it is invisible in a plain 401, and it has a
    one-line fix (add the domain to the peer's TRUSTED_SPIFFE_DOMAINS and restart it).
    """
    if not error:
        return {"diagnosis": None, "remedy": None}
    e = error.lower()

    if "untrusted domain" in e or ("401" in e and "federation authentication" in e):
        return {
            "diagnosis": "trust_domain_not_accepted",
            "remedy": ("The peer does not list our SPIFFE trust domain in its "
                       "TRUSTED_SPIFFE_DOMAINS. Add it on the peer and restart its registry "
                       "(the value is read once at import)."),
        }
    if "hostname mismatch" in e or "certificate verify failed" in e or "ssl" in e:
        return {
            "diagnosis": "certificate_mismatch",
            "remedy": ("The peer's certificate does not cover the hostname we dial — usually a "
                       "renamed operator whose SVID DNS SANs were never reissued."),
        }
    if "name or service not known" in e or "nodename nor servname" in e or "getaddrinfo" in e:
        return {
            "diagnosis": "dns_unresolvable",
            "remedy": "The peer's base_url does not resolve from this frame. Stale row or dead host.",
        }
    if "timeout" in e or "timed out" in e:
        return {
            "diagnosis": "timeout",
            "remedy": "The peer accepted the connection but did not answer in time. Often transient.",
        }
    if "connect" in e or "connection refused" in e:
        return {
            "diagnosis": "connection_refused",
            "remedy": "Nothing is listening at the peer's base_url.",
        }
    if "403" in e:
        return {
            "diagnosis": "forbidden",
            "remedy": "Authenticated but not authorised — check the federation licence and peer status.",
        }
    return {"diagnosis": "unknown", "remedy": None}


def _aware(dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def classify(
    peer: models.PeerRegistry,
    now: Optional[datetime.datetime] = None,
    *,
    not_dialled: bool = False,
) -> Dict[str, Any]:
    """Classify one peer's corridor. Pure — no I/O, no writes.

    `not_dialled` is decided by the CALLER because the answer needs the whole peer list (which
    trust domains belong to an ACTIVE frame), and this function is deliberately pure.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    last_sync = _aware(getattr(peer, "last_synced_at", None))
    registered = _aware(getattr(peer, "registered_at", None))
    attempted = _aware(getattr(peer, "last_sync_attempt_at", None))
    failures = int(getattr(peer, "consecutive_sync_failures", 0) or 0)
    error = getattr(peer, "last_sync_error", None)

    age_seconds: Optional[float] = (now - last_sync).total_seconds() if last_sync else None

    if not_dialled:
        state = STATE_NOT_DIALLED
    elif last_sync is None:
        registered_age_h = ((now - registered).total_seconds() / 3600.0) if registered else None
        if registered_age_h is not None and registered_age_h < NEVER_GRACE_HOURS:
            state = STATE_PENDING
        else:
            state = STATE_NEVER_SYNCED
    elif age_seconds is not None and age_seconds > STALE_HOURS * 3600:
        state = STATE_STALE
    elif failures >= UNREACHABLE_FAILURES:
        # Answered at some point, failing repeatedly now.
        state = STATE_UNREACHABLE
    else:
        state = STATE_OK

    d = diagnose(error)
    # ── §29e — NAME THE STATE YOU CANNOT DIAGNOSE ────────────────────────────────────────────
    # `diagnose()` reads `last_sync_error`, and that field is only ever written by an ATTEMPT
    # (`record_outcome`). So a peer that was never dialled, or dialled without recording an error,
    # rendered `—` in BOTH the "Diagnosis" and "What to do" columns — the two columns that exist
    # to tell an operator what to do, blank in exactly the cases they are for. Three states, said
    # out loud, rather than one em dash standing for all of them.
    if d["diagnosis"] is None:
        if state == STATE_NOT_DIALLED:
            d = {
                "diagnosis": "not dialled by design",
                "remedy": ("No action. This is a federated frame's own operator: its cards reach "
                           "us through that frame's export, and a direct pull would be refused by "
                           "a proxy that never federated with us."),
            }
        elif state in (STATE_OK, STATE_PENDING):
            d = {"diagnosis": None, "remedy": None}      # nothing wrong, nothing to say
        elif attempted is None:
            d = {
                "diagnosis": "never attempted",
                "remedy": ("Nothing has dialled this peer, so there is no error to read. Check "
                           "that federation_sync considers it syncable (peer_type, licence gate) "
                           "before looking at the URL or the certificates."),
            }
        else:
            d = {
                "diagnosis": "attempted, no error recorded",
                "remedy": ("The corridor was dialled and left no error string. Read the "
                           "federation_sync log for this peer — this is a gap in what we record, "
                           "not evidence that the peer is healthy."),
            }
    return {
        "peer": peer.name,
        "peer_id": getattr(peer, "id", None),
        "base_url": peer.base_url,
        "peer_type": getattr(peer, "peer_type", None),
        "trust_domain": getattr(peer, "trust_domain", None),
        "spiffe_id": getattr(peer, "spiffe_id", None),
        "status": peer.status,
        "state": state,
        "severity": SEVERITY.get(state, "info"),
        "last_synced_at": last_sync.isoformat() if last_sync else None,
        "last_sync_attempt_at": attempted.isoformat() if attempted else None,
        "last_sync_age_seconds": int(age_seconds) if age_seconds is not None else None,
        "registered_at": registered.isoformat() if registered else None,
        "age_days_since_registration": (
            int((now - registered).total_seconds() // 86400) if registered else None
        ),
        "consecutive_sync_failures": failures,
        "last_sync_error": (error[:300] if error else None),
        "diagnosis": d["diagnosis"],
        "remedy": d["remedy"],
    }


async def build_report(db: AsyncSession, *, include_ok: bool = False) -> Dict[str, Any]:
    """Fleet-wide reachability, shaped for the compliance overview and the FE.

    `include_ok=False` returns only the peers worth acting on, so the finding is not buried
    in a wall of healthy rows; the counts always cover everything.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    rows = (await db.execute(select(models.PeerRegistry))).scalars().all()

    # §DRIFTSKIP — ONE PREDICATE, EVERY CALLER. The syncer's skip is decided here so this report
    # and the drift monitor and federation_sync all answer the same question about the same row.
    try:
        from ..background_tasks.federation_sync import is_peer_frames_operator
        _skip = {getattr(p, "id", None) for p in rows if is_peer_frames_operator(p, rows)}
    except Exception as e:  # noqa: BLE001
        # LOUD, and it degrades to the old behaviour rather than mislabelling anything: with no
        # skip set every peer is classified as before. "I could not ask" is not "the answer is no".
        logger.warning("[reachability] could not evaluate the not-dialled predicate (%s) — "
                       "corridors fall back to pre-2026-09-09 classification", e)
        _skip = set()

    classified = [classify(p, now, not_dialled=getattr(p, "id", None) in _skip) for p in rows]
    active = [c for c in classified if (c["status"] or "").upper() == "ACTIVE"]

    counts: Dict[str, int] = {}
    for c in active:
        counts[c["state"]] = counts.get(c["state"], 0) + 1

    findings = [c for c in active
                if c["state"] not in (STATE_OK, STATE_PENDING, STATE_NOT_DIALLED)]
    findings.sort(key=lambda c: (c["severity"] != "critical", c["peer"] or ""))

    # A row that is not a corridor must not be counted as a BROKEN corridor. EU read "3 of 5
    # answering" while two of the five were never dialled by design; the honest denominator is
    # the corridor population, and the excluded count is published beside it rather than dropped.
    not_dialled_n = counts.get(STATE_NOT_DIALLED, 0)
    # §REACHGAUGE (2026-09-28): the same holds for a peer inside its never-synced grace. This module
    # calls it "not yet evidence of anything" and keeps it out of the findings, while the ratio
    # counted it as a corridor that did not answer: sbx-beta read "2 of 3" beside "Every active peer
    # answered within the window" for a kit frame registered two hours earlier, and
    # FederationCorridorDegraded fired on it. Out of the denominator, published beside it; the grace
    # ends as NEVER_SYNCED, which counts again.
    pending_n = counts.get(STATE_PENDING, 0)
    total_active = len(active) - not_dialled_n - pending_n
    reachable = counts.get(STATE_OK, 0)

    report = {
        "generated_at": now.isoformat(),
        "window": {
            "stale_hours": STALE_HOURS,
            "never_synced_grace_hours": NEVER_GRACE_HOURS,
            "unreachable_after_failures": UNREACHABLE_FAILURES,
        },
        "peers_total": len(classified),
        "peers_active": total_active,
        # published, not hidden — the reader can see what was taken out of the ratio and why
        "peers_not_dialled": not_dialled_n,
        "peers_pending": pending_n,
        "reachable": reachable,
        "reachable_ratio": round(reachable / total_active, 4) if total_active else None,
        "counts": counts,
        "findings": findings,
        "peers": classified if include_ok else None,
        # Named so a reader knows what "healthy" means here without opening the code.
        "definition": ("A peer is reachable when it answered a federation fan-out within "
                       f"{STALE_HOURS}h. NEVER_SYNCED means it has not answered once since "
                       "registration — the state that hid the frame-c gap for seven weeks. "
                       "NOT_DIALLED peers are excluded from the ratio: they are a federated "
                       "frame's own operators, reached through that frame's export, and were "
                       "never corridors of ours to begin with. PENDING peers (registered less "
                       f"than {NEVER_GRACE_HOURS:g}h ago, not answered yet) are excluded too "
                       "until their grace ends."),
    }
    # The gauges are published from EVERY row whatever the response carries: a findings-only read
    # must still refresh the healthy corridors and retract the rows that left (§REACHGAUGE).
    publish_metrics(report if include_ok else {**report, "peers": classified})
    return report


async def record_outcome(
    db: AsyncSession,
    peer_id: Any,
    *,
    ok: bool,
    error: Optional[str] = None,
) -> None:
    """Persist one corridor outcome. Best-effort: never breaks the fan-out that called it.

    Success sets `last_synced_at` too, so "answered a discovery query" and "synced" share one
    freshness signal — the frame-c gap was invisible partly because those were separate ideas
    with only one of them recorded.
    """
    try:
        row = (await db.execute(
            select(models.PeerRegistry).where(models.PeerRegistry.id == peer_id)
        )).scalar_one_or_none()
        if row is None:
            return
        now = datetime.datetime.now(datetime.timezone.utc)
        row.last_sync_attempt_at = now
        if ok:
            row.last_synced_at = now
            row.consecutive_sync_failures = 0
            row.last_sync_error = None
        else:
            row.consecutive_sync_failures = int(row.consecutive_sync_failures or 0) + 1
            row.last_sync_error = (error or "unknown error")[:500]
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[REACHABILITY] could not record outcome for peer %s: %s", peer_id, exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


# ── Prometheus ────────────────────────────────────────────────────────────────
# multiprocess_mode='livemostrecent' to match the IRONHAND gauges: under gunicorn with
# many workers, the latest write wins and dead workers are ignored.
try:
    from prometheus_client import Gauge

    PEER_LAST_SYNC_AGE = Gauge(
        "federation_peer_last_sync_age_seconds",
        "Seconds since this peer last answered a federation fan-out (+Inf = never; NaN = not a "
        "judged corridor: inactive, pending or not dialled by design)",
        ["peer", "peer_type"],
        multiprocess_mode="livemostrecent",
    )
    PEER_STATE = Gauge(
        "federation_peer_state",
        "1 for the peer's current reachability state",
        ["peer", "state", "diagnosis"],
        multiprocess_mode="livemostrecent",
    )
    PEERS_REACHABLE_RATIO = Gauge(
        "federation_peers_reachable_ratio",
        "Fraction of judged corridors (ACTIVE, not pending, not dialled by design) that answered "
        "within the staleness window (NaN = no corridor to judge)",
        multiprocess_mode="livemostrecent",
    )
    PEERS_NEVER_SYNCED = Gauge(
        "federation_peers_never_synced",
        "ACTIVE peers that have never answered once since registration",
        multiprocess_mode="livemostrecent",
    )
    _PROM = True
except Exception:  # noqa: BLE001 — metrics are never load-bearing
    _PROM = False


# ── §REACHGAUGE (2026-09-28): WHAT A SERIES MAY SAY, AND FOR HOW LONG ─────────────────────────────
# Measured on sbx-beta: a kit frame's row went INACTIVE at 17:59Z and FederationPeerStale kept firing
# on it at +Inf, beside FederationCorridorDegraded at 2/3, for hours. Three defects:
#   (1) Only a USER read published (a federated discovery search, the compliance view), so between
#       reads every series said what the last read saw: frozen trouble on sbx-beta (17:22Z), and on
#       EU, ASIA and their operators no series at all, so the three alerts could not fire there.
#       The sync cycle publishes now (federation_sync._publish_reachability).
#   (2) A series outlived its row. Only ACTIVE rows were written and nothing retracted one, and a
#       multiprocess gauge cannot remove a label set (each worker's mmap file keeps it). Retraction
#       is a WRITE: NaN, the newest sample under livemostrecent, which no comparison matches.
#   (3) The export judged what the report does not. A PENDING peer ("not yet evidence of anything")
#       went out as never-answered (+Inf), and a NOT_DIALLED peer (reached through its frame by
#       design) exported an age that only grows: the pre-flight on the production operators would
#       have fired FederationPeerStale on four such rows each. Only a judged corridor has an age.
_JUDGED = frozenset({STATE_OK, STATE_STALE, STATE_UNREACHABLE, STATE_NEVER_SYNCED})
_NAN = float("nan")
# The label sets THIS process has written, per peer, so a later publish can retract them when a
# peer's type or state changes or its row disappears. Per process by nature (see (2)); the sync
# cycle republishes every row each cycle, which is what retires the series of a row that stayed.
_AGE_SERIES: Dict[str, set] = {}      # peer -> {peer_type}
_STATE_SERIES: Dict[str, set] = {}    # peer -> {(state, diagnosis)}
_WARNED_AT: List[Optional[float]] = [None]


def publish_metrics(report: Dict[str, Any]) -> None:
    """Publish a report to Prometheus. Never raises: a metrics failure is not an outage.

    A report WITH `peers` (every row) is authoritative: each row gets a series, and a series this
    process wrote for a row that is no longer listed is retracted. A findings-only report updates
    what it lists and retracts nothing, because what it leaves out is not gone.
    """
    if not _PROM:
        return
    try:
        full = report.get("peers") is not None
        peers = report.get("peers") if full else (report.get("findings") or [])
        listed = set()
        for c in peers:
            name = c.get("peer") or "unknown"
            ptype = c.get("peer_type") or "unknown"
            listed.add(name)
            active = (c.get("status") or "").upper() == "ACTIVE"
            state = c.get("state") or "unknown"

            if active and state in _JUDGED:
                age = c.get("last_sync_age_seconds")
                value = float(age) if age is not None else float("inf")
            else:
                value = _NAN
            types = _AGE_SERIES.setdefault(name, set())
            for old in types - {ptype}:
                PEER_LAST_SYNC_AGE.labels(peer=name, peer_type=old).set(_NAN)
            PEER_LAST_SYNC_AGE.labels(peer=name, peer_type=ptype).set(value)
            _AGE_SERIES[name] = {ptype}

            current = (state, c.get("diagnosis") or "none") if active else None
            combos = _STATE_SERIES.setdefault(name, set())
            for s, d in combos - {current}:
                PEER_STATE.labels(peer=name, state=s, diagnosis=d).set(0)
            if current is not None:
                PEER_STATE.labels(peer=name, state=current[0], diagnosis=current[1]).set(1)
            _STATE_SERIES[name] = {current} if current is not None else set()

        if full:
            for name in [n for n in _AGE_SERIES if n not in listed]:
                for t in _AGE_SERIES.pop(name):
                    PEER_LAST_SYNC_AGE.labels(peer=name, peer_type=t).set(_NAN)
            for name in [n for n in _STATE_SERIES if n not in listed]:
                for s, d in _STATE_SERIES.pop(name):
                    PEER_STATE.labels(peer=name, state=s, diagnosis=d).set(0)

        ratio = report.get("reachable_ratio")
        # No corridor to judge is not "every corridor answers" and not the last value either.
        PEERS_REACHABLE_RATIO.set(float(ratio) if ratio is not None else _NAN)
        PEERS_NEVER_SYNCED.set(float((report.get("counts") or {}).get(STATE_NEVER_SYNCED, 0)))
    except Exception as exc:  # noqa: BLE001
        # Loud but rare: a publish that fails every cycle freezes the gauges, which is the defect
        # this function exists to prevent, so it must be seen; once per ten minutes is enough.
        import time as _t
        now_m = _t.monotonic()
        if _WARNED_AT[0] is None or now_m - _WARNED_AT[0] > 600:
            _WARNED_AT[0] = now_m
            logger.warning("[REACHABILITY] metric publish failed, the reachability gauges are "
                           "not moving: %s", exc)


def summarize_for_metrics(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten a report into metric-ready rows (peer, state, age)."""
    out = []
    for c in (report.get("peers") or report.get("findings") or []):
        out.append({
            "peer": c["peer"],
            "state": c["state"],
            "age_seconds": c["last_sync_age_seconds"],
            "diagnosis": c["diagnosis"],
        })
    return out
