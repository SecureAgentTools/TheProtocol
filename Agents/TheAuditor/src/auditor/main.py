"""The Auditor — Supply Invariant Guardian Agent.

Monitors the supply invariant (tokens_issued − tokens_destroyed == tokens_circulating)
24/7 across all sovereign frames. Polls each EventStore every AUDIT_INTERVAL seconds.

v2.1 — INDEPENDENT ATOMIC VERIFICATION:
  The auditor no longer trusts the EventStore's HTTP /supply-audit endpoint as the
  source of truth. That endpoint reads supply_summary and materialized_balances in
  two separate steps, so under live CQRS batch updates the reads skew and it reports
  transient phantom deltas (e.g. +125) while the true invariant holds. The auditor
  now ALSO reads each frame's EventStore Postgres directly and computes the invariant
  in ONE SQL statement (single MVCC snapshot) — the ATOMIC TRUTH. Breach/uptime/streak
  key off the atomic delta; the HTTP value is retained as the "live-read" signal.
"""
import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request, Header
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

try:
    import asyncpg  # direct-DB atomic verification (optional — graceful fallback)
except Exception:  # pragma: no cover
    asyncpg = None

from .config import (
    EVENT_STORE_KEY,
    AGENT_DID,
    AGENT_NAME,
    AUDIT_INTERVAL,
    FRONTEND_DIR,
    FRAMES,
    VENUES,
    FRAME_MODE,
    MODES,
    DEFAULT_MODE,
    ATTEST_MODES,
    ATOMIC_TOLERANCE,
    PER_USER_TOLERANCE,
    NATIVE_SUPPLY_TOL,
    TRUE_SUPPLY_SINCE,
    AUDITOR_VERSION,
    AUDITOR_ADMIN_TOKEN,
    MAINTENANCE_SEED_ACTIVE,
    MAINTENANCE_SEED_TITLE,
    MAINTENANCE_SEED_MESSAGE,
    MAINTENANCE_SEED_PATCH_REF,
    FX_RESERVE_DID,
    FX_SOLVENCY_COMFORT_MULT,
    FX_SOLVENCY_WARN_FACTOR,
    FX_ROUTER_RESIDUE_THRESHOLD,
    AUDITOR_TLS_CERT,
    AUDITOR_TLS_KEY,
    AUDITOR_TLS_CA,
    PUBLIC_BREACH_READINGS,
    PUBLIC_ONLY_REASON,
    SLOT_SHAPES,
)
from . import database as db
from . import attest
from . import tls_client
from . import track_record  # §MEMBERSHIP phase D1: the registry track record (off without its carrier file)

logger = logging.getLogger("auditor")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# ── State ────────────────────────────────────────────────────────────────

latest_results: dict[str, Optional[dict]] = {}
# §GLOBALSTD Phase 1/4.1 — TPSA-1 signing context + liveness bookkeeping.
attest_key = None                       # set in lifespan; None → audits run UNSIGNED (logged)
_attest_lock: "asyncio.Lock" = asyncio.Lock()   # serializes head-read → sign → insert per chain
attest_counts: dict[str, int] = {}      # per-frame emit counter since process start (/metrics)
last_cycle_done: dict[str, float] = {}  # frame → epoch of last COMPLETED cycle (loop-stall deadman)
consecutive_ok: dict[str, int] = {}
public_streak: dict[str, int] = {}   # §MTLSHOPS (a): consecutive BREACH readings of a public-only frame's public supply audit
total_audits: int = 0
start_time: float = 0.0
ws_clients: set[WebSocket] = set()
audit_task: Optional[asyncio.Task] = None
track_task: Optional[asyncio.Task] = None   # §MEMBERSHIP D1: the track record's observe loop (never raises)
maintenance_state: dict = {}

# asyncpg pools, lazily created per frame (None until first success).
_pools: dict[str, "asyncpg.Pool"] = {}
# Separate read-only pools to each frame's REGISTRY Postgres (AGORA share cap table).
# Distinct from `_pools` (EventStore) — different DB, different DSN (FRAME_<X>_REG_DSN).
_reg_pools: dict[str, "asyncpg.Pool"] = {}
# Read-only pools to each frame's TEG Postgres (V6 currency attribution via
# cross_teg_transfers — the only currency-aware money table). FRAME_<X>_TEG_DSN.
_teg_pools: dict[str, "asyncpg.Pool"] = {}
# V6 currency attribution cache (the cross-TEG rail moves far slower than the supply Δ
# and the GROUP BY scans the whole table → refresh on a slow cadence). {fid: {at, data}}.
_crossteg_cache: dict = {}
_CROSSTEG_REFRESH_SEC = float(os.getenv("CROSSTEG_REFRESH_SEC", "300"))

# Single-statement atomic invariant query (consistent MVCC snapshot).
# §B (2026-05-30): the invariant gains a transit_net term — tokens_issued/destroyed are REAL
# mint/burn, and transit_net carries transfer / cross-frame legs:
#   tokens_issued − tokens_destroyed + transit_net − Σ(liquid+staked) = 0.
# COALESCE(transit_net,0) keeps it correct pre-§B (column defaults 0). If the column does not
# yet exist on a frame (pre-rollout), the query errors → _atomic_invariant returns None →
# graceful fallback to the HTTP live-read (so deploy order is not load-bearing).
ATOMIC_SQL = """
SELECT
    (ss.tokens_issued)::float8                                                   AS tokens_issued,
    (ss.tokens_destroyed)::float8                                                AS tokens_destroyed,
    (ss.tokens_fees_collected)::float8                                           AS tokens_fees_collected,
    (ss.transit_net)::float8                                                     AS transit_net,
    (mb.circ)::float8                                                            AS total_circulating,
    mb.n                                                                         AS agent_count,
    (ss.tokens_issued - ss.tokens_destroyed + ss.transit_net - mb.circ)::float8  AS atomic_delta,
    es.max_seq                                                                   AS as_of_event_seq
FROM (SELECT tokens_issued, tokens_destroyed, tokens_fees_collected,
             COALESCE(transit_net, 0) AS transit_net
        FROM supply_summary ORDER BY id LIMIT 1) ss,
     (SELECT COALESCE(SUM(liquid_balance + staked_balance), 0) AS circ, COUNT(*) AS n
        FROM materialized_balances) mb,
     -- §GLOBALSTD Phase 1 (TPSA-1): pins the observation into the event stream.
     -- ONE statement = ONE snapshot in Postgres, so this MAX(seq) is transactionally
     -- consistent with the terms above (index-only via ix_events_seq, ~1-3ms).
     (SELECT COALESCE(MAX(seq), 0)::bigint AS max_seq FROM events) es
"""

# True mint/burn from the typed supply events on the immutable log. The
# supply_summary issued/destroyed counters fold in transfer/cross-frame legs
# post-CQRS-cutover and are NOT real mint/burn; these typed events are. Bounded
# at the balance-integrity baseline (config.TRUE_SUPPLY_SINCE) to exclude the
# pre-cutover guard-era BalanceCorrected inflation. Read-only.
# W4 phase 1 (2026-10-25): a mint under its new name (UnitsIssued, once the registry's emitter switches) counts as
# TokensIssued does; the registry's map is agentvault_registry/core/ledger_names.py.
TRUE_SUPPLY_SQL = """
SELECT
  COALESCE(SUM(CASE
     WHEN event_type IN ('TokensIssued','UnitsIssued','DisputeCompensationMinted')
       THEN COALESCE((data->>'amount')::numeric, 0)
     WHEN event_type = 'BalanceCorrected'
       AND COALESCE((data->>'adjustment')::numeric,(data->>'amount')::numeric,0) > 0
       THEN COALESCE((data->>'adjustment')::numeric,(data->>'amount')::numeric,0)
     ELSE 0 END), 0)::float8 AS true_minted,
  COALESCE(SUM(CASE
     WHEN event_type = 'DisputeSlash'
       THEN COALESCE((data->>'amount')::numeric, 0)
     WHEN event_type = 'BalanceCorrected'
       AND COALESCE((data->>'adjustment')::numeric,(data->>'amount')::numeric,0) < 0
       THEN -COALESCE((data->>'adjustment')::numeric,(data->>'amount')::numeric,0)
     ELSE 0 END), 0)::float8 AS true_burned
FROM events
WHERE timestamp >= $1::timestamptz
  AND event_type IN ('TokensIssued','UnitsIssued','DisputeCompensationMinted','DisputeSlash','BalanceCorrected')
"""

# ── I3: per-user conservation (V3, 2026-06-10) ──────────────────────────────
# The supply invariant (I1) sums all balances, so it is structurally BLIND to a
# SINGLE user's funds going negative (one agent at −100 + treasury at +100 nets
# Δ=0). I3 reads the SAME materialized_balances snapshot and asserts the per-agent
# floor: ∀ agent, liquid_balance ≥ 0 AND staked_balance ≥ 0. A negative agent
# balance = funds conjured into / lost from a user — a per-user conservation
# breach the headline Δ cannot see. Independent witness: the auditor's own read of
# the immutable projection, never the registry's API.
PER_USER_SQL = """
SELECT
  COUNT(*) FILTER (WHERE liquid_balance < -$1::numeric)              AS neg_liquid_agents,
  COUNT(*) FILTER (WHERE staked_balance < -$1::numeric)             AS neg_staked_agents,
  COALESCE(MIN(liquid_balance) FILTER (WHERE liquid_balance < -$1::numeric), 0)::float8  AS worst_liquid,
  COALESCE(MIN(staked_balance) FILTER (WHERE staked_balance < -$1::numeric), 0)::float8  AS worst_staked,
  COALESCE(-SUM(liquid_balance) FILTER (WHERE liquid_balance < -$1::numeric), 0)::float8 AS neg_liquid_sum,
  COALESCE(-SUM(staked_balance) FILTER (WHERE staked_balance < -$1::numeric), 0)::float8 AS neg_staked_sum
FROM materialized_balances
"""

# §2026-06-25 (per-user hardening B): the DIDs behind a per-user negative, so I3 can
# cross-check each against the frame's LIVE TEG (agent_teg_profiles). A negative on an
# agent with NO live TEG balance = an ES-projection transit/escrow residue: cross-TEG
# escrow legs land in THIS frame's ES while the agent's real balance lives off-frame (or
# the agent is orphaned). It is NOT a per-user loss — the TEG (source of truth, and as of
# this pass CHECK-guarded ≥0) holds no negative. Such agents are EXCLUDED from the breach
# and reported as `orphan_transit_*` (informational). A negative on a REAL holder (TEG row
# present) STILL breaches — a genuine projection-vs-ledger discrepancy worth paging.
NEG_DIDS_SQL = """
SELECT agent_did,
       (liquid_balance)::float8 AS liq,
       (staked_balance)::float8 AS stk
FROM materialized_balances
WHERE liquid_balance < -$1::numeric OR staked_balance < -$1::numeric
ORDER BY liquid_balance ASC
LIMIT 1000
"""

# Which candidate DIDs actually hold a LIVE balance on this frame's TEG (source of truth).
TEG_PRESENT_SQL = "SELECT agent_id FROM agent_teg_profiles WHERE agent_id = ANY($1::text[])"

# §LEDGERGATE E (2026-10-11): which of them still have balance changes the TEG has NOT handed to the store (rows of its
# balance outbox's journal, not yet emitted). A negative projection with such rows is BEHIND: it resolves when they
# land. One with none, or whose oldest waiting row is older than PER_USER_BEHIND_MAX_S (a ledger that stopped
# draining; the TEG's ledger gate refuses new movements meanwhile), is a BREACH as before.
TEG_PENDING_SQL = """
SELECT agent_id, count(*)::int AS rows, EXTRACT(EPOCH FROM now() - min(changed_at))::float8 AS oldest_s
FROM balance_ledger_journal
WHERE emitted_at IS NULL AND agent_id = ANY($1::text[])
GROUP BY agent_id
"""
PER_USER_BEHIND_MAX_S = float(os.getenv("PER_USER_BEHIND_MAX_S", "900"))

# §LEDGERGATE F (2026-10-11): the TEG itself never holds a negative (its sufficiency check under a row lock, and migration
# 0007's CHECK (token_balance >= 0) and CHECK (locked_balance >= 0)). A named census of that, every cycle, read on the TEG
# and independent of the projection: one negative row on the TEG means the guarantee broke (a schema without 0007, a raw
# write), a BREACH whatever the store says. A census that cannot be read is "not checked", never OK.
TEG_NEGATIVE_SQL = ("SELECT count(*)::int AS n, coalesce(min(least(token_balance, locked_balance)), 0)::float8 AS worst "
                    "FROM agent_teg_profiles WHERE token_balance < 0 OR locked_balance < 0")

# ── I4: TEG↔ES STAKED CROSS-CHECK (2026-08-01, §AUDITFIX) ───────────────────────────────
# WHY THIS EXISTS. On 2026-07-28 a reconciliation compared the EventStore's liquid+staked
# against TEG's token_balance ALONE. Stake lives in a second TEG column, locked_balance, that
# the comparison never read, so every staked account looked like an excess and was written
# down: 1,881,514 AVT of stake deleted from the public projection. It ran undetected for four
# days because Δ=0 compares the EventStore against ITSELF — supply_summary had been set from
# the very table that was wrong. No check anywhere compared the two STORES.
#
# This is that check. It is the only assertion in the auditor that spans TEG and the
# EventStore, and it is the reason a repeat cannot be silent.
ES_STAKED_SQL = """
    SELECT agent_did AS did, staked_balance::float8 AS amt
      FROM materialized_balances
     WHERE staked_balance <> 0
"""
TEG_LOCKED_SQL = """
    SELECT agent_id AS did, locked_balance::float8 AS amt
      FROM agent_teg_profiles
     WHERE locked_balance <> 0
"""
# Staking rewards compound continuously in TEG while the projection is event-driven, so a
# small live lag is normal and must not cry wolf (~1.18 observed within minutes of a clean
# reconcile). These tolerances are wide enough to ignore that and still catch the 2026-07-28
# failure — which removed 99.85% of all stake — instantly.
STAKED_GUARD_TOL_ABS = float(os.getenv("STAKED_GUARD_TOL_ABS", "5"))
STAKED_GUARD_TOL_PCT = float(os.getenv("STAKED_GUARD_TOL_PCT", "0.001"))
STAKED_GUARD_BREACH_FRAC = float(os.getenv("STAKED_GUARD_BREACH_FRAC", "0.10"))
# §STAKEDCONFIRM: settle delay before the confirming re-read (only taken when the first
# pass sees a per-account mismatch). 0 restores the old single-read behaviour.
STAKED_GUARD_CONFIRM_DELAY_SEC = float(os.getenv("STAKED_GUARD_CONFIRM_DELAY_SEC", "4"))

# Secondary (informational) — the V0045 escrow-reconciler fingerprint events on the
# immutable log. NegativeEscrowLockClamped recurring AFTER V0045 means a lock
# double-release is reappearing (the F1 class); OrphanedEscrowLockReleased is the
# routine phantom-escrow sweep. Graceful: 0 when the event type is absent.
LOCK_EVENTS_SQL = """
SELECT
  COUNT(*) FILTER (WHERE event_type = 'NegativeEscrowLockClamped')            AS neg_clamps,
  COUNT(*) FILTER (WHERE event_type = 'OrphanedEscrowLockReleased')           AS orphan_releases
FROM events
WHERE timestamp >= $1::timestamptz
  AND event_type IN ('NegativeEscrowLockClamped','OrphanedEscrowLockReleased')
"""

# ── Supply composition (V4, 2026-06-10): "issued ≠ circulating — where is the rest?" ──
# The answer is the invariant itself: issued − destroyed + transit_net = circulating, so
# (issued − circulating) = (destroyed − transit_net). transit_net is the net of every
# non-mint/burn balance change (transfers, fees, cross-frame legs, and — dominant here —
# cross-TEG escrow lock/release/refund residue). The two views below LOCATE the supply
# (top holders + named system accounts) and EXPLAIN the gap (transit by kind). All read
# the same materialized_balances / supply_summary the invariant uses. CHEAP per cycle.
TOP_HOLDERS_SQL = """
SELECT agent_did, (liquid_balance)::float8 AS liquid, (staked_balance)::float8 AS staked
FROM materialized_balances
ORDER BY (liquid_balance + staked_balance) DESC
LIMIT $1
"""

# Aggregate "where it sits" buckets in one pass (system suspense vs everyone else).
HOLDER_BUCKETS_SQL = """
SELECT
  COALESCE(SUM(liquid_balance + staked_balance) FILTER (
    WHERE agent_did LIKE '%teg_system_treasury%'), 0)::float8 AS treasury,
  COALESCE(SUM(liquid_balance + staked_balance) FILTER (
    WHERE agent_did LIKE '%fee_collector%'), 0)::float8 AS fee_collector,
  COALESCE(SUM(liquid_balance + staked_balance) FILTER (
    WHERE agent_did LIKE '%fx_reserve%'), 0)::float8 AS fx_reserve,
  COALESCE(SUM(liquid_balance + staked_balance) FILTER (
    WHERE agent_did LIKE '%fx_router%' OR agent_did = $1), 0)::float8 AS fx_router,
  -- §2026-06-18: escrow holdings (AGORA exchange escrow + any cross-TEG escrow suspense)
  -- get their own bucket so they stop hiding inside the "agents (liquid)" residual.
  COALESCE(SUM(liquid_balance + staked_balance) FILTER (
    WHERE agent_did LIKE '%escrow%'), 0)::float8 AS escrow,
  COALESCE(SUM(staked_balance), 0)::float8 AS total_staked,
  COALESCE(SUM(liquid_balance + staked_balance) FILTER (
    WHERE agent_did NOT LIKE '%teg_system%' AND agent_did NOT LIKE '%fee_collector%'
      AND agent_did NOT LIKE '%fx_re%' AND agent_did NOT LIKE '%fx_router%'
      AND agent_did NOT LIKE '%escrow%' AND agent_did <> $1), 0)::float8 AS agents,
  COUNT(*)::int AS holder_count
FROM materialized_balances
"""

# transit_net by transaction KIND (escrow refunds dominate). HEAVY (per-event jsonb
# unroll over all LedgerBalanceChanged) → computed on a SLOW cadence and cached.
# §2026-06-10 reconcile-fix: sum ONLY events that carry a `kind` (the ledger trigger
# routes kind-less mint/genesis balance-changes to tokens_issued, NOT transit_net —
# including them produced a bogus "unknown +100M" line that didn't reconcile). With the
# `data ? 'kind'` filter the remaining kinds are exactly the escrow/stake transit legs;
# the caller adds a single `transfer_settlement` remainder so the breakdown sums to
# transit_net with nothing labeled "unknown".
TRANSIT_KIND_SQL = """
SELECT kind, count(*) AS events, round(sum(ev_net), 2)::float8 AS net_to_balances
FROM (
  SELECT CASE WHEN e.data->>'kind' = 'unknown' THEN 'transfer_settlement'
              ELSE e.data->>'kind' END AS kind,
         (SELECT COALESCE(SUM((ent->>'delta_liquid')::numeric), 0)
               + COALESCE(SUM((ent->>'delta_staked')::numeric), 0)
          FROM jsonb_array_elements(e.data->'entries') ent) AS ev_net
  FROM events e
  WHERE e.event_type = 'LedgerBalanceChanged' AND e.data ? 'kind'
    -- Mirror the ledger trigger (materialized_balances.sql): mint/dispute_comp route
    -- to tokens_issued, slash/burn to tokens_destroyed; ONLY the rest accrue to
    -- transit_net. Excluding them here makes the breakdown sum to transit_net.
    AND e.data->>'kind' NOT IN ('mint', 'dispute_comp', 'slash', 'burn')
) t GROUP BY kind ORDER BY net_to_balances
"""

# V6 — cross-TEG rail volume, attributed to the frame's NATIVE currency. cross_teg_transfers
# is a SAME-currency rail: cross-currency transfers settle on the FX rail (FxSwap/FxRoute),
# NOT here. So every COMPLETED row in a frame's TEG DB is that frame's own currency. The
# stored per-row `currency` column is NOT authoritative (historically hardcoded 'AVT' on the
# 2PC path, defaulted 'TEG' when absent), so we DO NOT group by it — we sum the rail and
# label it native. Read-only; mainframe-TEG-scoped (cluster cloud-op TEGs are separate DBs).
CROSSTEG_CCY_SQL = """
SELECT count(*)                       AS transfers,
       round(sum(amount), 2)::float8  AS completed_volume
FROM cross_teg_transfers
WHERE status = 'COMPLETED'
"""


# ── AGORA share registry (V5, 2026-06-17): "who holds the stocks?" ──────────
# The org-stock cap table lives in the REGISTRY DB (org_share_positions +
# exchange_listings), NOT the EventStore — shares are the registry ledger. These
# read-only queries are the stock analog of the currency composition: per listing,
# the holder count, the treasury vs public vs unsold-IPO-float split, and the top
# holders. The auditor reads the registry DB DIRECTLY (independent witness), the
# same way it reads materialized_balances for currency holders. CHEAP (a handful
# of listings, a few hundred positions; the top-holders query is windowed).
SHARE_LISTINGS_SQL = """
SELECT l.id, l.symbol, l.display_name, l.currency, l.status,
       l.total_shares::float8       AS total_shares,
       l.ipo_float::float8          AS ipo_float,
       l.ipo_sold::float8           AS ipo_sold,
       l.treasury_agent_did         AS treasury_did,
       COALESCE(agg.holders, 0)                   AS holders,
       COALESCE(agg.held, 0)::float8              AS held,
       COALESCE(agg.locked, 0)::float8            AS locked,
       COALESCE(agg.treasury_qty, 0)::float8      AS treasury_qty,
       COALESCE(agg.neg_holders, 0)               AS neg_holders,
       COALESCE(agg.over_locked, 0)               AS over_locked,
       COALESCE(agg.neg_locked, 0)                AS neg_locked
FROM exchange_listings l
LEFT JOIN (
    SELECT p.listing_id,
           COUNT(*) FILTER (WHERE p.qty > 0)                                        AS holders,
           SUM(p.qty)                                                               AS held,
           SUM(p.locked_qty)                                                        AS locked,
           SUM(p.qty) FILTER (WHERE p.agent_did = el.treasury_agent_did)            AS treasury_qty,
           -- I-Shares conservation witnesses (should all be 0):
           COUNT(*) FILTER (WHERE p.qty < 0)                  AS neg_holders,   -- holder owes shares
           COUNT(*) FILTER (WHERE p.locked_qty > p.qty)       AS over_locked,   -- locked more than owned
           COUNT(*) FILTER (WHERE p.locked_qty < 0)           AS neg_locked     -- negative lock
    FROM org_share_positions p
    JOIN exchange_listings el ON el.id = p.listing_id
    GROUP BY p.listing_id
) agg ON agg.listing_id = l.id
WHERE l.status <> 'delisted'
ORDER BY l.symbol
"""

# Top-N holders per listing in ONE windowed pass (treasury tagged from the listing).
SHARE_TOP_HOLDERS_SQL = """
SELECT listing_id, agent_did, qty::float8 AS qty, locked_qty::float8 AS locked, is_treasury
FROM (
    SELECT p.listing_id, p.agent_did, p.qty, p.locked_qty,
           (p.agent_did = l.treasury_agent_did) AS is_treasury,
           ROW_NUMBER() OVER (PARTITION BY p.listing_id ORDER BY p.qty DESC) AS rn
    FROM org_share_positions p
    JOIN exchange_listings l ON l.id = p.listing_id
    WHERE p.qty > 0 AND l.status <> 'delisted'
) t
WHERE rn <= $1
ORDER BY listing_id, qty DESC
"""

# Current price = last executed trade per listing. Driven off the (few) listings with a
# LATERAL LIMIT-1 so each lookup rides ix_exchange_trades_listing_seq (listing_id, seq DESC)
# — a per-listing index probe (~ms), NOT a 150k-row DISTINCT ON seqscan (~1s). price is
# NULL for a listing with no trades yet (LEFT JOIN). Quoted in the listing's currency.
SHARE_LAST_PRICE_SQL = """
SELECT l.id AS listing_id, t.price::float8 AS price, t.created_at
FROM exchange_listings l
LEFT JOIN LATERAL (
    SELECT price, created_at FROM exchange_trades
    WHERE listing_id = l.id ORDER BY seq DESC LIMIT 1
) t ON TRUE
WHERE l.status <> 'delisted'
"""

# 24h price sparkline: last trade price per hourly bucket (≤24 pts/listing). HEAVIER
# (24h created_at scan) → refreshed on a slow cadence and cached, like transit-by-kind.
# §AGORAFLAT (2026-08-22): 24h ACTIVITY per listing. The panel showed price/trend/
# holders only, so a price PINNED by a buy-only regime (treasury MM sole seller) was
# indistinguishable from a dead market — the Commander read 1,507 trades/24h as "no
# trading". Volume makes pinned-but-busy legible.
SHARE_ACTIVITY_SQL = """
SELECT listing_id, count(*) AS trades_24h,
       COALESCE(sum(qty), 0)::float8      AS vol_24h_qty,
       COALESCE(sum(notional), 0)::float8 AS vol_24h_notional
FROM exchange_trades
WHERE created_at > now() - interval '24 hours'
GROUP BY listing_id
"""

SHARE_SPARK_SQL = """
SELECT listing_id, b, price FROM (
  SELECT t.listing_id,
         date_trunc('hour', t.created_at) AS b,
         t.price::float8 AS price,
         ROW_NUMBER() OVER (PARTITION BY t.listing_id, date_trunc('hour', t.created_at)
                            ORDER BY t.seq DESC) AS rn
  FROM exchange_trades t
  WHERE t.created_at >= now() - interval '24 hours'
) s WHERE rn = 1
ORDER BY listing_id, b
"""

# The AGORA share registry moves far slower than the supply Δ, and its reads hit the
# PRODUCTION registry DB (not the EventStore). So the WHOLE payload is cached per frame and
# refreshed on a cadence DELIBERATELY slower than AUDIT_INTERVAL (the 60s currency-Δ cycle),
# keeping exchange-read churn off the registry DB low. Between refreshes _do_audit reuses the
# cached object (still attached to every audit result + broadcast; just no DB hit).
# {frame_id: {"at": iso, "data": <shares dict>}}.
_shares_cache: dict = {}
_SHARES_REFRESH_SEC = float(os.getenv("SHARES_REFRESH_SEC", "300"))  # 5 min; keep ≥ AUDIT_INTERVAL

# §OPDIST (2026-09-16): the last OBSERVED failure of a share-registry read, per frame/venue id, so an answer can say what
# was seen instead of one sentence for every cause. On beacon a TLS refusal (the operator's Postgres serves no TLS to a
# verify-full auditor) and a permission denial (the read-only role could not read exchange_trades) both answered
# "registry DB not reachable". {id: {"stage": "pool" | "read", "error": <redacted text>, "at": iso}}; a success clears it.
_share_errors: dict = {}


def _record_share_error(fid: str, stage: str, exc: BaseException, dsn: Optional[str]) -> None:
    """Record what a pool or a read raised, with the DSN's password removed: an error text can carry the whole DSN."""
    import re
    from urllib.parse import urlsplit, unquote
    text = str(exc) or type(exc).__name__
    try:
        pw = urlsplit(dsn or "").password
    except ValueError:
        pw = None
    for secret in {pw, unquote(pw) if pw else None} - {None, ""}:
        text = text.replace(secret, "<redacted>")
    text = re.sub(r"(://[^:/@\s]+):[^@\s]*@", r"\1:<redacted>@", text)
    _share_errors[fid] = {"stage": stage, "error": text[:240], "at": datetime.now(timezone.utc).isoformat()}


# ── AGORA escrow invariant (I-X3, 2026-06-28): authoritative independent witness ──
# The registry's per-worker `agora_invariant_delta` gauge is a snapshot of ONE worker's
# compute_invariants() and skews transiently (per-worker race + orders mid-'funding'),
# so the AgoraEscrowInvariantBreach alert fires with nothing to refute it. The auditor
# now computes I-X3 itself from TWO independent reads — the escrow agent's LIVE liquid
# balance straight from the frame's TEG DB, and the registry's 5-term expected-escrow
# straight from the frame's REGISTRY DB — then CONFIRMS any non-zero delta on a re-read
# and only calls BREACH when it persists AND exceeds what in-flight 'funding' explains.
# Both reads are READ-ONLY (observer-only); never writes any system DB.
#
# actual_escrow  = liquid `token_balance` of the AGORA escrow agent on the TEG. The
#   registry mover's GET /admin/exchange/escrow returns AgentCRUD.get_balance(escrow) =
#   agent_teg_profiles.token_balance of `teg:system:exchange_escrow` (env-overridable).
ESCROW_TEG_DID = os.getenv("AGORA_ESCROW_TEG_DID", "teg:system:exchange_escrow")
# LISTING_FEE — mirror the registry constant (services/exchange_service.py:102) so the
# parked-fee escrow term matches byte-for-byte (env EXCHANGE_LISTING_FEE, default 1000).
EXCHANGE_LISTING_FEE = float(os.getenv("EXCHANGE_LISTING_FEE", "1000") or 1000)
# Tolerance + confirm settle. TOL ~ 1.0 (sub-unit dust never breaches); the confirm
# sleep lets a same-cycle in-flight 'funding' deposit/flip converge before we judge.
ESCROW_INVARIANT_TOL = float(os.getenv("ESCROW_INVARIANT_TOL", "1.0") or 1.0)
ESCROW_CONFIRM_SLEEP_SEC = float(os.getenv("ESCROW_CONFIRM_SLEEP_SEC", "3") or 3)

# actual side — the escrow agent's LIVE liquid balance on the frame's TEG (source of
# truth, exactly what the mover's /escrow returns). 0 when the row is absent (venue-dark).
ESCROW_ACTUAL_SQL = "SELECT COALESCE(token_balance, 0)::float8 AS bal FROM agent_teg_profiles WHERE agent_id = $1"

# expected side — the registry's 5-term venue-global escrow expectation, replicated
# EXACTLY from compute_invariants() (exchange_service.py ~3445-3503):
#   expected = buy_holds + unsettled_notional + ipo_in_flight + unpaid_div_legs
#              + LISTING_FEE * parked_fees
# buy_holds EXCLUDES status IN ('rejected','funding') — a 'funding' buy's deposit isn't
# in escrow yet (it's on the buyer/Passport gateway), so it must NOT inflate expected.
ESCROW_EXPECTED_SQL = """
SELECT
  COALESCE((SELECT SUM(escrow_amount - matched_notional - escrow_refunded)
            FROM exchange_orders
            WHERE side = 'buy' AND escrow_amount > 0
              AND status NOT IN ('rejected', 'funding')), 0)::float8          AS buy_holds,
  COALESCE((SELECT SUM(notional) FROM exchange_trades
            WHERE settle_status = 'pending_settlement'), 0)::float8           AS unsettled_notional,
  COALESCE((SELECT SUM(amount) FROM exchange_ipo_purchases
            WHERE status IN ('allocated', 'refunding')), 0)::float8           AS ipo_in_flight,
  COALESCE((SELECT SUM(dl.amount)
            FROM exchange_dividend_legs dl
            JOIN exchange_dividends d ON d.id = dl.dividend_id
            WHERE dl.status = 'pending' AND d.pot_funded IS TRUE), 0)::float8  AS unpaid_div_legs,
  COALESCE((SELECT COUNT(*) FROM exchange_listings
            WHERE listing_fee_parked IS TRUE), 0)                             AS parked_fees
"""

# the ONE legitimate transient I-X3 window — buy orders whose deposit may have landed in
# escrow (↑ actual) while the order is still 'funding' (excluded from buy_holds → not yet
# in expected). funding_notional = Σ(escrow_amount) of those orders bounds that skew.
# §2026-07-02: + YOUNG (<15 min) IPO purchases in 'funding' — same skew via ipo_in_flight
# (counts only allocated/refunding). Age-capped on purpose: the registry's ipo_funding
# sweeper heals stuck rows at ~30s, so an OLD 'funding' IPO row means the sweeper is
# broken and MUST still read as a BREACH, not tolerance. (frame-b +6.25 trace.)
ESCROW_FUNDING_SQL = """
SELECT
  ((SELECT COUNT(*) FROM exchange_orders WHERE status = 'funding')
   + (SELECT COUNT(*) FROM exchange_ipo_purchases
      WHERE status = 'funding'
        AND created_at > now() - interval '15 minutes'))                 AS n,
  (COALESCE((SELECT SUM(escrow_amount) FROM exchange_orders
             WHERE status = 'funding'), 0)
   + COALESCE((SELECT SUM(amount) FROM exchange_ipo_purchases
               WHERE status = 'funding'
                 AND created_at > now() - interval '15 minutes'), 0))::float8 AS notional
"""


# ── Maintenance state ─────────────────────────────────────────────────────

def _maintenance_payload() -> dict:
    """Return the current maintenance descriptor (always well-formed)."""
    return {
        "active": bool(maintenance_state.get("active", False)),
        "title": maintenance_state.get("title", ""),
        "message": maintenance_state.get("message", ""),
        "patch_ref": maintenance_state.get("patch_ref", ""),
        "since": maintenance_state.get("since"),
        "updated_at": maintenance_state.get("updated_at"),
    }


async def _load_maintenance() -> None:
    """Load maintenance state from DB; seed from env on a fresh DB."""
    global maintenance_state
    stored = await db.get_meta("maintenance")
    if stored is None:
        now = datetime.now(timezone.utc).isoformat()
        stored = {
            "active": MAINTENANCE_SEED_ACTIVE,
            "title": MAINTENANCE_SEED_TITLE,
            "message": MAINTENANCE_SEED_MESSAGE,
            "patch_ref": MAINTENANCE_SEED_PATCH_REF,
            "since": now if MAINTENANCE_SEED_ACTIVE else None,
            "updated_at": now,
        }
        await db.set_meta("maintenance", stored)
    maintenance_state = stored


# ── WebSocket broadcast ─────────────────────────────────────────────────

async def broadcast(msg: dict) -> None:
    """Send JSON message to all connected WebSocket clients."""
    if not ws_clients:
        return
    data = json.dumps(msg)
    dead = set()
    for ws in ws_clients:
        try:
            await ws.send_text(data)
        except Exception:
            dead.add(ws)
    ws_clients.difference_update(dead)


# ── Atomic invariant (direct DB) ──────────────────────────────────────────

async def _get_pool(frame: dict):
    """Lazily create (and cache) an asyncpg pool for a frame. None if unavailable."""
    if asyncpg is None:
        return None
    fid = frame["id"]
    dsn = frame.get("dsn")
    if not dsn:
        return None
    pool = _pools.get(fid)
    if pool is not None:
        return pool
    try:
        # statement_cache_size=0 → immune to InvalidCachedStatementError after the
        # EventStore applies a NUMERIC(36,18) ALTER during a cutover/recreate.
        pool = await asyncpg.create_pool(
            dsn=dsn, min_size=1, max_size=2, command_timeout=15.0,
            statement_cache_size=0, timeout=10.0,
        )
        _pools[fid] = pool
        logger.info(f"[{fid}] Atomic DB pool established")
        return pool
    except Exception as e:
        logger.warning(f"[{fid}] Atomic DB pool unavailable (will retry): {e}")
        return None


async def _get_reg_pool(frame: dict):
    """Lazily create (and cache) a read-only asyncpg pool to a frame's REGISTRY
    Postgres (AGORA share cap table). None if no FRAME_<X>_REG_DSN is configured —
    the Share Registry panel is then simply absent for that frame. Mirrors
    `_get_pool` (statement_cache_size=0 → resilient to a registry schema ALTER)."""
    if asyncpg is None:
        return None
    fid = frame["id"]
    dsn = frame.get("reg_dsn")
    if not dsn:
        return None
    pool = _reg_pools.get(fid)
    if pool is not None:
        return pool
    try:
        pool = await asyncpg.create_pool(
            dsn=dsn, min_size=1, max_size=2, command_timeout=15.0,
            statement_cache_size=0, timeout=10.0,
        )
        _reg_pools[fid] = pool
        logger.info(f"[{fid}] Registry DB pool established (share registry)")
        return pool
    except Exception as e:
        _record_share_error(fid, "pool", e, dsn)
        logger.warning(f"[{fid}] Registry DB pool unavailable (will retry): {_share_errors[fid]['error']}")
        return None


async def _get_teg_pool(frame: dict):
    """Lazily create (and cache) a READ-ONLY asyncpg pool to a frame's TEG Postgres
    (cross_teg_transfers — the only currency-aware money table). None if no
    FRAME_<X>_TEG_DSN is configured → the V6 currency attribution is simply omitted.
    Mirrors `_get_reg_pool` (statement_cache_size=0 → resilient to a TEG schema ALTER)."""
    if asyncpg is None:
        return None
    fid = frame["id"]
    dsn = frame.get("teg_dsn")
    if not dsn:
        return None
    pool = _teg_pools.get(fid)
    if pool is not None:
        return pool
    try:
        pool = await asyncpg.create_pool(
            dsn=dsn, min_size=1, max_size=2, command_timeout=15.0,
            statement_cache_size=0, timeout=10.0,
        )
        _teg_pools[fid] = pool
        logger.info(f"[{fid}] TEG DB pool established (currency attribution)")
        return pool
    except Exception as e:
        logger.warning(f"[{fid}] TEG DB pool unavailable (will retry): {e}")
        return None


async def _atomic_invariant(frame: dict) -> Optional[dict]:
    """Compute the supply invariant from a single consistent DB snapshot."""
    pool = await _get_pool(frame)
    if pool is None:
        return None
    try:
        async with pool.acquire() as con:
            row = await con.fetchrow(ATOMIC_SQL)
        if row is None:
            return None
        issued = float(row["tokens_issued"])
        destroyed = float(row["tokens_destroyed"])
        circ = float(row["total_circulating"])
        transit = float(row["transit_net"])  # §B
        atomic_delta = float(row["atomic_delta"])
        status = "OK" if abs(atomic_delta) <= ATOMIC_TOLERANCE else "BREACH"
        return {
            "tokens_issued": issued,
            "tokens_destroyed": destroyed,
            "tokens_fees_collected": float(row["tokens_fees_collected"]),
            "transit_net": transit,  # §B
            "total_circulating": circ,
            "net_supply": issued - destroyed + transit,
            "agent_count": int(row["agent_count"]),
            "atomic_delta": atomic_delta,
            "atomic_status": status,
            "as_of_event_seq": int(row["as_of_event_seq"]),
        }
    except Exception as e:
        logger.warning(f"[{frame['id']}] Atomic invariant read failed: {e}")
        return None


async def _true_supply(frame: dict) -> Optional[dict]:
    """Real mint/burn from the typed supply events since the balance-integrity
    baseline — the honest counterpart to supply_summary's transfer-leg-inflated
    issued/destroyed. Read-only, same pool as the atomic invariant. None if the
    DB is unavailable (graceful — the dashboard just omits it)."""
    pool = await _get_pool(frame)
    if pool is None:
        return None
    try:
        # asyncpg binds a ::timestamptz param as a datetime, not a str.
        try:
            since_dt = datetime.fromisoformat(TRUE_SUPPLY_SINCE)
        except Exception:
            since_dt = datetime(2026, 5, 29, tzinfo=timezone.utc)
        async with pool.acquire() as con:
            row = await con.fetchrow(TRUE_SUPPLY_SQL, since_dt)
        if row is None:
            return None
        return {
            "true_minted": float(row["true_minted"]),
            "true_burned": float(row["true_burned"]),
            "true_supply_since": TRUE_SUPPLY_SINCE,
        }
    except Exception as e:
        logger.warning(f"[{frame['id']}] True-supply read failed: {e}")
        return None


async def _per_user_integrity(frame: dict) -> Optional[dict]:
    """I3 — per-user conservation. Reads the per-agent floor (no negative liquid or
    staked balance) from the SAME materialized_balances projection as I1, plus the
    V0045 escrow-reconciler fingerprint event counts (24h). Independent + read-only;
    None if the DB is unavailable (graceful — dashboard omits I3 that cycle)."""
    pool = await _get_pool(frame)
    if pool is None:
        return None
    try:
        async with pool.acquire() as con:
            neg_rows = await con.fetch(NEG_DIDS_SQL, PER_USER_TOLERANCE)
            since_dt = datetime.now(timezone.utc) - timedelta(hours=24)
            try:
                ev = await con.fetchrow(LOCK_EVENTS_SQL, since_dt)
            except Exception:
                ev = None

        # §2026-06-25 (B) — classify each negative: genuine (live TEG holder → real
        # discrepancy, BREACH) vs orphan/transit (no TEG row → cross-TEG escrow projection
        # residue, EXCLUDED). Graceful + fail-LOUD: no TEG DSN / TEG unreachable → every
        # negative counts (legacy behaviour); never silently hides a real per-user breach.
        tol = PER_USER_TOLERANCE
        all_neg_dids = [r["agent_did"] for r in neg_rows]
        present: set = set()
        teg_checked = False
        pending: dict = {}
        journal_checked = False
        if all_neg_dids:
            teg_pool = await _get_teg_pool(frame)
            if teg_pool is not None:
                try:
                    async with teg_pool.acquire() as tcon:
                        prows = await tcon.fetch(TEG_PRESENT_SQL, all_neg_dids)
                    present = {r["agent_id"] for r in prows}
                    teg_checked = True
                except Exception as te:
                    logger.warning(f"[{frame['id']}] I3 TEG cross-check failed (counting all negs): {te}")
                # §LEDGERGATE E: the genuine negatives' balance changes still waiting in the TEG's journal
                if teg_checked and present:
                    try:
                        async with teg_pool.acquire() as tcon:
                            jrows = await tcon.fetch(TEG_PENDING_SQL, sorted(present))
                        pending = {r["agent_id"]: (int(r["rows"]), float(r["oldest_s"] or 0.0)) for r in jrows}
                        journal_checked = True
                    except Exception as je:
                        logger.warning(f"[{frame['id']}] I3 TEG journal read failed (no negative read as behind): {je}")

        # §LEDGERGATE F: the TEG's own census, every cycle (not only when the projection shows a negative)
        teg_neg = None
        census_pool = await _get_teg_pool(frame)
        if census_pool is not None:
            try:
                async with census_pool.acquire() as tcon:
                    crow = await tcon.fetchrow(TEG_NEGATIVE_SQL)
                teg_neg = (int(crow["n"]), float(crow["worst"] or 0.0)) if crow else (0, 0.0)
            except Exception as ce:
                logger.warning(f"[{frame['id']}] I3 TEG census failed (not checked this cycle): {ce}")

        # §CENSUS-BLINDSPOT (2026-08-12): the DID set of this frame's FEDERATED (cloud-op TEG)
        # agents. A federated agent has a real TEG-guarded ≥0 balance on its cloud-op TEG but
        # only a PARTIAL cross-frame-leg projection on THIS frame's ES — often negative. That
        # is a projection artifact, not a per-user breach, so exclude it (like orphan-transit).
        # None (file absent/incomplete) → no exclusion = legacy; a NATIVE negative always counts.
        fed_set = _read_federated_agents(frame["id"])

        g_neg_liq = g_neg_stk = 0
        g_worst_liq = g_worst_stk = 0.0
        g_sum_liq = g_sum_stk = 0.0
        o_count = 0
        o_total = 0.0
        f_count = 0
        f_total = 0.0
        b_count = b_rows = 0
        b_total = b_oldest = 0.0
        for r in neg_rows:
            liq = float(r["liq"]); stk = float(r["stk"])
            # Federated (real balance on a cloud-op TEG) → partial-projection artifact, EXCLUDE.
            if fed_set is not None and r["agent_did"] in fed_set:
                f_count += 1
                if liq < -tol:
                    f_total += -liq
                if stk < -tol:
                    f_total += -stk
                continue
            # No TEG check available → treat every negative as genuine (fail-loud legacy).
            genuine = (r["agent_did"] in present) if teg_checked else True
            # §LEDGERGATE E: genuine, but the TEG still holds its balance changes (recent ones): BEHIND, not a breach
            waiting = pending.get(r["agent_did"]) if genuine else None
            if waiting is not None and waiting[1] < PER_USER_BEHIND_MAX_S:
                b_count += 1
                b_rows += waiting[0]
                b_oldest = max(b_oldest, waiting[1])
                if liq < -tol:
                    b_total += -liq
                if stk < -tol:
                    b_total += -stk
                continue
            if genuine:
                if liq < -tol:
                    g_neg_liq += 1; g_sum_liq += -liq; g_worst_liq = min(g_worst_liq, liq)
                if stk < -tol:
                    g_neg_stk += 1; g_sum_stk += -stk; g_worst_stk = min(g_worst_stk, stk)
            else:
                o_count += 1
                if liq < -tol:
                    o_total += -liq
                if stk < -tol:
                    o_total += -stk

        neg_agents = g_neg_liq + g_neg_stk
        status = "BREACH" if neg_agents > 0 or (teg_neg is not None and teg_neg[0] > 0) else "OK"
        return {
            "status": status,
            "negative_agents": neg_agents,
            "neg_liquid_agents": g_neg_liq,
            "neg_staked_agents": g_neg_stk,
            "worst_liquid": g_worst_liq,
            "worst_staked": g_worst_stk,
            "negative_total": g_sum_liq + g_sum_stk,
            "tolerance": tol,
            # §2026-06-25 (B): ES-projection transit residue on agents with NO live TEG
            # balance — excluded from the breach (real money is TEG-guarded ≥0). Informational.
            "orphan_transit_excluded": o_count,
            "orphan_transit_total": round(o_total, 6),
            # §CENSUS-BLINDSPOT: federated (cloud-op TEG) agents whose negative on THIS frame's
            # ES is a partial-projection artifact — excluded from the breach, real balance is on
            # the cloud-op TEG. Informational (like orphan_transit). None-file ⇒ 0 (legacy count).
            "federated_excluded": f_count,
            "federated_excluded_total": round(f_total, 6),
            "teg_cross_checked": teg_checked,
            # §LEDGERGATE E: genuine negatives whose balance changes the TEG still holds (journal rows not yet emitted,
            # the oldest younger than PER_USER_BEHIND_MAX_S): behind, they resolve when the rows land. Not a breach.
            "behind_agents": b_count,
            "behind_total": round(b_total, 6),
            "behind_pending_rows": b_rows,
            "behind_oldest_s": round(b_oldest, 3),
            "behind_max_s": PER_USER_BEHIND_MAX_S,
            "teg_journal_checked": journal_checked,
            # §LEDGERGATE F: negative rows on the TEG itself (0 by its constraints; any is a BREACH); None = not checked
            "teg_negative_rows": teg_neg[0] if teg_neg is not None else None,
            "teg_negative_worst": round(teg_neg[1], 6) if teg_neg is not None else None,
            "teg_census_checked": teg_neg is not None,
            # V0045 lock-anomaly fingerprint (informational; 0 when healthy / absent).
            "escrow_negative_clamps_24h": int(ev["neg_clamps"]) if ev else 0,
            "escrow_orphan_releases_24h": int(ev["orphan_releases"]) if ev else 0,
        }
    except Exception as e:
        logger.warning(f"[{frame['id']}] Per-user integrity read failed: {e}")
        return None


# Cache for the heavy transit-by-kind decomposition: {frame_id: {"at": iso, "rows": [...]}}.
_transit_cache: dict = {}
_TRANSIT_REFRESH_SEC = float(os.getenv("TRANSIT_REFRESH_SEC", "1800"))  # 30 min default
# transit_net DRIFT monitoring: a per-frame baseline (persisted in meta) captures the
# settled transit_net at a known-clean moment; going forward, drift = current − baseline
# surfaces NEW stranding (escrow that locks but never releases, one-sided cross-frame legs)
# WITHOUT editing the truthful ledger value. Drift below −threshold ⇒ STRANDING alert.
_TRANSIT_DRIFT_ALERT = float(os.getenv("TRANSIT_DRIFT_ALERT", "1000"))


def _holder_label(did: str, fx_router_did: str) -> str:
    d = (did or "").lower()
    if "teg_system_treasury" in d: return "treasury"
    if "fee_collector" in d: return "fee_collector"
    if "fx_reserve" in d: return "fx_reserve"
    if "fx_router" in d or (fx_router_did and did == fx_router_did): return "fx_router"
    return "agent"


async def _staked_cross_check(frame: dict) -> Optional[dict]:
    """I4 — the ONLY cross-STORE assertion: EventStore staked_balance vs TEG locked_balance,
    per agent. Read-only on both sides. Returns None when either store is unreachable, which
    the dashboard renders as "not checked" rather than as a pass — an unrun check must never
    look like a passing one."""
    es_pool = await _get_pool(frame)
    teg_pool = await _get_teg_pool(frame)
    if es_pool is None or teg_pool is None:
        return None

    # §STAKEDCONFIRM (2026-08-10): the two reads are non-atomic across two databases, and
    # the projection mirrors TEG's 2PC escrow locks in staked_balance (LedgerBalanceChanged
    # cross_teg_escrow_lock/release on the fx_router). Under heavy cross-TEG traffic the two
    # snapshots describe different instants, so a shared system account transiently shows a
    # per-account diff in either direction (observed −781.08 on frame-b's fx_router during
    # the 2026-08-10 parked-route recovery; the day's lock/release sum was exactly 0). A
    # mismatch is therefore only reported if it survives a re-read after a settle delay —
    # the confirm pattern the escrow invariant already uses. A real one-sided loss (the
    # 2026-07-28 class, missing for hours) confirms instantly.
    async def _read_once():
        async with es_pool.acquire() as con:
            es_rows = await con.fetch(ES_STAKED_SQL)
        async with teg_pool.acquire() as tcon:
            teg_rows = await tcon.fetch(TEG_LOCKED_SQL)
        return ({r["did"]: float(r["amt"]) for r in es_rows},
                {r["did"]: float(r["amt"]) for r in teg_rows})

    def _mismatches(es_map: dict, teg_map: dict) -> dict:
        # Union, so a stake present on ONE side only is caught. The 2026-07-28 deletion left
        # accounts staked in TEG and zero in the projection; frame-b additionally carried an
        # impossible NEGATIVE stake on an account TEG held no stake for at all. A one-sided
        # sweep sees neither.
        out = {}
        for did in set(es_map) | set(teg_map):
            e, t = es_map.get(did, 0.0), teg_map.get(did, 0.0)
            diff = e - t
            tol = max(STAKED_GUARD_TOL_ABS, STAKED_GUARD_TOL_PCT * max(abs(e), abs(t)))
            if abs(diff) > tol:
                out[did] = {"did": did, "es": round(e, 6), "teg": round(t, 6),
                            "diff": round(diff, 6)}
        return out

    try:
        es, teg = await _read_once()
    except Exception as e:
        logger.warning(f"[{frame['id']}] I4 staked cross-check failed: {e}")
        return None

    mism = _mismatches(es, teg)
    confirm_reread = False
    transient_suppressed = 0
    if mism:
        await asyncio.sleep(STAKED_GUARD_CONFIRM_DELAY_SEC)
        try:
            es, teg = await _read_once()
        except Exception as e:
            logger.warning(f"[{frame['id']}] I4 staked confirm re-read failed: {e}")
            return None
        second = _mismatches(es, teg)
        persistent = {d: second[d] for d in (mism.keys() & second.keys())}
        transient_suppressed = len(mism) - len(persistent)
        if transient_suppressed:
            logger.info(
                f"[{frame['id']}] I4 staked: {transient_suppressed} transient per-account "
                f"diff(s) did not survive the {STAKED_GUARD_CONFIRM_DELAY_SEC:.0f}s re-read "
                f"(non-atomic cross-store snapshot under 2PC traffic) — suppressed")
        mism = persistent
        confirm_reread = True

    worst = sorted(mism.values(), key=lambda x: -abs(x["diff"]))
    mismatched = len(mism)
    es_total = round(sum(es.values()), 6)
    teg_total = round(sum(teg.values()), 6)

    diff_total = round(es_total - teg_total, 6)
    # Severity scales with how much of the stake is in dispute: a few units of compounding lag
    # is not the same event as most of the stake vanishing, and one alarm level for both would
    # train the operator to ignore it.
    scale = max(abs(teg_total), abs(es_total), 1.0)
    frac = abs(diff_total) / scale
    if mismatched == 0:
        status = "OK"
    elif frac >= STAKED_GUARD_BREACH_FRAC:
        status = "BREACH"
    else:
        status = "MISMATCH"
    return {
        "status": status,
        "checked": True,
        "es_total": es_total,
        "teg_total": teg_total,
        "diff_total": diff_total,
        "diff_fraction": round(frac, 6),
        "mismatched_agents": mismatched,
        "es_holders": len(es),
        "teg_holders": len(teg),
        "worst": worst[:5],
        "tolerance_abs": STAKED_GUARD_TOL_ABS,
        "tolerance_pct": STAKED_GUARD_TOL_PCT,
        "confirm_reread": confirm_reread,
        "transient_suppressed": transient_suppressed,
    }


async def _supply_composition(frame: dict) -> Optional[dict]:
    """V4 — locate the circulating supply + explain the issued↔circulating gap.

    Cheap part (every cycle): the waterfall (issued − destroyed + transit_net =
    circulating, so gap = issued − circulating = destroyed − transit_net), the named
    system-account buckets (treasury / fee_collector / fx_reserve / fx_router), the
    staked total, and the top-N holders. Heavy part (transit_net by kind) is refreshed
    on _TRANSIT_REFRESH_SEC and carried from cache. Read-only; None if DB unavailable."""
    pool = await _get_pool(frame)
    if pool is None:
        return None
    fid = frame["id"]
    fx_router_did = frame.get("fx_router_did") or ""
    try:
        async with pool.acquire() as con:
            ss = await con.fetchrow(
                "SELECT tokens_issued::float8 i, tokens_destroyed::float8 d, "
                "COALESCE(transit_net,0)::float8 t FROM supply_summary ORDER BY id LIMIT 1"
            )
            buckets = await con.fetchrow(HOLDER_BUCKETS_SQL, fx_router_did or "__none__")
            holders = await con.fetch(TOP_HOLDERS_SQL, 12)
        if ss is None:
            return None
        issued, destroyed, transit = float(ss["i"]), float(ss["d"]), float(ss["t"])
        circulating = issued - destroyed + transit
        gap = issued - circulating  # == destroyed - transit
        # transit_net drift vs a persisted per-frame baseline (auto-set on first sight).
        bkey = f"transit_baseline:{fid}"
        base_meta = await db.get_meta(bkey)
        if base_meta is None or "baseline" not in base_meta:
            base_meta = {"baseline": transit, "set_at": datetime.now(timezone.utc).isoformat(), "auto": True}
            await db.set_meta(bkey, base_meta)
            logger.info(f"[{fid}] transit_net baseline auto-set at {transit:.2f}")
        baseline = float(base_meta["baseline"])
        drift = transit - baseline
        drift_status = "STRANDING" if drift < -_TRANSIT_DRIFT_ALERT else ("RETURNING" if drift > _TRANSIT_DRIFT_ALERT else "OK")
        comp = {
            "issued": issued, "destroyed": destroyed, "transit_net": transit,
            "circulating": circulating, "issued_minus_circulating": gap,
            "transit_baseline": baseline, "transit_baseline_at": base_meta.get("set_at"),
            "transit_drift": drift, "transit_drift_status": drift_status,
            "currency": frame.get("currency"),
            "buckets": {
                "treasury": float(buckets["treasury"]),
                "fee_collector": float(buckets["fee_collector"]),
                "fx_reserve": float(buckets["fx_reserve"]),
                "fx_router": float(buckets["fx_router"]),
                "escrow": float(buckets["escrow"]),
                "agents": float(buckets["agents"]),
                "total_staked": float(buckets["total_staked"]),
            } if buckets else {},
            "holder_count": int(buckets["holder_count"]) if buckets else 0,
            "top_holders": [
                {"did": h["agent_did"], "label": _holder_label(h["agent_did"], fx_router_did),
                 "liquid": float(h["liquid"]), "staked": float(h["staked"]),
                 "total": float(h["liquid"]) + float(h["staked"])}
                for h in (holders or [])
            ],
        }
        # Heavy transit-by-kind: refresh on the slow cadence, else serve cache.
        cached = _transit_cache.get(fid)
        now = datetime.now(timezone.utc)
        stale = (cached is None) or (
            (now - datetime.fromisoformat(cached["at"])).total_seconds() > _TRANSIT_REFRESH_SEC
        )
        if stale:
            try:
                async with pool.acquire() as con:
                    # MEASURED 2026-08-22: the full-history breakdown takes 56-126s per
                    # frame (23-28M events, jsonb entries explode). The pool's
                    # command_timeout=15.0 killed it with an EMPTY-str TimeoutError on
                    # every attempt, so the panel silently served the catch-all
                    # remainder forever. Per-call fetch timeout overrides the pool;
                    # SET LOCAL inside a transaction so the server bound dies with the
                    # txn instead of leaking onto this pooled connection for its life.
                    async with con.transaction():
                        await con.execute("SET LOCAL statement_timeout = '240s'")
                        _t0 = time.time()
                        rows = await con.fetch(TRANSIT_KIND_SQL, timeout=250)
                _transit_cache[fid] = {
                    "at": now.isoformat(),
                    "rows": [{"kind": r["kind"], "events": int(r["events"]),
                              "net_to_balances": float(r["net_to_balances"])} for r in rows],
                }
                logger.info(f"[{fid}] transit-by-kind refreshed ({len(rows)} kinds, {time.time() - _t0:.1f}s)")
            except Exception as e:
                # {e!r}, never {e}: asyncpg timeout classes stringify EMPTY, and an
                # empty message hid every one of these failures since the restart.
                logger.warning(f"[{fid}] transit-by-kind refresh failed (serving cache): {e!r}")
        # Known transit kinds (escrow/stake legs). Append a single balancing
        # `transfer_settlement` remainder = transit_net − Σ(known) so the breakdown
        # sums EXACTLY to transit_net — nothing is "unknown", every cent is named.
        kind_rows = list((_transit_cache.get(fid) or {}).get("rows") or [])
        tnet = comp.get("transit_net")
        if tnet is not None:
            known_sum = sum(r["net_to_balances"] for r in kind_rows)
            remainder = round(float(tnet) - known_sum, 2)
            if abs(remainder) >= 0.01:
                # Fold any small residual (pre-§B kinded events / timing) into the
                # transfer_settlement line so there's ONE clean such row and the
                # breakdown sums exactly to transit_net — never a separate dangling term.
                ts = next((r for r in kind_rows if r["kind"] == "transfer_settlement"), None)
                if ts is not None:
                    ts["net_to_balances"] = round(ts["net_to_balances"] + remainder, 2)
                else:
                    kind_rows = kind_rows + [{
                        "kind": "transfer_settlement", "events": None, "net_to_balances": remainder,
                    }]
            comp["reconciled"] = abs(sum(r["net_to_balances"] for r in kind_rows) - float(tnet)) < 0.01
        comp["transit_by_kind"] = kind_rows
        comp["transit_by_kind_at"] = (_transit_cache.get(fid) or {}).get("at")
        return comp
    except Exception as e:
        logger.warning(f"[{fid}] supply composition read failed: {e}")
        return None


# ── Native-supply per-currency check (V6, 2026-06-19) ──────────────────────
# Proves per-frame conservation in the NATIVE currency WITHOUT de-agnosticizing the
# ledger. The ledger is currency-blind → "circulating" sums every currency on a frame's
# books while "issued" is native mints, so an FX-active frame reads circulating > issued.
# V6 reframes it honestly and adds a real (non-circular) integrity gate:
#   native_circulating = circulating − transit_net   (transit_net = cross-frame settlement
#                          residue / what's in-transit + foreign on the books)
#   native_issued      = true_minted                 (typed mint events — INDEPENDENT)
# Integrity: (circulating − transit_net) must equal (true_minted − true_burned). Because
# circ−transit ≡ issued_acc−destroyed_acc (atomic invariant), this tests that transit_net
# absorbed ALL non-mint movement AND the accumulators reconcile with REAL typed mints. A
# mis-stamped / hidden mint inflates circulating with no typed event → recon_gap blows the
# tolerance → native_supply_ok=false = the leak signal. Δ=0 alone cannot see this.
async def _crossteg_attribution(frame: dict) -> dict:
    """Currency attribution of the cross-TEG rail (read-only TEG DB), cached on a slow
    cadence. {} if no FRAME_<X>_TEG_DSN / unavailable (serves last cache if present)."""
    fid = frame["id"]
    cached = _crossteg_cache.get(fid)
    now = datetime.now(timezone.utc)
    if cached and (now - datetime.fromisoformat(cached["at"])).total_seconds() < _CROSSTEG_REFRESH_SEC:
        return cached["data"]
    pool = await _get_teg_pool(frame)
    if pool is None:
        return (cached or {}).get("data", {})
    native_ccy = (frame.get("currency") or "").upper()
    try:
        async with pool.acquire() as con:
            await con.execute("SET statement_timeout = '20s'")
            row = await con.fetchrow(CROSSTEG_CCY_SQL)
        # Same-currency rail → attribute the whole COMPLETED rail to the frame's native
        # currency; the stored per-row label is not authoritative (see CROSSTEG_CCY_SQL).
        data = {
            "crossteg_by_currency": [
                {"currency": native_ccy,
                 "native": True,
                 "transfers": int((row and row["transfers"]) or 0),
                 "completed_volume": float((row and row["completed_volume"]) or 0.0)}
            ],
            "crossteg_scope": "mainframe-teg",
        }
        _crossteg_cache[fid] = {"at": now.isoformat(), "data": data}
        return data
    except Exception as e:
        logger.warning(f"[{fid}] cross-teg currency attribution failed: {e}")
        return (cached or {}).get("data", {})


def _read_federated_out(fid: str) -> Optional[float]:
    """§CENSUS-BLINDSPOT — per-frame federated-out supply (Σ cloud-op TEG token_balance),
    published to /app/data/federated_out.json by scratchpad/publish_federated_out.py. None
    if absent/stale/incomplete → the auditor falls back to the pre-federation reading."""
    try:
        with open("/app/data/federated_out.json") as f:
            d = json.load(f)
        fr = (d.get("frames") or {}).get(fid) or {}
        if not fr.get("complete"):
            return None
        v = fr.get("federated_out")
        return float(v) if v is not None else None
    except Exception:
        return None


# §GLOBALSTD Phase 0-B (2026-08-22): the baseline read must be LOUD. A silently missing
# 888-byte file here converts a documented write-down into a public false 155M BREACH with
# nothing naming the cause. State is tracked per frame so each condition logs exactly once
# per transition (the 60s cadence would otherwise spam), and a baseline that DISAPPEARS
# after having been readable logs CRITICAL — that is the false-breach precursor.
_NATIVE_BASELINE_STATE: dict = {}


def _native_baseline_note(fid: str, state: str, level: int, msg: str) -> None:
    prev = _NATIVE_BASELINE_STATE.get(fid)
    if prev == state:
        return
    _NATIVE_BASELINE_STATE[fid] = state
    if prev == "ok" and state != "ok":
        logger.critical(
            f"[{fid}] NATIVEBASE baseline LOST (was readable, now {state}): {msg} — the recon "
            f"falls back and may announce the documented write-down as a gap or false BREACH"
        )
    else:
        logger.log(level, f"[{fid}] NATIVEBASE {msg}")


def _read_native_baseline(fid: str) -> Optional[dict]:
    """§NATIVEBASE (2026-08-17) — the per-frame native-supply write-down baseline, set at a
    verified at-rest moment (sim stopped, books census-clean). It carries the DOCUMENTED
    un-evented supply removal: the 2026-08-12 §BOOKRECON reconciliation booked ~155.29M BVT
    (frame-c) of phantom/federated projection write-downs into tokens_destroyed with no burn
    events behind them — correctly, because nothing was burned. recon_gap is therefore a
    FROZEN constant equal to that write-down, and reconciling against this baseline makes the
    check quiet at truth while any NEW un-evented destruction surfaces as a moving gap.
    File: /app/data/native_supply_baseline.json. Absent/invalid → None (legacy path) — but
    NEVER silently (§GLOBALSTD Phase 0-B): every fallback names itself in the log."""
    path = "/app/data/native_supply_baseline.json"
    try:
        with open(path) as f:
            d = json.load(f)
    except FileNotFoundError:
        _native_baseline_note(fid, "absent", logging.WARNING,
                              f"baseline file {path} ABSENT — recon uses legacy path")
        return None
    except Exception as e:
        _native_baseline_note(fid, "unreadable", logging.ERROR,
                              f"baseline file {path} UNREADABLE ({e!r}) — recon uses legacy path")
        return None
    fr = (d.get("frames") or {}).get(fid)
    if not fr:
        known = sorted((d.get("frames") or {}).keys())
        _native_baseline_note(fid, "no-entry", logging.INFO,
                              f"no baseline entry for '{fid}' (file carries {known}) — expected for pre-baseline frames")
        return None
    try:
        v = float(fr.get("baseline"))
    except (TypeError, ValueError):
        _native_baseline_note(fid, "malformed", logging.ERROR,
                              f"baseline entry for '{fid}' MALFORMED ({fr.get('baseline')!r}) — ignored, recon uses legacy path")
        return None
    if not (v > 0) or v == float("inf") or v != v:
        _native_baseline_note(fid, "malformed", logging.ERROR,
                              f"baseline {v!r} for '{fid}' fails sanity (must be finite and > 0) — ignored")
        return None
    set_at = fr.get("set_at")
    try:
        datetime.fromisoformat(str(set_at).replace("Z", "+00:00"))
    except Exception:
        logger.warning(f"[{fid}] NATIVEBASE set_at {set_at!r} is not parseable ISO — baseline still applied")
    _native_baseline_note(fid, "ok", logging.INFO, f"baseline {v} (set {set_at}) in effect")
    return {"baseline": v, "set_at": set_at, "ref": fr.get("ref")}


def _read_federated_agents(fid: str) -> Optional[set]:
    """§CENSUS-BLINDSPOT (per_user) — the DID set of a frame's federated (cloud-op TEG)
    agents, published to /app/data/federated_agents.json by publish_federated_out.py. A
    federated agent's PARENT-frame ES projection is a PARTIAL cross-frame-leg artifact (its
    real, TEG-guarded ≥0 balance lives on the cloud-op TEG), so a negative on it is NOT a
    per-user breach. Returns the set, or None if absent/incomplete → the check falls back to
    counting every negative (fail-loud legacy; never silently hides a real NATIVE breach)."""
    try:
        with open("/app/data/federated_agents.json") as f:
            d = json.load(f)
        fr = (d.get("frames") or {}).get(fid) or {}
        dids = fr.get("dids")
        # Unlike native_supply (which needs a COMPLETE total to reconcile), per_user does a
        # per-agent MEMBERSHIP test: an incomplete set can only UNDER-exclude (a residual
        # false-positive), never wrongly exclude a NATIVE negative — so use it even when a
        # cloud-op is missing (e.g. frame-a qatest16). Empty/absent ⇒ None (legacy count).
        return set(dids) if dids else None
    except Exception:
        return None


async def _native_supply(frame: dict, atomic: Optional[dict],
                         true_supply: Optional[dict]) -> Optional[dict]:
    if not atomic or not true_supply:
        return None
    fid = frame["id"]
    try:
        circ = float(atomic["total_circulating"])
        transit = float(atomic.get("transit_net") or 0.0)
        minted = float(true_supply.get("true_minted") or 0.0)
        burned = float(true_supply.get("true_burned") or 0.0)
        native_circ = round(circ - transit, 2)
        recon_gap = round(native_circ - (minted - burned), 2)

        # COVERAGE GATE — is the typed-mint figure COMPLETE? true_minted counts mints
        # since TRUE_SUPPLY_SINCE. A frame whose issuance predates the baseline (the
        # genesis AVT mainframe carries pre-`kind` ledger events + guard-era typed-mint
        # inflation that don't reconcile) has INCOMPLETE coverage → the recon is then
        # informational, NOT a breach. A frame with NO pre-baseline issuance (a clean
        # post-baseline frame, e.g. BVT) has COMPLETE coverage → recon_gap > TOL is a
        # REAL finding (mis-stamped/hidden mint). This keeps the leak-detector honest
        # on clean frames without false-flagging old ones.
        complete: Optional[bool] = None
        try:
            pool = await _get_pool(frame)
            if pool is not None:
                since_dt = datetime.fromisoformat(TRUE_SUPPLY_SINCE)
                async with pool.acquire() as con:
                    has_pre = await con.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM events "
                        "WHERE event_type IN ('TokensIssued','UnitsIssued') AND timestamp < $1)",  # W4: either name
                        since_dt,
                    )
                complete = not bool(has_pre)
        except Exception as e:
            logger.warning(f"[{fid}] native-supply baseline-coverage probe failed: {e}")

        # §NATIVEBASE (2026-08-17) — the federated_out term was WRONG in this identity and
        # was the oscillator behind the flickering "-155M gap" panel. The old comment's
        # premise ("the balance projection ignores their LedgerBalanceChanged") is FALSE:
        # the parent ES projection DOES apply cloud-op balance deltas via the TEG outbox
        # (measured 2026-08-17: 88.2M of federated-agent rows in frame-c's projection), so
        # adding the op TEGs' full LEVELS on top double-counts every delta since the
        # 2026-08-12 write-down. recon_gap itself is a FROZEN constant (the documented
        # §BOOKRECON write-down, booked as tokens_destroyed with no burn events, correctly),
        # while federated_out moves with every mainframe<->op sim flow — hence the flicker
        # (breach shown or not depending on the sim's net op-holdings that cycle).
        # Durable reconciliation: recon_gap + the frozen per-frame baseline set at a
        # verified at-rest moment (§TRANSITBASE pattern). NEW un-evented destruction now
        # surfaces as a moving gap, which is the thing this check exists to catch.
        # federated_out stays in the payload as a DIAGNOSTIC, never in the verdict.
        federated_out = _read_federated_out(fid)
        recon_gap_fed = round(recon_gap + federated_out, 2) if federated_out is not None else None
        nb = _read_native_baseline(fid)
        recon_gap_rebased = round(recon_gap + nb["baseline"], 2) if nb is not None else None
        if complete is True and nb is not None:
            recon_basis = "writedown_rebaselined"
            native_supply_ok: Optional[bool] = abs(recon_gap_rebased) <= NATIVE_SUPPLY_TOL
        elif complete is True and federated_out is not None:
            fed_tol = max(NATIVE_SUPPLY_TOL, 0.005 * abs(federated_out))
            recon_basis = "federated_reconciled"
            native_supply_ok = abs(recon_gap_fed) <= fed_tol
        elif complete is True:
            recon_basis = "typed_mints_complete"
            native_supply_ok = abs(recon_gap) <= NATIVE_SUPPLY_TOL
        elif complete is False:
            recon_basis = "pre_baseline_genesis"  # issuance predates baseline → total unverifiable
            native_supply_ok = None               # NOT a breach; atomic Δ=0 still governs
        else:
            recon_basis = "coverage_unknown"
            native_supply_ok = None

        out = {
            "native_currency": frame.get("currency"),
            "native_issued": round(minted, 2),         # typed mints SINCE baseline
            "native_burned": round(burned, 2),
            "native_issued_complete": complete,         # True → native_issued == total issuance
            "native_circulating": native_circ,          # = circulating − transit_net (native on books)
            "crossframe_residual": round(transit, 2),   # in-transit cross-frame settlement
            "recon_gap": recon_gap,
            "federated_out": round(federated_out, 2) if federated_out is not None else None,
            "recon_gap_after_federation": recon_gap_fed,  # DIAGNOSTIC only since §NATIVEBASE (double-counts op deltas)
            "writedown_baseline": nb["baseline"] if nb is not None else None,
            "writedown_baseline_set_at": nb.get("set_at") if nb is not None else None,
            "recon_gap_rebased": recon_gap_rebased,       # recon_gap + baseline (0 => explained; drift => NEW un-evented destruction)
            "recon_basis": recon_basis,
            "native_supply_ok": native_supply_ok,
        }
        out.update(await _crossteg_attribution(frame))  # currency attribution (cached)
        return out
    except Exception as e:
        logger.warning(f"[{fid}] native-supply compute failed: {e}")
        return None


# ── AGORA share registry (V5) — the stock analog of the currency composition ──

def _share_holder_label(is_treasury: bool) -> str:
    return "treasury" if is_treasury else "public"


async def _share_registry(frame: dict) -> Optional[dict]:
    """Per-listing share cap table for this frame, read DIRECTLY from the registry
    DB (independent witness — never the registry's /exchange API). For each listed
    org: total shares, holder count, the treasury / public / unsold-IPO-float split
    (sums to total_shares — the share-conservation identity), locked shares (backing
    open SELL orders), and the top holders. None if the frame has no reg_dsn."""
    pool = await _get_reg_pool(frame)
    if pool is None:
        return None
    fid = frame["id"]

    # Slow-cadence cache: refresh far less often than the 60s supply-Δ cycle, so the
    # exchange-stock reads barely touch the production registry DB. Reuse between refreshes.
    now = datetime.now(timezone.utc)
    cached = _shares_cache.get(fid)
    if cached and (now - datetime.fromisoformat(cached["at"])).total_seconds() < _SHARES_REFRESH_SEC:
        return cached["data"]

    try:
        async with pool.acquire() as con:
            listings = await con.fetch(SHARE_LISTINGS_SQL)
            holders = await con.fetch(SHARE_TOP_HOLDERS_SQL, 8)
            prices = await con.fetch(SHARE_LAST_PRICE_SQL)
            activity = await con.fetch(SHARE_ACTIVITY_SQL)
            # SET LOCAL in a txn: the bound dies with it instead of leaking onto the
            # pooled connection for its lifetime (same class as the transit fix).
            async with con.transaction():
                await con.execute("SET LOCAL statement_timeout = '30s'")  # bound the 24h spark scan
                srows = await con.fetch(SHARE_SPARK_SQL)
    except Exception as e:
        _record_share_error(fid, "read", e, frame.get("reg_dsn"))
        logger.warning(f"[{fid}] share registry read failed: {_share_errors[fid]['error']}")
        # Serve stale cache on a transient error rather than dropping the panel (the venue answer names it "stale").
        return cached["data"] if cached else None

    by_listing: dict = {}
    for h in holders:
        by_listing.setdefault(h["listing_id"], []).append(h)
    last_price = {r["listing_id"]: (float(r["price"]), r["created_at"]) for r in prices if r["price"] is not None}
    activity_by = {r["listing_id"]: r for r in activity}
    spark_by_listing: dict = {}
    for r in srows:
        spark_by_listing.setdefault(r["listing_id"], []).append(round(float(r["price"]), 6))

    out_listings = []
    breached = []
    for l in listings:
        total = float(l["total_shares"])
        held = float(l["held"])
        treasury_qty = float(l["treasury_qty"])
        public_held = max(0.0, held - treasury_qty)
        float_unissued = total - held  # unsold IPO float / shares not yet allocated
        ipo_float = float(l["ipo_float"]); ipo_sold = float(l["ipo_sold"])
        neg_holders = int(l["neg_holders"]); over_locked = int(l["over_locked"]); neg_locked = int(l["neg_locked"])

        # ── I-Shares conservation invariant (per listing) — the share analog of I1/I3.
        # treasury + public + unsold == total_shares is the identity; these are the ways
        # it can be VIOLATED (each should be impossible in a sound long-only share ledger).
        violations = []
        if held - total > 0.5:
            violations.append(f"over-issued: held {int(held)} > total {int(total)}")
        if neg_holders > 0:
            violations.append(f"{neg_holders} holder(s) with negative points")
        if over_locked > 0:
            violations.append(f"{over_locked} holder(s) locked > owned")
        if neg_locked > 0:
            violations.append(f"{neg_locked} negative lock(s)")
        if ipo_sold - ipo_float > 0.5:
            violations.append(f"launch oversold: {int(ipo_sold)} > allocation {int(ipo_float)}")
        ok = not violations

        # ── current price (local currency) + 24h trend ──
        lp = last_price.get(l["id"])
        price = lp[0] if lp else None
        last_trade_at = lp[1].isoformat() if (lp and lp[1]) else None
        spark = spark_by_listing.get(l["id"], [])
        change_pct = ((spark[-1] - spark[0]) / spark[0] * 100.0) if (len(spark) >= 2 and spark[0] > 0) else None

        tops = [
            {
                "did": h["agent_did"],
                "label": _share_holder_label(bool(h["is_treasury"])),
                "qty": float(h["qty"]),
                "locked": float(h["locked"]),
                "pct": (float(h["qty"]) / total * 100.0) if total > 0 else 0.0,
            }
            for h in by_listing.get(l["id"], [])
        ]
        out_listings.append({
            "symbol": l["symbol"],
            "display_name": l["display_name"],
            "currency": l["currency"],
            "status": l["status"],
            "total_shares": total,
            "ipo_float": ipo_float,
            "ipo_sold": ipo_sold,
            "holders": int(l["holders"]),
            "treasury_did": l["treasury_did"],
            "treasury_qty": treasury_qty,
            "public_held": public_held,
            "float_unissued": max(0.0, float_unissued),
            "locked": float(l["locked"]),
            "neg_holders": neg_holders,
            "over_locked": over_locked,
            # I-Shares verdict (reconciled kept = ok for back-compat with the panel badge):
            "ok": ok,
            "violations": violations,
            "reconciled": ok,
            # price + trend (local currency):
            "price": price,
            "price_currency": l["currency"],
            "last_trade_at": last_trade_at,
            "price_spark": spark,
            "price_change_pct": change_pct,
            "spark_window": "24h",
            # §AGORAFLAT — activity, so a pinned price cannot masquerade as a dead market:
            "trades_24h": int((activity_by.get(l["id"]) or {}).get("trades_24h") or 0),
            "vol_24h_qty": float((activity_by.get(l["id"]) or {}).get("vol_24h_qty") or 0.0),
            "vol_24h_notional": float((activity_by.get(l["id"]) or {}).get("vol_24h_notional") or 0.0),
            "top_holders": tops,
        })
        if not ok:
            breached.append({"symbol": l["symbol"], "violations": violations})

    data = {
        "listings": out_listings,
        "listing_count": len(out_listings),
        # I-Shares aggregate invariant for this frame (independent — like I3, it does
        # NOT feed the I1 supply uptime; it is its own conservation witness).
        "status": "BREACH" if breached else "OK",
        "breached_count": len(breached),
        "breached": breached,
        "refreshed_at": now.isoformat(),
        "spark_at": now.isoformat(),
    }
    _shares_cache[fid] = {"at": now.isoformat(), "data": data}
    _share_errors.pop(fid, None)
    logger.info(
        f"[{fid}] share registry refreshed ({len(out_listings)} listings, "
        f"status={data['status']}, every {int(_SHARES_REFRESH_SEC)}s)"
    )
    return data


# ── AGORA escrow invariant (I-X3) — independent witness against the racy gauge ──

async def _escrow_invariant(frame: dict) -> Optional[dict]:
    """I-X3 — AGORA escrow conservation, computed independently + READ-ONLY.

    actual_escrow  := the AGORA escrow agent's LIVE liquid balance, read DIRECTLY from
                      the frame's TEG DB (exactly what the mover's /escrow returns).
    expected_escrow := the registry's 5-term escrow expectation, read DIRECTLY from the
                      frame's REGISTRY DB (replicates compute_invariants() byte-for-byte:
                      buy_holds + unsettled_notional + ipo_in_flight + unpaid_div_legs
                      + LISTING_FEE * parked_fees).
    delta := actual − expected.

    CONFIRM (defeats the per-worker snapshot race the registry gauge suffers): if
    |delta| > TOL, sleep then RE-READ both sides and recompute. BREACH only when the
    delta PERSISTS *and* |delta| > funding_notional + TOL — i.e. it is NOT explained by
    in-flight 'funding' deposits (the documented legitimate transient). Else OK.

    Returns None if the frame is not equipped (no registry/TEG DSN). NEVER raises — any
    pool/read error returns {"status":"ERROR","error":...} so the audit loop is safe."""
    reg_pool = await _get_reg_pool(frame)
    teg_pool = await _get_teg_pool(frame)
    if reg_pool is None or teg_pool is None:
        return None  # frame has no registry/TEG DSN → I-X3 omitted (graceful, like I3/V5)

    async def _read() -> tuple:
        async with reg_pool.acquire() as rcon:
            exp = await rcon.fetchrow(ESCROW_EXPECTED_SQL)
            fund = await rcon.fetchrow(ESCROW_FUNDING_SQL)
        async with teg_pool.acquire() as tcon:
            actual_v = await tcon.fetchval(ESCROW_ACTUAL_SQL, ESCROW_TEG_DID)
        expected_v = (
            float(exp["buy_holds"])
            + float(exp["unsettled_notional"])
            + float(exp["ipo_in_flight"])
            + float(exp["unpaid_div_legs"])
            + EXCHANGE_LISTING_FEE * float(exp["parked_fees"])
        )
        return (
            float(actual_v or 0.0), expected_v,
            int(fund["n"]), float(fund["notional"]),
        )

    try:
        actual, expected, funding_n, funding_notional = await _read()
        delta = actual - expected
        confirmed = False
        if abs(delta) > ESCROW_INVARIANT_TOL:
            # Re-read BOTH sides after a short settle — kills the per-worker race and lets
            # a same-cycle 'funding' deposit/status-flip converge before we judge.
            await asyncio.sleep(ESCROW_CONFIRM_SLEEP_SEC)
            actual, expected, funding_n, funding_notional = await _read()
            delta = actual - expected
            confirmed = True
        # BREACH iff the (confirmed) delta exceeds what in-flight funding can explain.
        # funding_notional ≥ 0 ⇒ this also implies |delta| > TOL (the delta PERSISTED).
        breached = abs(delta) > (funding_notional + ESCROW_INVARIANT_TOL)
        return {
            "actual": round(actual, 6),
            "expected": round(expected, 6),
            "delta": round(delta, 6),
            "funding_n": funding_n,
            "funding_notional": round(funding_notional, 6),
            "status": "BREACH" if breached else "OK",
            "confirmed": confirmed,
            "tolerance": ESCROW_INVARIANT_TOL,
        }
    except Exception as e:
        logger.warning(f"[{frame['id']}] escrow invariant (I-X3) read failed: {e}")
        return {"status": "ERROR", "error": str(e)}


# ── FX reserve solvency (independent I2 invariant) ────────────────────────
# The supply invariant (I1) is structurally BLIND to FX liquidity: @fx_reserve and
# @fx_router are ordinary balances counted in Σ(liquid+staked), so a draining reserve
# or stranded op→op router residue keeps Δ=0. This reads those balances directly from
# the SAME materialized_balances snapshot and checks them against the auditor's OWN
# configured floors — an INDEPENDENT witness (never the registry's /fx/pool).
SOLVENCY_SQL = """
SELECT agent_did, (liquid_balance + staked_balance)::float8 AS bal
FROM materialized_balances
WHERE agent_did = ANY($1::text[])
"""


async def _solvency(frame: dict) -> Optional[dict]:
    """Independent FX reserve solvency (I2). None if the frame has no @fx_reserve
    (i.e. it is not an FX reserve frame — e.g. Frame B). Read-only, same pool."""
    pool = await _get_pool(frame)
    if pool is None:
        return None
    reserve_did = FX_RESERVE_DID
    router_did = (frame.get("fx_router_did") or "").strip()
    wanted = [reserve_did] + ([router_did] if router_did else [])
    try:
        async with pool.acquire() as con:
            rows = await con.fetch(SOLVENCY_SQL, wanted)
    except Exception as e:
        logger.warning(f"[{frame['id']}] Solvency read failed: {e}")
        return None
    bals = {r["agent_did"]: float(r["bal"]) for r in rows}
    if reserve_did not in bals:
        return None  # not a reserve frame → no solvency dimension
    bal = bals[reserve_did]
    floor = float(frame.get("fx_reserve_floor") or 0.0)
    if floor <= 0:
        status = "SOLVENT"
    elif bal < floor:
        status = "BREACH"
    elif bal < floor * FX_SOLVENCY_WARN_FACTOR:
        status = "LOW"
    else:
        status = "SOLVENT"
    # Fuel gauge: full at ≥ COMFORT_MULT × floor; the floor sits at (1/COMFORT_MULT).
    gauge_pct = 100.0 if floor <= 0 else max(
        0.0, min(100.0, bal / (floor * FX_SOLVENCY_COMFORT_MULT) * 100.0)
    )
    out = {
        "present": True,
        "currency": frame.get("currency", "AVT"),
        "reserve_did": reserve_did,
        "reserve_balance": bal,
        "floor": floor,
        "headroom": bal - floor,
        "headroom_x": (bal / floor) if floor > 0 else None,
        "gauge_pct": gauge_pct,
        "status": status,
    }
    if router_did:
        residue = bals.get(router_did, 0.0)
        out.update({
            "router_did": router_did,
            "router_residue": residue,
            "router_threshold": FX_ROUTER_RESIDUE_THRESHOLD,
            "router_status": "RESIDUE" if residue > FX_ROUTER_RESIDUE_THRESHOLD else "OK",
        })
    return out


def _fx_pool(per_frame: dict) -> Optional[dict]:
    """Cross-frame FX pool health from raw reserves (TRACKED, never a gate). Pairs the
    AVT reserve frame with the BVT reserve frame in one mode: x=AVT, y=BVT, spot=x/y
    (AVT per BVT), k=x·y, MtM=x+y·spot. Computed independently from the two balances."""
    avt = next((s for s in per_frame.values() if s and s.get("currency") == "AVT"), None)
    bvt = next((s for s in per_frame.values() if s and s.get("currency") == "BVT"), None)
    if not avt or not bvt:
        return None
    x = float(avt["reserve_balance"])
    y = float(bvt["reserve_balance"])
    if x <= 0 or y <= 0:
        return None
    spot = x / y
    return {
        "x_avt": x, "y_bvt": y,
        "spot_avt_per_bvt": spot,
        "spot_bvt_per_avt": (1.0 / spot) if spot else None,
        "k": x * y,
        "mtm_avt": x + y * spot,
        "tracked_not_gated": True,
    }


# ── Audit loop ──────────────────────────────────────────────────────────

async def _do_audit(frame: dict) -> Optional[dict]:
    """Execute one supply audit check for a specific frame (atomic + live-read)."""
    global total_audits

    frame_id = frame["id"]
    url = frame["url"]
    t0 = time.monotonic()
    in_maintenance = bool(maintenance_state.get("active", False))

    # ── HTTP live-read (transient signal; in-flight outbox lag) ─────────
    live_delta = 0.0
    live_status = "ERROR"
    live_issued = 0.0
    live_circ = 0.0
    http_extra: dict = {}
    http_error: Optional[str] = None
    # §MTLSHOPS (a) (2026-09-15, his decision; agentvault2-85's rules): what this read may send is decided per slot
    # (tls_client.live_read_plan). An extra slot never inherits this host's key; a public read sends no key and no
    # certificate; an extra slot with neither a key nor a certificate of this auditor is not read, and says so.
    plan = tls_client.live_read_plan(frame, EVENT_STORE_KEY, cert=AUDITOR_TLS_CERT, key=AUDITOR_TLS_KEY, ca=AUDITOR_TLS_CA)
    live_skipped = "" if plan["read"] else plan["skipped"]
    if plan["read"]:
        try:
            # §MTLSHOPS T2 (S4, 2026-09-15): TLS by scheme; a solo auditor reads its frame through the store's mTLS sidecar
            data = await tls_client.read_supply_audit(
                url, plan["store_key"], cert=plan["cert"], key=plan["key"], ca=plan["ca"],
            )
            live_issued = float(data.get("tokens_issued", 0))
            live_circ = float(data.get("total_circulating", 0))
            live_delta = float(data.get("delta", 0))
            live_status = data.get("status", "UNKNOWN")
            for key in ("tokens_destroyed", "tokens_fees_collected", "net_supply", "agent_count"):
                if key in data:
                    http_extra[key] = data[key]
        except Exception as e:
            http_error = str(e)
            logger.warning(f"[{frame_id}] HTTP live-read failed: {e}")
    else:
        logger.warning(f"[{frame_id}] HTTP live-read {live_skipped}")

    public_only = bool(frame.get("public_only"))
    if public_only:
        # §MTLSHOPS (a): a public-only slot holds no DSN, so nothing below reads a database for it. Every check it cannot
        # make is recorded as not measured with its reason (extra_data.not_measured), never as a pass and never as absent.
        atomic = true_supply = solvency = per_user = staked_guard = composition = shares = escrow = native_supply = None
    else:
        # ── Atomic truth (direct DB single-statement) ──────────────────────
        atomic = await _atomic_invariant(frame)
        # ── True mint/burn (typed supply events since baseline) — A2 ────────
        true_supply = await _true_supply(frame)
        # ── FX reserve solvency (independent I2) — None on non-reserve frames ─
        solvency = await _solvency(frame)
        # ── Per-user conservation (independent I3) — None if DB unavailable ───
        per_user = await _per_user_integrity(frame)
        # ── Supply composition (V4): where circulating sits + transit decomposition ──
        # ── I4: TEG↔ES staked cross-check (§AUDITFIX) — the only cross-STORE assertion ──
        staked_guard = await _staked_cross_check(frame)
        composition = await _supply_composition(frame)
        # ── AGORA share registry (V5): who holds the stocks (registry DB) — None if no reg_dsn ──
        shares = await _share_registry(frame)
        # ── AGORA escrow invariant (I-X3): TEG-actual vs registry-expected escrow, confirmed ──
        escrow = await _escrow_invariant(frame)
        # ── Native-supply per-currency check (V6): native_issued == native_circulating ──
        native_supply = await _native_supply(frame, atomic, true_supply)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    atomic_available = atomic is not None
    if atomic_available:
        # Truth-preferred numbers for the supply detail.
        rec_issued = atomic["tokens_issued"]
        rec_circ = atomic["total_circulating"]
        rec_destroyed = atomic["tokens_destroyed"]
        atomic_delta = atomic["atomic_delta"]
        atomic_status = atomic["atomic_status"]
        agent_count = atomic["agent_count"]
        net_supply = atomic["net_supply"]
        fees = atomic["tokens_fees_collected"]
    else:
        # Fallback: no DB access → live-read carries the headline.
        rec_issued = live_issued
        rec_circ = live_circ
        rec_destroyed = http_extra.get("tokens_destroyed")
        atomic_delta = None
        atomic_status = None
        agent_count = http_extra.get("agent_count")
        net_supply = http_extra.get("net_supply")
        fees = http_extra.get("tokens_fees_collected")

    # `delta`/`status` columns stay = HTTP live-read (continuity); when the HTTP
    # call failed but atomic succeeded, mirror atomic so the row isn't an ERROR.
    if (http_error or live_skipped) and atomic_available:
        live_delta = atomic_delta
        live_status = atomic_status

    extra_data = {
        "tokens_destroyed": rec_destroyed,
        "tokens_fees_collected": fees,
        "net_supply": net_supply,
        "agent_count": agent_count,
        "atomic_available": atomic_available,
        "live_delta": live_delta,
        "live_status": live_status,
        "live_tokens_issued": live_issued,
        "live_total_circulating": live_circ,
        # A2: real mint/burn from typed events (issued/destroyed above are
        # transfer-leg-inflated accumulators, NOT mint/burn).
        "true_minted": (true_supply or {}).get("true_minted"),
        "true_burned": (true_supply or {}).get("true_burned"),
        "true_supply_since": (true_supply or {}).get("true_supply_since"),
        # I2: independent FX reserve solvency (None on non-reserve frames).
        "solvency": solvency,
        # I3: independent per-user conservation (negative agent balances + V0045
        # escrow lock-anomaly fingerprint). None if DB unavailable this cycle.
        "per_user": per_user,
        # I4: TEG(locked_balance) vs EventStore(staked_balance), per agent. None = not
        # checked this cycle (a store was unreachable) — rendered as unchecked, never as OK.
        "staked_guard": staked_guard,
        # V4: supply composition — top holders + named system accounts (WHERE the
        # circulating sits) + transit_net by kind (WHAT created the issued↔circulating
        # gap; escrow refund/lock residue dominates). None if DB unavailable.
        "composition": composition,
        # V5: AGORA share registry — per-listing cap table (who holds the stocks),
        # read directly from the registry DB. None if the frame has no reg_dsn.
        "shares": shares,
        # I-X3: AGORA escrow conservation — TEG-actual vs registry-expected escrow,
        # CONFIRMED on re-read (the authoritative refutation of the registry's racy
        # per-worker agora_invariant_delta gauge). None if the frame has no reg/TEG DSN.
        "escrow": escrow,
        # V6: native-supply per-currency — native_issued == native_circulating + the
        # non-circular recon gate + currency attribution. None if atomic/true-supply absent.
        "native_supply": native_supply,
    }
    if http_error:
        extra_data["live_error"] = http_error
    if live_skipped:
        extra_data["live_skipped"] = live_skipped
    if frame.get("public_read"):
        extra_data["public_read"] = True
        extra_data["public_source"] = f"{url}/api/v1/projections/supply-audit"
    if public_only:
        extra_data["public_only"] = True
        extra_data["attested_by"] = "the frame's own auditor"
        extra_data["public_breach_readings"] = PUBLIC_BREACH_READINGS
        extra_data["not_measured"] = {k: PUBLIC_ONLY_REASON for k in (
            "atomic", "true_supply", "solvency", "per_user", "staked_guard", "composition", "shares", "escrow", "native_supply")}

    result = await db.record_audit(
        tokens_issued=rec_issued,
        total_circulating=rec_circ,
        delta=live_delta,
        status=live_status,
        response_ms=elapsed_ms,
        frame=frame_id,
        extra_data=extra_data,
        atomic_delta=atomic_delta,
        atomic_status=atomic_status,
        maintenance=in_maintenance,
        tokens_destroyed=rec_destroyed,
        source="public" if public_only else "audit",
        public_breach_readings=PUBLIC_BREACH_READINGS,
    )

    # §GLOBALSTD Phase 1 — sign the verdict (audit-row first, attestation second;
    # a failed emit logs and NEVER poisons the audit path).
    # §MTLSHOPS (a) (agentvault2-85's call): the host does not attest a public-only frame. A TPSA-1 attestation claims the
    # atomic check; the frame's own auditor keeps that chain.
    if not public_only:
        try:
            await _emit_attestation(frame, result, atomic, native_supply, per_user,
                                    staked_guard, escrow, shares, solvency, in_maintenance)
        except Exception as e:
            logger.error(f"[{frame_id}] TPSA attestation emit failed (audit stored, unsigned this cycle): {e}")

    if public_only:
        # §MTLSHOPS (a): a public reading never feeds the streak, the uptime or the atomic status.
        public_streak[frame_id] = int(result.get("public_breach_streak") or 0)
        truth_status = None
    else:
        # Truth status drives the streak / health signal.
        truth_status = atomic_status or live_status
        if truth_status == "OK" or in_maintenance:
            consecutive_ok[frame_id] = consecutive_ok.get(frame_id, 0) + 1 if truth_status == "OK" else consecutive_ok.get(frame_id, 0)
        else:
            consecutive_ok[frame_id] = 0

    total_audits += 1
    latest_results[frame_id] = result

    # Independent solvency-incident tracking (kind='solvency'); a reserve BELOW its
    # floor opens an incident (maintenance-aware). Router residue is surfaced but is
    # Δ-neutral parked value (a sweep hint), not a breach.
    if solvency is not None:
        try:
            await db.record_solvency_incident(
                frame=frame_id,
                breached=(solvency.get("status") == "BREACH"),
                detail=solvency,
                maintenance=in_maintenance,
            )
        except Exception as e:
            logger.warning(f"[{frame_id}] solvency incident record failed: {e}")

    # Independent escrow-incident tracking (kind='escrow'); mirrors the solvency path —
    # a CONFIRMED I-X3 BREACH (delta persists + not explained by in-flight funding) opens
    # an incident, OK resolves it. ERROR/absent cycles leave the incident table untouched.
    if escrow is not None and escrow.get("status") in ("OK", "BREACH"):
        try:
            await db.record_escrow_incident(
                frame=frame_id,
                breached=(escrow.get("status") == "BREACH"),
                detail=escrow,
                maintenance=in_maintenance,
            )
        except Exception as e:
            logger.warning(f"[{frame_id}] escrow incident record failed: {e}")

    # I-X3 escrow breach is independent of the supply (I1) status — surface it loudly.
    # It is the auditor's own confirmed verdict, the refutation the registry gauge lacks.
    if escrow is not None and escrow.get("status") == "BREACH" and not in_maintenance:
        logger.error(
            f"[{frame_id}] I-X3 ESCROW BREACH (confirmed): actual={escrow.get('actual')} "
            f"expected={escrow.get('expected')} delta={escrow.get('delta')} "
            f"(funding_n={escrow.get('funding_n')} funding_notional={escrow.get('funding_notional')}) "
            f"— NOT explained by in-flight funding."
        )

    # I3 per-user breach is independent of the supply (I1) status — surface it
    # loudly even when Δ=0 (that is precisely the I1 blind spot it covers).
    if per_user is not None and per_user.get("status") == "BREACH" and not in_maintenance:
        logger.error(
            f"[{frame_id}] I3 PER-USER BREACH: {per_user['negative_agents']} agent(s) with "
            f"negative balance (worst_liquid={per_user['worst_liquid']} "
            f"worst_staked={per_user['worst_staked']} total={per_user['negative_total']}) — "
            f"Δ may still read 0 (sum hides it)."
        )
    elif per_user is not None and per_user.get("escrow_negative_clamps_24h", 0) > 0 and not in_maintenance:
        logger.warning(
            f"[{frame_id}] I3 lock-anomaly: {per_user['escrow_negative_clamps_24h']} "
            f"NegativeEscrowLockClamped event(s) in 24h (escrow double-release recurring?)."
        )

    # I-Shares conservation breach (independent of I1; AGORA share over-issuance /
    # negative holdings / over-lock). Surface loudly — like I3, the headline Δ can't see it.
    if shares is not None and shares.get("status") == "BREACH" and not in_maintenance:
        logger.error(
            f"[{frame_id}] I-SHARES BREACH: {shares.get('breached_count')} listing(s) violate "
            f"share conservation — "
            + "; ".join(f"${b['symbol']}: {', '.join(b['violations'])}" for b in shares.get("breached", []))
        )

    level = logging.INFO if (live_status if public_only else truth_status) == "OK" else logging.WARNING
    logger.log(
        level,
        f"[{frame_id}] Audit #{total_audits}: atomic_delta="
        f"{atomic_delta if atomic_delta is not None else 'n/a'} "
        f"(atomic_status={atomic_status or 'n/a'}) live_delta={live_delta:.6f} "
        f"live_status={live_status}{' [MAINTENANCE]' if in_maintenance else ''}"
        f"{f' [PUBLIC-ONLY: public BREACH streak {public_streak.get(frame_id, 0)}/{PUBLIC_BREACH_READINGS}]' if public_only else ''}"
        f" ({elapsed_ms}ms)",
    )

    last_cycle_done[frame_id] = time.time()  # §GLOBALSTD 4.1 — the loop-stall deadman's pulse
    await broadcast({"type": "audit_result", "data": result, "frame": frame_id})
    return result



async def _emit_attestation(frame: dict, result: dict, atomic, native_supply,
                            per_user, staked_guard, escrow, shares, solvency,
                            in_maintenance: bool) -> None:
    """§GLOBALSTD Phase 1 — TPSA-1: sign the verdict the cycle just produced.

    Attested tiers only (ATTEST_MODES: prod + legacy). A sandbox that is deliberately
    dark would flood the chain with ERROR attestations; the legacy frames are real ledgers
    with an existing chain, so they keep signing. prev_hash is INSIDE the signed payload, so the
    per-frame chain is itself signed; the lock serializes head-read → sign →
    insert against the baseline admin rail. Never raises into the audit path."""
    if attest_key is None or frame.get("mode") not in ATTEST_MODES:
        return
    fid = frame["id"]
    ns = native_supply or {}

    def _st(x):
        return x.get("status") if isinstance(x, dict) else None

    body = {
        "standard": attest.STANDARD,
        "kind": "audit",
        "auditor_version": AUDITOR_VERSION,
        "frame": fid,
        "currency": frame.get("currency"),
        "ts": result.get("timestamp"),
        "audit_row_id": result.get("id"),
        "as_of_event_seq": (atomic or {}).get("as_of_event_seq"),
        "terms": {
            "issued": atomic["tokens_issued"],
            "destroyed": atomic["tokens_destroyed"],
            "transit_net": atomic["transit_net"],
            "net_supply": atomic["net_supply"],
            "circulating": atomic["total_circulating"],
        } if atomic else None,
        "delta": (atomic or {}).get("atomic_delta"),
        "status": (atomic or {}).get("atomic_status"),
        "live_status": result.get("status"),
        "maintenance": bool(in_maintenance),
        "native": {
            "ok": ns.get("native_supply_ok"),
            "basis": ns.get("recon_basis"),
            "gap": ns.get("recon_gap"),
            "gap_rebased": ns.get("recon_gap_rebased"),
        } if native_supply else None,
        "checks": {
            "per_user": _st(per_user),
            "staked_guard": _st(staked_guard),
            "escrow": _st(escrow),
            "shares": _st(shares),
            "solvency": _st(solvency),
        },
    }
    async with _attest_lock:
        prev = await db.get_attestation_head(fid) or ""
        body["prev_hash"] = prev
        payload = attest.canonical_json(body)
        await db.record_attestation(
            frame=fid, ts=body["ts"] or "", kind="audit", payload=payload,
            digest=attest.AttestKey.digest(payload), prev_hash=prev,
            signature=attest_key.sign(payload), kid=attest_key.kid,
        )
    attest_counts[fid] = attest_counts.get(fid, 0) + 1


async def _audit_loop() -> None:
    """Background loop — run audit every AUDIT_INTERVAL seconds."""
    await asyncio.sleep(5)
    frame_names = ", ".join(f["name"] for f in FRAMES)
    logger.info(
        f"Audit loop started: interval={AUDIT_INTERVAL}s, frames=[{frame_names}], "
        f"atomic_verification={'ON' if asyncpg is not None else 'OFF (asyncpg missing)'}"
    )
    while True:
        try:
            results = await asyncio.gather(
                *[_do_audit(f) for f in FRAMES],
                return_exceptions=True,
            )
            for f, r in zip(FRAMES, results):
                if isinstance(r, Exception):
                    logger.error(f"Audit gather exception for {f['id']}: {r}")
        except Exception as e:
            logger.error(f"Audit loop exception: {e}", exc_info=True)
        await asyncio.sleep(AUDIT_INTERVAL)


# ── Lifespan ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global audit_task, track_task, start_time, total_audits

    start_time = time.time()
    logger.info(f"The Auditor v{AUDITOR_VERSION} starting — {AGENT_NAME} ({len(FRAMES)} frames)")

    await db.init_db()
    await track_record.init_db()
    logger.info("Database initialized")

    # §GLOBALSTD Phase 1 — TPSA-1 signing key (durable on the ./data bind mount).
    global attest_key
    try:
        attest_key = attest.load_or_create(db.DATA_DIR)
        logger.info(
            f"TPSA-1 attestation key ready (kid={attest_key.kid}) — signed chain per prod "
            f"frame, JWKS at /.well-known/auditor-jwks.json"
        )
    except Exception as e:
        attest_key = None
        logger.error(f"TPSA-1 attestation key unavailable — audits continue UNSIGNED: {e}")

    await _load_maintenance()
    logger.info(f"Maintenance state loaded: active={maintenance_state.get('active')}")

    # Restore stats from DB (combined)
    stats = await db.get_stats()
    total_audits = stats["total_audits"]
    for f in FRAMES:
        frame_stats = await db.get_stats(frame=f["id"])
        consecutive_ok[f["id"]] = frame_stats["consecutive_ok"]

    audit_task = asyncio.create_task(_audit_loop())
    logger.info("Audit loop task created")
    # §MEMBERSHIP D1: a SEPARATE task; it reads its carrier every cycle and idles while there is none
    track_task = asyncio.create_task(track_record.run_forever(attest_key, _attest_lock, AUDITOR_VERSION))

    yield

    for task in (audit_task, track_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    for fid, pool in list(_pools.items()) + list(_reg_pools.items()):
        try:
            await pool.close()
        except Exception:
            pass
    logger.info("The Auditor shut down")


# ── App ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="The Auditor",
    description="Supply Invariant Guardian Agent for TheProtocol",
    version=AUDITOR_VERSION,
    lifespan=lifespan,
)


def _require_admin(token: Optional[str]) -> Optional[JSONResponse]:
    """Gate write endpoints. Returns an error response if unauthorized, else None."""
    if not AUDITOR_ADMIN_TOKEN:
        return JSONResponse(
            {"error": "Admin endpoints disabled (AUDITOR_ADMIN_TOKEN unset)"},
            status_code=503,
        )
    if token != AUDITOR_ADMIN_TOKEN:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return None


# ── API Endpoints ───────────────────────────────────────────────────────

@app.get("/health")
async def health():
    frames_status = {}
    for fid, r in latest_results.items():
        if not r:
            frames_status[fid] = None
            continue
        frames_status[fid] = {
            "delta": r.get("delta"),
            "status": r.get("status"),
            "atomic_delta": r.get("atomic_delta"),
            "atomic_status": r.get("atomic_status"),
            "last_audit": r.get("timestamp"),
            "consecutive_ok": consecutive_ok.get(fid, 0),
            "public_only": bool((r.get("extra_data") or {}).get("public_only")),
            "public_breach_streak": public_streak.get(fid, 0),
        }
    return {
        "status": "operational",
        "agent": AGENT_NAME,
        "agent_did": AGENT_DID,
        "version": AUDITOR_VERSION,
        "maintenance": _maintenance_payload(),
        "frames": frames_status,
        "total_audits": total_audits,
        "uptime_seconds": int(time.time() - start_time) if start_time else 0,
    }


@app.get("/api/auditor/modes")
async def api_modes():
    """Available modes + the server's default (the frontend overrides the default
    from the subdomain, but this is the fallback)."""
    return {"modes": MODES, "default": DEFAULT_MODE, "attest": sorted(ATTEST_MODES & set(MODES)),
            # §MTLSHOPS (a): the slot shapes this auditor reads; a slot writer asks here before it writes one
            "slot_shapes": list(SLOT_SHAPES)}


@app.get("/api/auditor/frames")
async def api_frames(mode: Optional[str] = Query(default=None)):
    """Return configured frames, optionally filtered by mode ('prod'|'sandbox'|'legacy')."""
    return [
        {"id": f["id"], "name": f["name"], "mode": f["mode"], "currency": f.get("currency", "AVT"),
         "public_only": bool(f.get("public_only")), "public_read": bool(f.get("public_read"))}
        for f in FRAMES
        if (mode is None or f["mode"] == mode)
    ]


@app.get("/api/auditor/latest")
async def api_latest(mode: Optional[str] = Query(default=None)):
    if not latest_results:
        return JSONResponse({"message": "No audit results yet"}, status_code=404)
    if mode is None:
        return latest_results
    return {fid: r for fid, r in latest_results.items() if FRAME_MODE.get(fid) == mode}


@app.get("/api/auditor/true-supply")
async def api_true_supply(mode: Optional[str] = Query(default=None)):
    """Real mint/burn (typed supply events since the balance-integrity baseline)
    per frame — the honest counterpart to supply_summary's issued/destroyed, which
    post-CQRS-cutover fold in transfer/cross-frame legs and are NOT mint/burn."""
    out = {}
    for f in FRAMES:
        if mode is not None and f["mode"] != mode:
            continue
        r = latest_results.get(f["id"]) or {}
        ex = r.get("extra_data") or {}
        out[f["id"]] = {
            "frame": f["name"],
            "true_minted": ex.get("true_minted"),
            "true_burned": ex.get("true_burned"),
            "true_supply_since": ex.get("true_supply_since"),
            "raw_destroyed_accumulator": ex.get("tokens_destroyed"),
            "circulating": r.get("total_circulating"),
            "atomic_delta": r.get("atomic_delta"),
            "atomic_status": r.get("atomic_status"),
        }
    return out


@app.get("/api/auditor/solvency")
async def api_solvency(mode: Optional[str] = Query(default=None)):
    """Independent FX reserve solvency (I2) per reserve-frame + cross-frame FX pool
    health (TRACKED, never gated). Reserve balances + floors are read by the auditor
    DIRECTLY from each frame's materialized_balances — it does not trust the registry's
    /fx/pool or /cross-frame-audit. Non-FX frames (e.g. Frame B) are simply absent."""
    per_frame: dict = {}
    for f in FRAMES:
        if mode is not None and f["mode"] != mode:
            continue
        r = latest_results.get(f["id"]) or {}
        sol = (r.get("extra_data") or {}).get("solvency")
        if sol:
            per_frame[f["id"]] = {**sol, "frame": f["name"], "mode": f["mode"]}
    pools: dict = {}
    for md in ([mode] if mode else MODES):
        md_frames = {fid: s for fid, s in per_frame.items() if FRAME_MODE.get(fid) == md}
        p = _fx_pool(md_frames)
        if p:
            pools[md] = p
    return {"frames": per_frame, "pool": pools}


# ── AGORA venue share registries (2026-08-27) ──────────────────────────────
# The share query and the pool helper already take {id, reg_dsn}, so a venue needs
# no new machinery — only a source list. Listings are enumerated from the DB, so a
# new stock on a wired venue appears by itself.
_venue_shares_cache: dict = {}

async def _venue_shares() -> dict:
    """Per-venue cap tables for venues that are not frames (the 13 cloud-ops).

    An unreachable venue is reported as an ERROR entry, never dropped: a venue that
    quietly disappears from an audit is indistinguishable from a venue with no
    shares, and only one of those is fine.
    """
    out: dict = {}
    for v in VENUES:
        try:
            sh = await _share_registry(v)
            err = _share_errors.get(v["id"]) or {}
            if sh is None:
                # §OPDIST: the note is what was OBSERVED. A pool that connected and a read that failed is not
                # "unreachable" (the fix is a grant, not a network), and a failure nobody recorded says so.
                if err.get("stage") == "read":
                    status, note = "read_failed", f"the registry DB answered but the holder register read failed: {err['error']}"
                elif err.get("stage") == "pool":
                    status, note = "unreachable", f"no pool to the registry DB could be established: {err['error']}"
                else:
                    status, note = "unreachable", "registry DB not reachable from the auditor (no failure was recorded)"
                out[v["name"]] = {"reachable": False, "reach_status": status,
                                  "status": None, "listings": [], "note": note}
            else:
                # 🔴 `status` is the I-SHARES CONSERVATION VERDICT ('OK' / breached),
                # which the dashboard aggregates. Overwriting it with a reachability
                # word would have shown a false breach on every venue AND hidden a
                # real one. Reachability gets its own key.
                out[v["name"]] = {**sh, "reachable": True, "reach_status": "ok",
                                  "venue": v["name"],
                                  "currency": v.get("currency") or sh.get("currency"),
                                  "frame": v.get("frame") or ""}
                if err.get("stage") == "read":
                    at = (_shares_cache.get(v["id"]) or {}).get("at") or "an earlier read"
                    out[v["name"]].update(reach_status="stale",
                                          note=f"the latest holder register read failed, so this is the reading from {at}: "
                                               f"{err['error']}")
        except Exception as e:  # noqa: BLE001
            out[v["name"]] = {"reachable": False, "reach_status": "error",
                              "status": None, "listings": [], "note": str(e)[:160]}
    _venue_shares_cache.clear()
    _venue_shares_cache.update(out)
    return out


@app.get("/api/auditor/venue-shares")
async def api_venue_shares():
    """Share registries for AGORA venues that are NOT frames (the cloud operators).

    Frames answer at /api/auditor/shares; this is the rest of the federation. Every
    configured venue appears with a status, so an unreachable one is VISIBLE rather
    than missing — the auditor's job is to say what it could not see.
    """
    data = await _venue_shares()
    listings = sum(len(x.get("listings") or []) for x in data.values())
    return {
        "venues": data,
        "venue_count": len(VENUES),
        "reachable": sum(1 for x in data.values() if x.get("reachable")),
        "listings": listings,
    }


@app.get("/api/auditor/shares")
async def api_shares(mode: Optional[str] = Query(default=None)):
    """AGORA share registry per frame — the per-listing cap table (who holds the
    stocks), read by the auditor DIRECTLY from each frame's registry DB. Frames
    without a reg_dsn (or with no listings) are simply absent. The same data also
    rides each audit result's extra_data.shares (this endpoint is the standalone view)."""
    out: dict = {}
    for f in FRAMES:
        if mode is not None and f["mode"] != mode:
            continue
        r = latest_results.get(f["id"]) or {}
        sh = (r.get("extra_data") or {}).get("shares")
        if sh and sh.get("listings"):
            out[f["id"]] = {**sh, "frame": f["name"], "mode": f["mode"], "currency": f.get("currency")}
    return out


@app.get("/api/auditor/history")
async def api_history(
    limit: int = Query(default=200, le=1000),
    frame: Optional[str] = Query(default=None),
    mode: Optional[str] = Query(default=None),
):
    rows = await db.get_history(limit=limit, frame=frame)
    # Mode-scope so the trend chart / audit log below the dashboard reflect only
    # the active environment's frames (prod vs sandbox), matching the supply panel.
    if mode is not None:
        rows = [r for r in rows if FRAME_MODE.get(r.get("frame")) == mode]
    return rows


@app.get("/api/auditor/stats")
async def api_stats(
    frame: Optional[str] = Query(default=None),
    mode: Optional[str] = Query(default=None),
):
    # Mode-scope the headline stats (audits / uptime / max-Δ) to the active
    # environment so they match the frames rendered below them.
    frames_in_mode = [f["id"] for f in FRAMES if f["mode"] == mode] if mode else None
    return await db.get_stats(frame=frame, frames=frames_in_mode)


@app.get("/api/auditor/breaches")
async def api_breaches(
    frame: Optional[str] = Query(default=None),
    kind: Optional[str] = Query(default=None),
):
    return await db.get_breaches(frame=frame, kind=kind)


@app.get("/api/auditor/maintenance")
async def api_get_maintenance():
    """Public read — the banner needs this."""
    return _maintenance_payload()


@app.post("/api/auditor/maintenance")
async def api_set_maintenance(
    request: Request,
    x_auditor_admin: Optional[str] = Header(default=None),
):
    """Toggle/update maintenance mode (reusable, no rebuild). Token-gated."""
    err = _require_admin(x_auditor_admin)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}

    global maintenance_state
    now = datetime.now(timezone.utc).isoformat()
    was_active = bool(maintenance_state.get("active", False))
    active = bool(body.get("active", was_active))

    new_state = {
        "active": active,
        "title": body.get("title", maintenance_state.get("title", MAINTENANCE_SEED_TITLE)),
        "message": body.get("message", maintenance_state.get("message", MAINTENANCE_SEED_MESSAGE)),
        "patch_ref": body.get("patch_ref", maintenance_state.get("patch_ref", MAINTENANCE_SEED_PATCH_REF)),
        # 'since' resets when toggling OFF→ON; preserved while staying ON.
        "since": (maintenance_state.get("since") if (active and was_active) else (now if active else None)),
        "updated_at": now,
    }
    await db.set_meta("maintenance", new_state)
    maintenance_state = new_state
    logger.info(f"Maintenance mode set: active={active} by admin")
    await broadcast({"type": "maintenance", "data": _maintenance_payload()})
    return _maintenance_payload()


@app.post("/api/auditor/admin/reset")
async def api_reset(
    request: Request,
    x_auditor_admin: Optional[str] = Header(default=None),
):
    """Resolve open breach incidents (e.g. clear stale false-positives at cutover)."""
    err = _require_admin(x_auditor_admin)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    frame = body.get("frame")
    closed = await db.resolve_open_breaches(frame=frame)
    logger.info(f"Reset: resolved {closed} open breach incident(s) (frame={frame or 'all'})")
    await broadcast({"type": "reset", "data": {"resolved": closed, "frame": frame}})
    return {"resolved": closed, "frame": frame}


@app.post("/api/auditor/admin/reload-frames")
async def api_reload_frames(x_auditor_admin: Optional[str] = Header(default=None)):
    """§FRAMEKIT P3.1 (2026-09-12) — re-read the extra-frames file (AUDITOR_EXTRA_FRAMES_FILE) and apply it in
    place: a frame wired or unwired by scripts/hetzner_demo/sidecars.py reaches this auditor without a recreate
    (a recreate re-audits every tier at once). Pools of removed or changed frames are closed; the audit loop
    picks the new list up on its next cycle. Answers what changed and which carrier it read."""
    err = _require_admin(x_auditor_admin)
    if err:
        return err
    from . import config as _cfg
    extra, source = _cfg.read_extra_frames()
    delta = _cfg.apply_extra_frames(extra)
    for fid in delta["removed"] + delta["replaced"]:
        for pools in (_pools, _reg_pools, _teg_pools):
            pool = pools.pop(fid, None)
            if pool is not None:
                try:
                    # terminate, never close(): close() waits for an in-flight audit of the very frame being removed
                    # to release its connection — a teardown's unwire timed out on it and fell back to a recreate
                    pool.terminate()
                except Exception:  # noqa: BLE001
                    pass
        if fid in delta["removed"]:
            latest_results.pop(fid, None)
    logger.info(f"reload-frames from {source}: added={delta['added']} removed={delta['removed']} replaced={delta['replaced']} "
                f"frames={delta['frames']}")
    return {"source": source, **delta}


@app.post("/api/auditor/admin/reload-venues")
async def api_reload_venues(x_auditor_admin: Optional[str] = Header(default=None)):
    """§OPDIST (2026-09-16) — re-read the venues carrier (venues.json beside the extra-frames file, else
    VENUE_REG_DSNS_JSON) and apply it in place: an operator's share register is wired or unwired without a recreate.
    Registry pools of removed or changed venues are terminated; the next /venue-shares read uses the new list.

    ⚠ Deliberately NOT reload-frames' behaviour on a bad file: an unparsable carrier applies NOTHING and answers 422.
    Frames apply an empty list there; for venues that would make every share register vanish from the audit at once,
    and a venue that silently disappears is the exact blindspot the venue block exists to close."""
    err = _require_admin(x_auditor_admin)
    if err:
        return err
    from . import config as _cfg
    mapping, source = _cfg.read_venues()
    if source.endswith("(unparsable)"):
        return JSONResponse({"error": f"{source}: nothing applied; the venues audited stay as they were",
                             "source": source, "venues": [v["name"] for v in VENUES]}, status_code=422)
    delta = _cfg.apply_venues(mapping)
    for vid in delta["removed"] + delta["replaced"]:
        pool = _reg_pools.pop(vid, None)
        if pool is not None:
            try:
                pool.terminate()   # terminate, never close(): see reload-frames
            except Exception:  # noqa: BLE001
                pass
        # A changed entry is read afresh: neither the old entry's reading nor its recorded failure speaks for it.
        _shares_cache.pop(vid, None)
        _share_errors.pop(vid, None)
        if vid in delta["removed"]:
            _venue_shares_cache.pop(vid[len("venue:"):], None)
    logger.info(f"reload-venues from {source}: added={delta['added']} removed={delta['removed']} "
                f"replaced={delta['replaced']} venues={delta['venues']}")
    return {"source": source, **delta}


@app.post("/api/auditor/admin/rebaseline-transit")
async def api_rebaseline_transit(
    request: Request,
    x_auditor_admin: Optional[str] = Header(default=None),
):
    """Re-baseline transit_net DRIFT monitoring for a frame (or all). Sets the baseline to
    the frame's CURRENT transit_net so drift restarts at 0 — use after a known cleanup /
    re-baseline so future stranding (drift below −TRANSIT_DRIFT_ALERT) is immediately
    visible. Does NOT touch the ledger (transit_net stays the truthful escrow residue);
    this only moves the monitoring zero-point. Body: {"frame": "frame-c"} | {} for all."""
    err = _require_admin(x_auditor_admin)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    want = body.get("frame")
    ref = (body.get("ref") or "").strip()
    done = []
    for f in FRAMES:
        fid = f["id"]
        if want and fid != want:
            continue
        cur = (latest_results.get(fid) or {}).get("extra_data", {}).get("composition") or {}
        transit = cur.get("transit_net")
        if transit is None:
            continue
        old_baseline = cur.get("transit_baseline")
        old_drift = cur.get("transit_drift")
        now_iso = datetime.now(timezone.utc).isoformat()
        await db.set_meta(f"transit_baseline:{fid}", {
            "baseline": float(transit),
            "set_at": now_iso,
            "auto": False,
        })
        # §GLOBALSTD (2026-08-22): the act itself is attested — same chain-of-custody
        # the NATIVEBASE rail has. A monitoring zero-point move is a signed, chained
        # event with its old value and its reason on the record, not a silent meta write.
        att_id = None
        if attest_key is not None and f.get("mode") in ATTEST_MODES:
            async with _attest_lock:
                prev = await db.get_attestation_head(fid) or ""
                b = {
                    "standard": attest.STANDARD, "kind": "transit_rebaselined",
                    "auditor_version": AUDITOR_VERSION, "frame": fid, "ts": now_iso,
                    "old_baseline": old_baseline, "old_drift": old_drift,
                    "new_baseline": float(transit), "ref": ref or None,
                    "rail": "admin/rebaseline-transit", "prev_hash": prev,
                }
                payload = attest.canonical_json(b)
                att_id = await db.record_attestation(
                    frame=fid, ts=now_iso, kind="transit_rebaselined", payload=payload,
                    digest=attest.AttestKey.digest(payload), prev_hash=prev,
                    signature=attest_key.sign(payload), kid=attest_key.kid,
                )
            attest_counts[fid] = attest_counts.get(fid, 0) + 1
        done.append({"frame": fid, "baseline": float(transit),
                     "old_baseline": old_baseline, "old_drift": old_drift,
                     "attestation_id": att_id})
        logger.warning(
            f"[{fid}] transit_net baseline MANUALLY re-set {old_baseline} -> {transit:.2f} "
            f"(old drift {old_drift}) by admin rail; ref={ref!r} attestation_id={att_id}"
        )
    return {"rebaselined": done}


# ── §GLOBALSTD Phase 1: TPSA-1 attestations + the baseline write rail ───

@app.get("/.well-known/auditor-jwks.json")
async def api_auditor_jwks():
    """Public verification keys for TPSA-1 attestations (Ed25519, JWK OKP)."""
    if attest_key is None:
        return JSONResponse({"keys": []}, status_code=503)
    keys = [attest_key.jwk]
    seen = {attest_key.kid}
    for jwk in attest.retired_jwks(db.DATA_DIR):
        if jwk["kid"] not in seen:
            keys.append(jwk)
            seen.add(jwk["kid"])
    return {"keys": keys}


# Literal route registered BEFORE /{att_id} — FastAPI matches by registration
# order, not path specificity (§NOTIFV2 gotcha).
@app.get("/api/auditor/attestations/head")
async def api_attestation_head(frame: str = Query(...)):
    """Chain head (latest attestation digest) for a frame — the anchoring target."""
    row = await db.get_attestation_head_row(frame)
    if not row:
        return JSONResponse({"error": f"no attestations for '{frame}'"}, status_code=404)
    return row


@app.get("/api/auditor/attestations/{att_id}")
async def api_attestation_one(att_id: int):
    row = await db.get_attestation(att_id)
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    return row


@app.get("/api/auditor/attestations")
async def api_attestations(
    frame: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    before_id: Optional[int] = Query(default=None),
):
    """TPSA-1 attestation list, newest first. `payload` carries the EXACT signed
    bytes: verify sha256(payload) == digest and Ed25519(signature, payload)
    against /.well-known/auditor-jwks.json — no re-canonicalization needed."""
    rows = await db.get_attestations(frame=frame, limit=limit, before_id=before_id)
    return {
        "attestations": rows,
        "standard": attest.STANDARD,
        "kid": attest_key.kid if attest_key else None,
    }


# ── §MEMBERSHIP phase D1: the registry track record ──────────────────────
# Declared here, above the SPA catch-all (GET /{full_path:path}), which would otherwise answer these paths with the page.

@app.get("/api/auditor/track-record")
async def api_track_record():
    """The latest signed track record per registry, with the formula, its weights and what is never an input.
    Each record's attestation sits in the chain `track_record:<registry>` (/api/auditor/attestations?frame=...)."""
    return await track_record.latest_view()


@app.get("/api/auditor/track-record/{registry}")
async def api_track_record_history(registry: str, days: int = Query(default=30, ge=1, le=400)):
    return await track_record.history_view(registry, days)


@app.post("/api/auditor/admin/track-record/compute")
async def api_track_record_compute(x_auditor_admin: Optional[str] = Header(default=None)):
    """Compute and sign a record for every configured registry NOW (the daily run does this after its hour)."""
    err = _require_admin(x_auditor_admin)
    if err:
        return err
    cfg = track_record.load_carrier()
    if not cfg.get("registries"):
        return JSONResponse({"error": "no carrier: the track record is off on this auditor",
                             "carrier": str(track_record.carrier_path())}, status_code=409)
    recs = [await track_record.compute_and_record(reg, attest_key, _attest_lock, AUDITOR_VERSION)
            for reg in cfg["registries"]]
    return {"computed": [{"registry": r["registry"], "score": r["score"], "provisional": r["provisional"],
                          "observed_days": r["observed_days"], "attestation_id": r.get("attestation_id")} for r in recs]}


@app.post("/api/auditor/admin/set-native-baseline")
async def api_set_native_baseline(
    request: Request,
    x_auditor_admin: Optional[str] = Header(default=None),
):
    """§GLOBALSTD Phase 1.4 — the audited write rail for the NATIVEBASE file.
    Writes /app/data/native_supply_baseline.json atomically AND emits a signed
    provenance attestation into the frame's chain, so a baseline change is a
    signed, chained event instead of a hand-edit. Body: {"frame": "frame-c",
    "baseline": <number | null to remove>, "set_at"?: iso8601, "ref": "why"}.
    The audit loop picks the change up on its next cycle (and re-logs it)."""
    err = _require_admin(x_auditor_admin)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON body required"}, status_code=422)
    fid = body.get("frame")
    if fid not in {f["id"] for f in FRAMES if f.get("mode") in ATTEST_MODES}:
        return JSONResponse({"error": f"unknown attested frame {fid!r}"}, status_code=422)
    ref = (body.get("ref") or "").strip()
    if not ref:
        return JSONResponse({"error": "'ref' (provenance note) is required"}, status_code=422)
    if "baseline" not in body:
        return JSONResponse({"error": "'baseline' required (number, or null to remove)"}, status_code=422)
    raw_v = body.get("baseline")
    set_at = body.get("set_at") or datetime.now(timezone.utc).isoformat()
    path = "/app/data/native_supply_baseline.json"
    try:
        with open(path) as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        doc = {"frames": {}}
    except Exception as e:
        return JSONResponse(
            {"error": f"existing baseline file unreadable ({e!r}) — refusing to overwrite blind"},
            status_code=409,
        )
    doc.setdefault("frames", {})
    if raw_v is None:
        if doc["frames"].pop(fid, None) is None:
            return JSONResponse({"error": f"no baseline entry for {fid!r} to remove"}, status_code=404)
        kind, entry = "baseline_removed", None
    else:
        try:
            v = float(raw_v)
        except (TypeError, ValueError):
            return JSONResponse({"error": f"baseline {raw_v!r} is not a number"}, status_code=422)
        if not (v > 0) or v == float("inf") or v != v:
            return JSONResponse({"error": f"baseline {v!r} fails sanity (finite, > 0)"}, status_code=422)
        entry = {"baseline": v, "set_at": set_at, "ref": ref}
        doc["frames"][fid] = entry
        kind = "baseline_set"
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(doc, fh, indent=2)
    os.replace(tmp, path)
    _NATIVE_BASELINE_STATE.pop(fid, None)  # next cycle re-logs the new state loudly
    att_id = None
    if attest_key is not None:
        async with _attest_lock:
            prev = await db.get_attestation_head(fid) or ""
            b = {
                "standard": attest.STANDARD, "kind": kind,
                "auditor_version": AUDITOR_VERSION, "frame": fid,
                "ts": datetime.now(timezone.utc).isoformat(),
                "entry": entry, "ref": ref,
                "rail": "admin/set-native-baseline", "prev_hash": prev,
            }
            payload = attest.canonical_json(b)
            att_id = await db.record_attestation(
                frame=fid, ts=b["ts"], kind=kind, payload=payload,
                digest=attest.AttestKey.digest(payload), prev_hash=prev,
                signature=attest_key.sign(payload), kid=attest_key.kid,
            )
        attest_counts[fid] = attest_counts.get(fid, 0) + 1
    logger.warning(
        f"[{fid}] NATIVEBASE {kind} via admin rail: {entry} ref={ref!r} attestation_id={att_id}"
    )
    await broadcast({"type": "native_baseline", "data": {"frame": fid, "kind": kind, "entry": entry}})
    return {"ok": True, "frame": fid, "kind": kind, "entry": entry, "attestation_id": att_id}


@app.get("/metrics")
async def metrics():
    """Prometheus-compatible metrics with per-frame labels."""
    lines = [
        "# HELP auditor_delta Live-read supply invariant delta (HTTP /supply-audit)",
        "# TYPE auditor_delta gauge",
    ]
    for f in FRAMES:
        if f.get("public_only"):
            continue   # §MTLSHOPS (a): published as auditor_public_delta
        fid = f["id"]
        r = latest_results.get(fid)
        delta = r.get("delta") if r else 0.0
        lines.append(f'auditor_delta{{frame="{fid}"}} {delta if delta is not None else 0.0}')

    lines.extend([
        "# HELP auditor_atomic_delta Atomic (single-statement) supply invariant delta — TRUTH",
        "# TYPE auditor_atomic_delta gauge",
    ])
    for f in FRAMES:
        fid = f["id"]
        r = latest_results.get(fid)
        ad = r.get("atomic_delta") if r else None
        if ad is not None:
            lines.append(f'auditor_atomic_delta{{frame="{fid}"}} {ad}')

    lines.extend([
        "# HELP auditor_status Truth supply invariant status (1=OK, 0=BREACH/ERROR)",
        "# TYPE auditor_status gauge",
    ])
    for f in FRAMES:
        if f.get("public_only"):
            continue   # §MTLSHOPS (a): a public reading is not the truth status; published as auditor_public_status
        fid = f["id"]
        r = latest_results.get(fid)
        truth = (r.get("atomic_status") or r.get("status")) if r else None
        status_val = 1 if truth == "OK" else 0
        lines.append(f'auditor_status{{frame="{fid}"}} {status_val}')

    lines.extend([
        "# HELP auditor_consecutive_ok Consecutive OK audits",
        "# TYPE auditor_consecutive_ok gauge",
    ])
    for f in FRAMES:
        if f.get("public_only"):
            continue
        fid = f["id"]
        lines.append(f'auditor_consecutive_ok{{frame="{fid}"}} {consecutive_ok.get(fid, 0)}')

    # §MTLSHOPS (a) (2026-09-15): a public-only frame's reading of its public supply audit, never under the truth names above
    _pub = [f for f in FRAMES if f.get("public_only")]
    if _pub:
        lines.extend([
            "# HELP auditor_public_status Public-only frame: its public supply audit (1=OK, 0=otherwise); not the atomic check",
            "# TYPE auditor_public_status gauge",
            "# HELP auditor_public_delta Public-only frame: delta from its public supply audit (two queries; transients happen)",
            "# TYPE auditor_public_delta gauge",
            "# HELP auditor_public_breach_streak Public-only frame: consecutive BREACH readings of its public supply audit",
            "# TYPE auditor_public_breach_streak gauge",
        ])
        for f in _pub:
            fid = f["id"]
            r = latest_results.get(fid) or {}
            d = r.get("delta")
            lines.append(f'auditor_public_status{{frame="{fid}"}} {1 if r.get("status") == "OK" else 0}')
            lines.append(f'auditor_public_delta{{frame="{fid}"}} {d if d is not None else 0.0}')
            lines.append(f'auditor_public_breach_streak{{frame="{fid}"}} {public_streak.get(fid, 0)}')

    # ── FX reserve solvency (I2) — independent witness ──────────────────
    _SOL = {"SOLVENT": 1, "LOW": 0.5, "BREACH": 0}
    lines.extend([
        "# HELP auditor_fx_reserve_balance @fx_reserve balance per reserve-frame",
        "# TYPE auditor_fx_reserve_balance gauge",
    ])
    for f in FRAMES:
        r = latest_results.get(f["id"]) or {}
        sol = (r.get("extra_data") or {}).get("solvency")
        if sol:
            lines.append(f'auditor_fx_reserve_balance{{frame="{f["id"]}",currency="{sol.get("currency","")}"}} {sol.get("reserve_balance",0)}')
    lines.extend([
        "# HELP auditor_fx_reserve_floor Configured reserve floor per reserve-frame",
        "# TYPE auditor_fx_reserve_floor gauge",
    ])
    for f in FRAMES:
        r = latest_results.get(f["id"]) or {}
        sol = (r.get("extra_data") or {}).get("solvency")
        if sol:
            lines.append(f'auditor_fx_reserve_floor{{frame="{f["id"]}",currency="{sol.get("currency","")}"}} {sol.get("floor",0)}')
    lines.extend([
        "# HELP auditor_solvency_status Reserve solvency (1=SOLVENT, 0.5=LOW, 0=BREACH)",
        "# TYPE auditor_solvency_status gauge",
    ])
    for f in FRAMES:
        r = latest_results.get(f["id"]) or {}
        sol = (r.get("extra_data") or {}).get("solvency")
        if sol:
            lines.append(f'auditor_solvency_status{{frame="{f["id"]}"}} {_SOL.get(sol.get("status"), 0)}')
    # Cross-frame FX pool (TRACKED, never gated).
    _pool_lines_added = False
    for md in MODES:
        pf = {}
        for f in FRAMES:
            if f["mode"] != md:
                continue
            sol = (latest_results.get(f["id"]) or {}).get("extra_data", {})
            sol = sol.get("solvency") if isinstance(sol, dict) else None
            if sol:
                pf[f["id"]] = sol
        p = _fx_pool(pf)
        if not p:
            continue
        if not _pool_lines_added:
            lines.extend([
                "# HELP auditor_fx_pool_spot Cross-frame FX pool spot (AVT per BVT) — tracked",
                "# TYPE auditor_fx_pool_spot gauge",
                "# HELP auditor_fx_pool_k Cross-frame FX pool constant product x*y — tracked",
                "# TYPE auditor_fx_pool_k gauge",
                "# HELP auditor_fx_pool_mtm Cross-frame FX pool mark-to-market (AVT) — tracked",
                "# TYPE auditor_fx_pool_mtm gauge",
            ])
            _pool_lines_added = True
        lines.append(f'auditor_fx_pool_spot{{mode="{md}"}} {p["spot_avt_per_bvt"]}')
        lines.append(f'auditor_fx_pool_k{{mode="{md}"}} {p["k"]}')
        lines.append(f'auditor_fx_pool_mtm{{mode="{md}"}} {p["mtm_avt"]}')

    # ── Per-user conservation (I3) + transit drift — the overnight watchdogs ──
    lines.extend([
        "# HELP auditor_per_user_status Per-user conservation I3 (1=OK, 0=BREACH)",
        "# TYPE auditor_per_user_status gauge",
        "# HELP auditor_per_user_negative_agents Agents with a negative liquid/locked balance",
        "# TYPE auditor_per_user_negative_agents gauge",
        "# HELP auditor_per_user_negative_total Sum of negative balances (absolute)",
        "# TYPE auditor_per_user_negative_total gauge",
        "# HELP auditor_per_user_behind_agents Negative projections whose balance changes the TEG still holds (behind, not a breach)",
        "# TYPE auditor_per_user_behind_agents gauge",
        "# HELP auditor_transit_drift transit_net drift vs the post-cleanup baseline (negative = stranding)",
        "# TYPE auditor_transit_drift gauge",
        "# HELP auditor_escrow_negative_clamps_24h NegativeEscrowLockClamped events in 24h (F1-class recurrence)",
        "# TYPE auditor_escrow_negative_clamps_24h gauge",
    ])
    for f in FRAMES:
        fid = f["id"]
        r = latest_results.get(fid) or {}
        x = r.get("extra_data") or {}
        pu = x.get("per_user")
        if pu:
            lines.append(f'auditor_per_user_status{{frame="{fid}"}} {1 if pu.get("status") == "OK" else 0}')
            lines.append(f'auditor_per_user_negative_agents{{frame="{fid}"}} {pu.get("negative_agents", 0)}')
            lines.append(f'auditor_per_user_negative_total{{frame="{fid}"}} {pu.get("negative_total", 0)}')
            lines.append(f'auditor_per_user_behind_agents{{frame="{fid}"}} {pu.get("behind_agents", 0)}')
            lines.append(f'auditor_escrow_negative_clamps_24h{{frame="{fid}"}} {pu.get("escrow_negative_clamps_24h", 0)}')
        comp = x.get("composition")
        if comp and comp.get("transit_drift") is not None:
            lines.append(f'auditor_transit_drift{{frame="{fid}"}} {comp["transit_drift"]}')

    # ── I-Shares: AGORA share-registry conservation + per-listing price ─────
    lines.extend([
        "# HELP auditor_shares_status I-Shares conservation per frame (1=OK, 0=BREACH)",
        "# TYPE auditor_shares_status gauge",
        "# HELP auditor_shares_listings Listed stocks per frame",
        "# TYPE auditor_shares_listings gauge",
        "# HELP auditor_shares_breached Listings violating share conservation",
        "# TYPE auditor_shares_breached gauge",
        "# HELP auditor_share_price Last trade price per listing (listing currency)",
        "# TYPE auditor_share_price gauge",
        "# HELP auditor_share_holders Holder count per listing",
        "# TYPE auditor_share_holders gauge",
    ])
    for f in FRAMES:
        fid = f["id"]
        x = (latest_results.get(fid) or {}).get("extra_data", {})
        sh = x.get("shares") if isinstance(x, dict) else None
        if not sh:
            continue
        lines.append(f'auditor_shares_status{{frame="{fid}"}} {1 if sh.get("status") == "OK" else 0}')
        lines.append(f'auditor_shares_listings{{frame="{fid}"}} {sh.get("listing_count", 0)}')
        lines.append(f'auditor_shares_breached{{frame="{fid}"}} {sh.get("breached_count", 0)}')
        for l in (sh.get("listings") or []):
            sym = l.get("symbol", "?"); ccy = l.get("currency", "")
            if l.get("price") is not None:
                lines.append(f'auditor_share_price{{frame="{fid}",symbol="{sym}",currency="{ccy}"}} {l["price"]}')
            lines.append(f'auditor_share_holders{{frame="{fid}",symbol="{sym}"}} {l.get("holders", 0)}')

    # ── I-X3: AGORA escrow conservation — the AUTHORITATIVE refutation of the registry's
    # racy per-worker agora_invariant_delta gauge. Confirmed delta + the legitimate
    # in-flight funding window. ERROR/absent cycles are omitted (nothing to refute with).
    lines.extend([
        "# HELP auditor_escrow_status AGORA escrow invariant I-X3 (1=OK, 0=BREACH; ERROR/absent omitted)",
        "# TYPE auditor_escrow_status gauge",
        "# HELP auditor_escrow_delta AGORA escrow actual−expected (CONFIRMED; escrow currency)",
        "# TYPE auditor_escrow_delta gauge",
        "# HELP auditor_escrow_funding_in_transition Buy orders mid-'funding' (the legitimate I-X3 transient)",
        "# TYPE auditor_escrow_funding_in_transition gauge",
    ])
    for f in FRAMES:
        fid = f["id"]
        x = (latest_results.get(fid) or {}).get("extra_data", {})
        esc = x.get("escrow") if isinstance(x, dict) else None
        if not esc or esc.get("status") not in ("OK", "BREACH"):
            continue  # not equipped / ERROR → omit (no authoritative value this cycle)
        lines.append(f'auditor_escrow_status{{frame="{fid}"}} {1 if esc.get("status") == "OK" else 0}')
        lines.append(f'auditor_escrow_delta{{frame="{fid}"}} {esc.get("delta", 0)}')
        lines.append(f'auditor_escrow_funding_in_transition{{frame="{fid}"}} {esc.get("funding_n", 0)}')

    lines.extend([
        "# HELP auditor_maintenance Maintenance mode active (1=yes, 0=no)",
        "# TYPE auditor_maintenance gauge",
        f'auditor_maintenance {1 if maintenance_state.get("active") else 0}',
    ])

    # ── §GLOBALSTD 4.1: loop-stall deadman. `up` proves the HTTP server answers;
    # THIS proves audit cycles ADVANCE — a wedged loop shows here while up==1.
    lines.extend([
        "# HELP auditor_last_cycle_age_seconds Seconds since the frame's audit cycle last completed",
        "# TYPE auditor_last_cycle_age_seconds gauge",
    ])
    _now_m = time.time()
    for f in FRAMES:
        _t = last_cycle_done.get(f["id"])
        if _t is not None:
            lines.append(f'auditor_last_cycle_age_seconds{{frame="{f["id"]}"}} {_now_m - _t:.1f}')
    lines.extend([
        "# HELP auditor_attestations_emitted_total TPSA-1 attestations emitted since process start",
        "# TYPE auditor_attestations_emitted_total counter",
    ])
    for f in FRAMES:
        if f.get("mode") in ATTEST_MODES:
            lines.append(f'auditor_attestations_emitted_total{{frame="{f["id"]}"}} {attest_counts.get(f["id"], 0)}')

    stats = await db.get_stats()
    lines.extend([
        "# HELP auditor_total_audits Total number of audits performed",
        "# TYPE auditor_total_audits counter",
        f'auditor_total_audits {stats["total_audits"]}',
        "# HELP auditor_uptime_pct Uptime percentage (truth-based)",
        "# TYPE auditor_uptime_pct gauge",
    ])
    if stats["uptime_pct"] is not None:   # §MTLSHOPS (a): None means only public readings, so uptime is not measured
        lines.append(f'auditor_uptime_pct {stats["uptime_pct"]}')
    lines.append("")
    return PlainTextResponse("\n".join(lines), media_type="text/plain; version=0.0.4")


# ── WebSocket ───────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    logger.info(f"WebSocket client connected ({len(ws_clients)} total)")

    welcome = {
        "type": "connected",
        "agent": AGENT_NAME,
        "version": AUDITOR_VERSION,
        "audit_interval": AUDIT_INTERVAL,
        "maintenance": _maintenance_payload(),
        "frames": [{"id": f["id"], "name": f["name"], "mode": f["mode"], "currency": f.get("currency", "AVT")} for f in FRAMES],
        "latest": latest_results,
    }
    try:
        await ws.send_text(json.dumps(welcome))
    except Exception:
        ws_clients.discard(ws)
        return

    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        ws_clients.discard(ws)
        logger.info(f"WebSocket client disconnected ({len(ws_clients)} total)")


# ── Static files (frontend) ────────────────────────────────────────────

@app.get("/")
async def serve_root():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text())
    return HTMLResponse(
        "<html><body style='background:#020a06;color:#00c853;font-family:monospace;padding:40px'>"
        "<h1>The Auditor</h1><p>Frontend not built yet. Run: cd frontend-src && npm run build</p>"
        "</body></html>"
    )


import os

if FRONTEND_DIR.exists() and (FRONTEND_DIR / "assets").exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIR / "assets")),
        name="assets",
    )


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    static_path = FRONTEND_DIR / full_path
    if static_path.exists() and static_path.is_file():
        content = static_path.read_text()
        media = "text/html"
        if full_path.endswith(".js"):
            media = "application/javascript"
        elif full_path.endswith(".css"):
            media = "text/css"
        elif full_path.endswith(".svg"):
            media = "image/svg+xml"
        return PlainTextResponse(content, media_type=media)
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text())
    return HTMLResponse("Not found", status_code=404)
