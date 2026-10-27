"""§AGENTDISC #186 — Agent track record: registry-attested guild work history (2026-08-16).

The registry ATTESTS what its own books prove, and only that:
  - **Local engagements** — settled `guild_work_orders` on THIS registry (the host book).
    Stars come from the append-only `guild_order_events` verified audit, never from the
    order row or the agent.
  - **Traveled engagements** — `guild_travel_credentials` rows (the home book): work done
    on OTHER registries whose Ed25519 credential was signature-verified at ingestion
    (`receive_work_credential` stores nothing unverifiable, so `verified` rows are proof).

The agent can never author these numbers. On discovery surfaces they ride the
registry-owned enrichment channel (like `flare`) — never agent `card_data` — and the
A2A card carries only an extension POINTER to the attestation endpoint (#187).

Verifiability layers per engagement (the receipts drawer, #188):
  1. **Digest binding** — each row carries `receipt_digest` = sha256 over the canonical
     `guild.receipt.v1` subset (sorted keys, tight separators, ensure_ascii — the SAME
     browser-recomputable convention as vcsign's `contract_attestation_digest` and the
     attestation signer's `_canonical_bytes`). The receipt endpoint serves the subset;
     the browser recomputes and compares against the listed digest.
  2. **Ed25519 attestation** — the work credential bundle (stored for traveled rows;
     deterministically re-issued on demand for local rows — Ed25519 over identical
     canonical bytes yields the identical signature) verifies offline against the
     registry's published attestation-signer pubkey.
  3. **Ledger trail** — `contract_id` links the spine mirror contract (V0182: 35/35
     settled orders carry one on frame-c).

Read-only over money rails. Δ-irrelevant by construction.
"""
from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

RECEIPT_KIND = "guild.receipt.v1"

# §AGENTDISC #187 — the A2A v1.0 vendor extension URI (AgentExtension in
# capabilities.extensions[], required:false ⇒ strict clients ignore it; sibling of
# .../extensions/v1/auth/did-jwt-self-signed). POINTER-ONLY on the public card: the
# extension never carries attested numbers into agent-declarable content, so even if
# an SDK agent re-registers its exported card verbatim, the only thing that can loop
# back is a stable URL — the numbers stay registry-attested behind the endpoint.
TRACK_RECORD_EXTENSION_URI = "https://theprotocol.cloud/extensions/v1/track-record"

# Latest verified-event stars per order (append-only audit is the source of truth).
_VSTARS_CTE = """
    WITH vstars AS (
        SELECT DISTINCT ON (order_id)
               order_id, NULLIF(payload->>'stars','')::int AS stars
        FROM guild_order_events
        WHERE event_type = 'verified'
        ORDER BY order_id, seq DESC
    )
"""


def _iso(v: Any) -> Optional[str]:
    return v.isoformat() if v is not None else None


def receipt_digest(subset: Dict[str, Any]) -> str:
    """sha256 over the canonical subset — sibling of `contract_attestation_digest`
    (regulatory_auth) and `attestation_signer._canonical_bytes`: sorted keys, tight
    separators, ensure_ascii (default) so a browser reproduces it with recursive key
    sort + JSON.stringify + a \\uXXXX escape pass over everything >= 0x7f.
    The subset is built from ALREADY-stringified values (no default= coercion), so the
    digested bytes and the served JSON are the same object byte-for-byte."""
    canonical = json.dumps(subset, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_receipt_subset(row: Dict[str, Any], stars: Optional[int]) -> Dict[str, Any]:
    """The `guild.receipt.v1` canonical subset: engagement FACTS only (registry envelope
    metadata like attested_by stays outside the digested subset). All values are
    plain str/int/None — pre-stringified so digest input == served JSON."""
    return {
        "kind": RECEIPT_KIND,
        "order_id": row["id"],
        "contract_id": row.get("contract_id"),
        "title": row.get("title"),
        "poster_did": row["poster_did"],
        "worker_did": row["worker_did"],
        "payee_did": row.get("payee_did"),
        "payee_org_id": row.get("payee_org_id"),
        "bounty": row.get("bounty_text"),
        "currency": row.get("currency"),
        "fee_charged": row.get("fee_text"),
        "stars": stars,
        "awarded_at": _iso(row.get("awarded_at")),
        "submitted_at": _iso(row.get("submitted_at")),
        "settled_at": _iso(row.get("settled_at")),
        "worker_home_registry": row.get("worker_home_registry"),
    }


def _on_time(row: Dict[str, Any]) -> Optional[bool]:
    """Honest on-time verdict: only orders whose AWARDED bid carried an eta promise
    enter the denominator (deadline on the order is the bidding deadline, not delivery)."""
    eta = row.get("eta_seconds")
    if eta is None or row.get("awarded_at") is None or row.get("submitted_at") is None:
        return None
    try:
        return (row["submitted_at"] - row["awarded_at"]).total_seconds() <= float(eta)
    except Exception:  # noqa: BLE001
        return None


async def track_record_summaries(db: AsyncSession, dids: List[str]) -> Dict[str, Dict[str, Any]]:
    """ONE grouped pass per book for a page of DIDs (discovery join, no N+1).
    Returns {did: summary} — DIDs with zero history are simply absent."""
    dids = sorted({d for d in dids if d})
    if not dids:
        return {}
    p = {"dids": dids}
    exp = [bindparam("dids", expanding=True)]

    local_rows = (await db.execute(text(_VSTARS_CTE + """
        SELECT o.worker_did,
               count(*)                                                        AS local_jobs,
               count(v.stars)                                                  AS starred,
               COALESCE(sum(v.stars), 0)                                       AS star_sum,
               count(*) FILTER (WHERE v.stars = 5)                             AS five_star,
               count(*) FILTER (WHERE b.eta_seconds IS NOT NULL
                                AND o.awarded_at IS NOT NULL
                                AND o.submitted_at IS NOT NULL)                AS eta_of,
               count(*) FILTER (WHERE b.eta_seconds IS NOT NULL
                                AND o.awarded_at IS NOT NULL
                                AND o.submitted_at IS NOT NULL
                                AND o.submitted_at <= o.awarded_at
                                    + make_interval(secs => b.eta_seconds))    AS eta_met,
               count(DISTINCT o.poster_did)                                    AS distinct_posters,
               count(*) FILTER (WHERE o.worker_home_registry IS NOT NULL)      AS foreign_home_jobs,
               min(o.settled_at)                                               AS first_at,
               max(o.settled_at)                                               AS last_at
        FROM guild_work_orders o
        LEFT JOIN vstars v ON v.order_id = o.id
        LEFT JOIN guild_bids b ON b.id = o.awarded_bid_id
        WHERE o.status = 'settled' AND o.worker_did IN :dids AND o.worker_did <> ''
        GROUP BY o.worker_did
    """).bindparams(*exp), p)).mappings().all()

    disputes = (await db.execute(text("""
        SELECT worker_did,
               count(*)                                     AS disputes,
               count(*) FILTER (WHERE status = 'refunded')  AS lost,
               count(*) FILTER (WHERE status = 'disputed')  AS open
        FROM guild_work_orders
        WHERE dispute_id IS NOT NULL AND worker_did IN :dids AND worker_did <> ''
        GROUP BY worker_did
    """).bindparams(*exp), p)).mappings().all()

    volume = (await db.execute(text("""
        SELECT worker_did, currency, sum(bounty)::text AS total, count(*) AS jobs
        FROM guild_work_orders
        WHERE status = 'settled' AND worker_did IN :dids AND worker_did <> ''
        GROUP BY worker_did, currency
    """).bindparams(*exp), p)).mappings().all()

    travel = (await db.execute(text("""
        SELECT worker_did,
               count(*)                                AS jobs,
               count(stars)                            AS starred,
               COALESCE(sum(stars), 0)                 AS star_sum,
               count(*) FILTER (WHERE stars = 5)       AS five_star,
               count(DISTINCT host_registry)           AS hosts,
               min(received_at)                        AS first_at,
               max(received_at)                        AS last_at
        FROM guild_travel_credentials
        WHERE verified AND worker_did IN :dids
        GROUP BY worker_did
    """).bindparams(*exp), p)).mappings().all()

    travel_volume = (await db.execute(text("""
        SELECT worker_did, currency, sum(bounty)::text AS total, count(*) AS jobs
        FROM guild_travel_credentials
        WHERE verified AND worker_did IN :dids AND currency IS NOT NULL
        GROUP BY worker_did, currency
    """).bindparams(*exp), p)).mappings().all()

    out: Dict[str, Dict[str, Any]] = {}

    def _base(did: str) -> Dict[str, Any]:
        return out.setdefault(did, {
            "jobs_verified": 0, "local_jobs": 0, "traveled_jobs": 0,
            "avg_stars": None, "five_star": 0, "_star_sum": 0, "_starred": 0,
            "on_time": {"met": 0, "of": 0},
            "disputes": {"total": 0, "lost": 0, "open": 0},
            "volume": [],
            "cross_registry_jobs": 0, "distinct_hosts": 0,
            "distinct_posters": 0, "repeat_poster_jobs": 0,
            "first_verified_at": None, "last_verified_at": None,
        })

    def _minmax(s: Dict[str, Any], first, last) -> None:
        fi, la = _iso(first), _iso(last)
        if fi and (s["first_verified_at"] is None or fi < s["first_verified_at"]):
            s["first_verified_at"] = fi
        if la and (s["last_verified_at"] is None or la > s["last_verified_at"]):
            s["last_verified_at"] = la

    for r in local_rows:
        s = _base(r["worker_did"])
        s["local_jobs"] = int(r["local_jobs"])
        s["_starred"] += int(r["starred"]); s["_star_sum"] += int(r["star_sum"])
        s["five_star"] += int(r["five_star"])
        s["on_time"] = {"met": int(r["eta_met"]), "of": int(r["eta_of"])}
        s["distinct_posters"] = int(r["distinct_posters"])
        s["repeat_poster_jobs"] = max(0, int(r["local_jobs"]) - int(r["distinct_posters"]))
        s["cross_registry_jobs"] += int(r["foreign_home_jobs"])
        _minmax(s, r["first_at"], r["last_at"])

    for r in disputes:
        s = _base(r["worker_did"])
        s["disputes"] = {"total": int(r["disputes"]), "lost": int(r["lost"]), "open": int(r["open"])}

    for r in travel:
        s = _base(r["worker_did"])
        s["traveled_jobs"] = int(r["jobs"])
        s["_starred"] += int(r["starred"]); s["_star_sum"] += int(r["star_sum"])
        s["five_star"] += int(r["five_star"])
        s["cross_registry_jobs"] += int(r["jobs"])
        s["distinct_hosts"] = int(r["hosts"])
        _minmax(s, r["first_at"], r["last_at"])

    vol_map: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for r in list(volume) + list(travel_volume):
        cur = vol_map.setdefault(r["worker_did"], {}).setdefault(
            r["currency"], {"currency": r["currency"], "total": "0", "jobs": 0})
        # sum the two books' Numeric-text totals without float drift
        cur["total"] = str(Decimal(cur["total"]) + Decimal(r["total"]))
        cur["jobs"] += int(r["jobs"])

    for did, s in out.items():
        s["jobs_verified"] = s["local_jobs"] + s["traveled_jobs"]
        if s["_starred"]:
            s["avg_stars"] = round(s["_star_sum"] / s["_starred"], 2)
        s["volume"] = sorted(vol_map.get(did, {}).values(), key=lambda v: v["currency"])
        del s["_star_sum"], s["_starred"]

    return out


# ─── §MARKSURFACES (2026-09-10) — ONE projection, read by every avatar surface ──────
#
# His report: *"we had a ranking display on the avatar man this got compeltly lost … i
# dont understand what made it go lost our ranking system avatar overlay."*
#
# The mark itself was never broken. What was missing is that only TWO of ~22 surfaces
# ever ASKED for a track record: Discovery and the agent modal, both reading
# `/agent-cards/discover`, which built this dict INLINE. Leaderboard — the ranking page
# itself — the header agent switcher, My Agents and a dozen others mounted `<UserAvatar>`
# and passed nothing, so they were structurally incapable of showing a mark however many
# jobs an agent had verified.
#
# §FANOUTFIX's rule: when several callers must ask the same question, the answer belongs
# in ONE place. This is that place. `agent_cards.discover` and every enrichment endpoint
# now build the compact row here, so a key renamed on one side can never mean a silently
# empty ring on the other (the exact defect `compactFromSummary`'s own docstring records
# on the FE side: `jobs_verified` vs `jobs`, and the globe rendered no mark for weeks).
def compact_track_record(summary: Dict[str, Any]) -> Dict[str, Any]:
    """The `TrackRecordCompact` shape the FE's `earnedMarks()` reads, from one summary."""
    return {
        "jobs": summary["jobs_verified"],
        "stars": summary["avg_stars"],
        "five_star": summary["five_star"],
        "on_time_met": summary["on_time"]["met"],
        "on_time_of": summary["on_time"]["of"],
        "traveled": summary["traveled_jobs"],
        "cross_registry": summary["cross_registry_jobs"],
        "disputes": summary["disputes"]["total"],
        "open_disputes": summary["disputes"].get("open", 0),
        "lost_disputes": summary["disputes"].get("lost", 0),
        "last_verified_at": summary["last_verified_at"],
    }


async def compact_track_records(db: AsyncSession, dids: List[str]) -> Dict[str, Dict[str, Any]]:
    """{did: compact} for a page of DIDs. DIDs with no history are ABSENT, exactly as
    `track_record_summaries` leaves them — an absent key is 'no verified work', which the
    FE renders as no mark. Never fabricate a zero row: a zero that was written by us is
    indistinguishable from a zero the ledger actually holds."""
    return {did: compact_track_record(s)
            for did, s in (await track_record_summaries(db, dids)).items()}


async def track_record_detail(db: AsyncSession, did: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Merged engagement rows (local + traveled), newest first. Each local row carries
    the `receipt_digest` binding it to its receipt endpoint."""
    local = (await db.execute(text(_VSTARS_CTE + """
        SELECT o.id, o.title, o.poster_did, o.worker_did, o.payee_did, o.payee_org_id,
               o.bounty::text AS bounty_text, o.currency, o.fee_charged::text AS fee_text,
               o.contract_id, o.worker_home_registry,
               o.awarded_at, o.submitted_at, o.settled_at,
               v.stars, b.eta_seconds
        FROM guild_work_orders o
        LEFT JOIN vstars v ON v.order_id = o.id
        LEFT JOIN guild_bids b ON b.id = o.awarded_bid_id
        WHERE o.status = 'settled' AND o.worker_did = :did
        ORDER BY o.settled_at DESC NULLS LAST
        LIMIT :n
    """), {"did": did, "n": limit})).mappings().all()

    traveled = (await db.execute(text("""
        SELECT order_id, host_registry, poster_did, stars,
               bounty::text AS bounty_text, currency, received_at
        FROM guild_travel_credentials
        WHERE verified AND worker_did = :did
        ORDER BY received_at DESC
        LIMIT :n
    """), {"did": did, "n": limit})).mappings().all()

    rows: List[Dict[str, Any]] = []
    for r in local:
        d = dict(r)
        subset = build_receipt_subset(d, d.get("stars"))
        rows.append({
            "kind": "local",
            "order_id": d["id"],
            "title": d.get("title"),
            "poster_did": d["poster_did"],
            "bounty": d.get("bounty_text"),
            "currency": d.get("currency"),
            "stars": d.get("stars"),
            "settled_at": _iso(d.get("settled_at")),
            "contract_id": d.get("contract_id"),
            "on_time": _on_time(d),
            "counterparty_home_registry": d.get("worker_home_registry"),
            "receipt_digest": receipt_digest(subset),
            "_ts": _iso(d.get("settled_at")) or "",
        })
    for r in traveled:
        rows.append({
            "kind": "traveled",
            "order_id": r["order_id"],
            "host_registry": r["host_registry"],
            "poster_did": r["poster_did"],
            "bounty": r.get("bounty_text"),
            "currency": r.get("currency"),
            "stars": r.get("stars"),
            "received_at": _iso(r.get("received_at")),
            "verified": True,
            "_ts": _iso(r.get("received_at")) or "",
        })
    rows.sort(key=lambda x: x["_ts"], reverse=True)
    for x in rows:
        del x["_ts"]
    return rows[:limit]


async def build_local_receipt(db: AsyncSession, did: str, order_id: str) -> Optional[Dict[str, Any]]:
    """Receipt for a LOCAL settled engagement: canonical subset + digest + a
    deterministically re-issued Ed25519 credential (the host never retained the
    originally shipped bundle; identical claim bytes yield the identical signature).
    Returns None when the order is not this worker's settled engagement."""
    row = (await db.execute(text(_VSTARS_CTE + """
        SELECT o.id, o.title, o.poster_did, o.worker_did, o.payee_did, o.payee_org_id,
               o.bounty::text AS bounty_text, o.bounty, o.currency,
               o.fee_charged::text AS fee_text, o.contract_id, o.worker_home_registry,
               o.awarded_at, o.submitted_at, o.settled_at, v.stars
        FROM guild_work_orders o
        LEFT JOIN vstars v ON v.order_id = o.id
        WHERE o.id = :o AND o.worker_did = :d AND o.status = 'settled'
    """), {"o": order_id, "d": did})).mappings().first()
    if not row:
        return None
    d = dict(row)
    subset = build_receipt_subset(d, d.get("stars"))

    credential = None
    try:
        from agentvault_registry.services import guild_reputation
        credential = await guild_reputation.issue_work_credential({
            "id": d["id"], "worker_did": d["worker_did"], "poster_did": d["poster_did"],
            "title": d.get("title"), "bounty": d.get("bounty"), "currency": d.get("currency"),
            "settled_at": d.get("settled_at"),
            "payee_did": d.get("payee_did"), "payee_org_id": d.get("payee_org_id"),
        }, stars=d.get("stars"))
    except Exception as e:  # noqa: BLE001
        logger.warning("[TRACKREC] receipt credential re-issue failed for %s: %s", order_id, e)

    from agentvault_registry.services.guild_reputation import credential_pubkey
    return {
        "kind": "local",
        "subset": subset,
        "digest": receipt_digest(subset),
        "credential": credential,
        "credential_reissued": credential is not None,
        "credential_note": None if credential is not None else
            "credential signing is disabled on this registry (GUILD_ZK_CREDENTIAL_ENABLED)",
        "credential_pubkey": credential_pubkey(),
        "contract_id": d.get("contract_id"),
    }


async def build_traveled_receipt(db: AsyncSession, did: str, order_id: str) -> Optional[Dict[str, Any]]:
    """Receipt for a TRAVELED engagement: the stored, ingestion-verified Ed25519 bundle
    plus a verify-at-origin pointer (the HOST registry attests the facts; we attest that
    we verified its signature when the credential landed)."""
    row = (await db.execute(text("""
        SELECT order_id, host_registry, poster_did, stars, bounty::text AS bounty_text,
               currency, bundle, pubkey_id, verified, received_at
        FROM guild_travel_credentials
        WHERE worker_did = :d AND order_id = :o AND verified
    """), {"d": did, "o": order_id})).mappings().first()
    if not row:
        return None
    host = (row["host_registry"] or "").rstrip("/")
    return {
        "kind": "traveled",
        "host_registry": host,
        "poster_did": row["poster_did"],
        "stars": row["stars"],
        "bounty": row["bounty_text"],
        "currency": row["currency"],
        "bundle": row["bundle"],
        "bundle_pubkey_id": row["pubkey_id"],
        "verified_at_ingestion": bool(row["verified"]),
        "received_at": _iso(row["received_at"]),
        "verify_at_origin": f"{host}/api/v1/agents/{did}/track-record/receipts/{order_id}" if host else None,
    }


# ─── §AGENTDISC #191 — proof-weighted ranking (ONE source of truth) ───────────
#
# The discover sort, the response meta, and the FE why-ranked-here popover all
# derive from THESE weights — the popover recomputes contributions from the same
# numbers the Proven-work band shows, so the explanation can never drift from
# the ranking. Transparent by construction; there is no pay-to-rank input.
PROOF_WEIGHTS: Dict[str, float] = {
    "jobs_ln": 2.0,            # 2.0 * ln(1 + jobs_verified)
    "stars_centered": 0.5,     # 0.5 * (avg_stars - 3)  — only when any job was starred
    "recency_180d": 1.0,       # 1.0 * max(0, 1 - days_since_last_verified / 180)
    "cross_capped3": 0.3,      # 0.3 * min(cross_registry_jobs, 3)
    "lost_dispute": -1.5,      # per lost dispute
    "open_dispute": -0.75,     # per currently open dispute
    "reputation_percent": 0.01,  # 0.01 * min(reputation_score, 100) — SQL-side tiebreak layer
}

PROOF_FORMULA = (
    "score = 2.0*ln(1+jobs) + 0.5*(avg_stars-3) + 1.0*max(0, 1-days_since_last/180) "
    "+ 0.3*min(cross_registry,3) - 1.5*lost_disputes - 0.75*open_disputes "
    "+ 0.01*min(reputation,100)"
)


def proof_score(summary: Dict[str, Any], now: Optional[Any] = None) -> float:
    """Pure scorer over a track_record_summaries() entry (reputation is added
    SQL-side as the tiebreak layer — see the discover ORDER BY)."""
    import math
    from datetime import datetime, timezone
    w = PROOF_WEIGHTS
    score = w["jobs_ln"] * math.log(1 + max(0, int(summary.get("jobs_verified") or 0)))
    if summary.get("avg_stars") is not None:
        score += w["stars_centered"] * (float(summary["avg_stars"]) - 3.0)
    last = summary.get("last_verified_at")
    if last:
        try:
            now_dt = now or datetime.now(timezone.utc)
            last_dt = datetime.fromisoformat(str(last))
            days = max(0.0, (now_dt - last_dt).total_seconds() / 86400.0)
            score += w["recency_180d"] * max(0.0, 1.0 - days / 180.0)
        except Exception:  # noqa: BLE001
            pass
    score += w["cross_capped3"] * min(int(summary.get("cross_registry_jobs") or 0), 3)
    disputes = summary.get("disputes") or {}
    score += w["lost_dispute"] * int(disputes.get("lost") or 0)
    score += w["open_dispute"] * int(disputes.get("open") or 0)
    return round(score, 4)


async def track_record_scores(db: AsyncSession, cap: int = 50) -> Dict[str, float]:
    """{did: proof_score} for every history-bearing DID (the guild books are tiny:
    two DISTINCT scans + the same grouped aggregation the band uses). Capped to the
    top `cap` scores so the discover ORDER BY CASE stays bounded."""
    dids = [r[0] for r in (await db.execute(text("""
        SELECT DISTINCT worker_did FROM guild_work_orders
        WHERE status = 'settled' AND worker_did <> ''
        UNION
        SELECT DISTINCT worker_did FROM guild_travel_credentials WHERE verified
    """))).all()]
    if not dids:
        return {}
    summaries = await track_record_summaries(db, dids)
    scored = {d: proof_score(s) for d, s in summaries.items()}
    top = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)[:cap]
    return dict(top)


async def has_history(db: AsyncSession, did: str) -> bool:
    """Cheap indexed existence check across both books — gates extension injection."""
    if not did:
        return False
    row = (await db.execute(text("""
        SELECT EXISTS (SELECT 1 FROM guild_work_orders
                       WHERE worker_did = :d AND status = 'settled')
            OR EXISTS (SELECT 1 FROM guild_travel_credentials
                       WHERE worker_did = :d AND verified)
    """), {"d": did})).scalar()
    return bool(row)


def attestation_url(did: str) -> str:
    """Absolute when the registry knows its public URL (loopback-rejecting helper),
    honest relative otherwise."""
    try:
        from agentvault_registry.core.public_url import public_base_url_static
        base = (public_base_url_static() or "").rstrip("/")
    except Exception:  # noqa: BLE001
        base = ""
    return f"{base}/api/v1/agents/{did}/track-record"


def inject_track_record_extension(
    card: Dict[str, Any],
    did: str,
    extended_payload: Optional[Dict[str, Any]] = None,
    compact: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Derive-time injection of the track-record AgentExtension (#187).

    IDEMPOTENT: deduped by URI, so a stored card that already carries the pointer
    (an SDK agent re-registering its own export) never duplicates. Applied AFTER the
    registry-owned-enrichment strip in card-export — never persisted into card_data.
    `extended_payload` (authenticated extended card only) inlines the attested
    summary + engagement rows into params; the public shape stays pointer-only."""
    out = dict(card)
    caps = out.get("capabilities")
    caps = dict(caps) if isinstance(caps, dict) else {}
    exts = [e for e in (caps.get("extensions") or [])
            if isinstance(e, dict) and e.get("uri") != TRACK_RECORD_EXTENSION_URI]
    entry: Dict[str, Any] = {
        "uri": TRACK_RECORD_EXTENSION_URI,
        "description": "Registry-attested guild work history with verifiable per-engagement receipts",
        "required": False,
        "params": {
            "attestation_url": attestation_url(did),
            "receipt_kind": RECEIPT_KIND,
        },
    }
    if extended_payload is not None:
        entry["params"]["track_record"] = extended_payload
    # §TRAVELREC — the FEDERATION EXPORT carries the compact summary, not only the pointer.
    # A pointer is enough for a reader that can dial the origin; it is NOT enough for a peer's
    # discovery page, which renders thousands of cards and cannot fetch one attestation each.
    # So the home registry states the summary on the card it signs, and states where to check it.
    # A peer renders it as the ORIGIN's claim (the card already names its origin registry), and
    # `verify_at` is how that claim stops being merely a claim.
    if compact is not None:
        entry["params"]["compact"] = dict(compact)
        entry["params"]["verify_at"] = attestation_url(did)
    exts.append(entry)
    caps["extensions"] = exts
    caps["extendedAgentCard"] = True
    out["capabilities"] = caps
    # v0.3 sibling field for older readers; render_for_v03_peer strips extensions
    # for strict-v0.3 peers, so this is the only trace they see.
    out["supportsAuthenticatedExtendedCard"] = True
    return out


async def touch_worker_card_no_commit(db, worker_did) -> int:
    """Move the worker's card clock so a settled job REACHES the peers that mirror it.

    §TRAVELREC's forward half. The record is derived at export, so if nothing touches the card
    when the record changes, a peer keeps yesterday's summary forever: its cursor sees no newer
    envelope and its digest sees no changed row. §ENFPROP solved the identical problem for
    suspensions with exactly this call — the touch IS the clock.

    Never raises: a bookkeeping touch must not roll back a settlement that has already moved money.
    """
    if not worker_did:
        return 0
    try:
        from .enforcement_propagation import touch_native_card_no_commit
        return await touch_native_card_no_commit(db, worker_did)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("[TRAVELREC] card touch failed for %s: %s", worker_did, e)
        return 0


def compact_from_card(card_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The attested compact summary a PEER's card carries, or None.

    The mirror half of the export. A federated card is the origin registry's signed statement
    about its own agent; this reads the summary out of it so a peer's discovery page can render
    a record it did not compute. Returns None for a card that carries no extension, and None is
    "no verified work known here" — never a fabricated zero row.
    """
    if not isinstance(card_data, dict):
        return None
    caps = card_data.get("capabilities")
    exts = (caps or {}).get("extensions") if isinstance(caps, dict) else None
    for e in (exts or []):
        if isinstance(e, dict) and e.get("uri") == TRACK_RECORD_EXTENSION_URI:
            params = e.get("params") or {}
            c = params.get("compact")
            if isinstance(c, dict) and c.get("jobs"):
                out = dict(c)
                out["attested"] = True
                if params.get("verify_at"):
                    out["verify_at"] = params["verify_at"]
                return out
            return None
    return None


__all__ = [
    "RECEIPT_KIND",
    "PROOF_WEIGHTS",
    "PROOF_FORMULA",
    "proof_score",
    "track_record_scores",
    "TRACK_RECORD_EXTENSION_URI",
    "has_history",
    "attestation_url",
    "inject_track_record_extension",
    "compact_from_card",
    "touch_worker_card_no_commit",
    "receipt_digest",
    "build_receipt_subset",
    "track_record_summaries",
    "track_record_detail",
    "build_local_receipt",
    "build_traveled_receipt",
]


async def org_track_record(db: AsyncSession, org_id: str) -> Dict[str, Any]:
    """§CHATDESK H1.1 — the FIRM's track record, computed on read.

    Aggregates settled guild work whose ``payee_org_id`` is this org — i.e.
    work done AS the firm through the firm-bid rail. The column is written at
    settlement time, so attribution is snapshot-at-verification: an agent (or
    developer) leaving later does not rewrite the firm's history, and joining
    later does not import theirs. Honest zeros; no snapshot table.
    """
    head = (await db.execute(text(_VSTARS_CTE + """
        SELECT COUNT(*) AS jobs,
               COUNT(DISTINCT o.worker_did) AS workers,
               AVG(v.stars)::float AS stars_avg,
               COUNT(v.stars) AS stars_n,
               MIN(o.settled_at) AS first_settled,
               MAX(o.settled_at) AS last_settled
        FROM guild_work_orders o
        LEFT JOIN vstars v ON v.order_id = o.id
        WHERE o.status = 'settled' AND o.payee_org_id = :org
    """), {"org": org_id})).mappings().first()
    per_currency = [
        {"currency": r["currency"], "jobs": int(r["jobs"]), "earned": r["earned"]}
        for r in (await db.execute(text("""
            SELECT currency, COUNT(*) AS jobs, SUM(bounty)::text AS earned
            FROM guild_work_orders
            WHERE status = 'settled' AND payee_org_id = :org
            GROUP BY currency ORDER BY currency
        """), {"org": org_id})).mappings().all()
    ]
    # §ORGCLIENT (H3.1) — the CLIENT half: work this firm COMMISSIONED and paid for.
    # Attribution is the order's poster_did == the org's OWN treasury (posted through
    # the org work-order door, which requires exactly that), settled only.
    commissioned = {"orders": 0, "workers_hired": 0, "per_currency": [],
                    "first_settled_at": None, "last_settled_at": None}
    from agentvault_registry.services.org_treasury import (
        org_treasury_source, resolve_org_treasury_did,
    )
    if await org_treasury_source(db, org_id) == "org":
        tdid = await resolve_org_treasury_did(db, org_id)
        if tdid:
            chead = (await db.execute(text("""
                SELECT COUNT(*) AS orders, COUNT(DISTINCT worker_did) AS workers,
                       MIN(settled_at) AS first_settled, MAX(settled_at) AS last_settled
                FROM guild_work_orders WHERE status = 'settled' AND poster_did = :p
            """), {"p": tdid})).mappings().first()
            cd = dict(chead or {})
            commissioned = {
                "orders": int(cd.get("orders") or 0),
                "workers_hired": int(cd.get("workers") or 0),
                "per_currency": [
                    {"currency": r["currency"], "orders": int(r["orders"]), "paid": r["paid"]}
                    for r in (await db.execute(text("""
                        SELECT currency, COUNT(*) AS orders, SUM(bounty)::text AS paid
                        FROM guild_work_orders WHERE status = 'settled' AND poster_did = :p
                        GROUP BY currency ORDER BY currency
                    """), {"p": tdid})).mappings().all()
                ],
                "first_settled_at": _iso(cd.get("first_settled")),
                "last_settled_at": _iso(cd.get("last_settled")),
            }

    d = dict(head or {})
    return {
        "verified_jobs": int(d.get("jobs") or 0),
        "workers": int(d.get("workers") or 0),
        "stars_avg": (round(float(d["stars_avg"]), 2) if d.get("stars_avg") is not None else None),
        "stars_n": int(d.get("stars_n") or 0),
        "first_settled_at": _iso(d.get("first_settled")),
        "last_settled_at": _iso(d.get("last_settled")),
        "per_currency": per_currency,
        "commissioned": commissioned,
        "attribution": "snapshot-at-verification: payee_org_id is written when the work settles; departures do not rewrite history",
    }
