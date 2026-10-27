"""
EigenTrust++ Engine — Phase 2

Computes global trust vectors from the local trust matrix.
Runs once per epoch (default: every hour via eigentrust_worker).

Algorithm:
  1. Load local_trust_scores sparse matrix
  2. Row-normalize (c_ij = max(s_ij,0) / Σ max)
  3. EigenTrust++ similarity activation (cosine similarity cutoff)
  4. Power iteration with pre-trust anchor (α=0.15)
  5. MeritRank epoch decay (0.95 carry-over)
  6. Volume weighting (volume^0.3)
  7. Write GlobalTrustVector rows (upsert)
  8. Project to Agent.reputation_score = int(global_trust × 1000)
  9. Emit ReputationChanged for changed agents
"""
import json
import math
import os
import uuid
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func

from ..es_ssl_helper import get_httpx_verify

logger = logging.getLogger(__name__)

# Algorithm constants — match plan (Section 13 deviation log)
ALPHA = 0.15               # Pre-trust weight (spec=0.10, we use 0.15 for small pool)
SIMILARITY_THRESHOLD = 0.3 # Cosine similarity below this → sever trust propagation
VOLUME_WEIGHT_EXP = 0.3    # Volume weighting exponent
# MeritRank carry-over per epoch. 0.95 with hourly epochs means new evidence enters at 5 %/epoch:
# a score is ~70 % of the way to its true value after 24 h and ~91 % after 48 h. Env-tunable since
# 2026-09-10 because the right value is a judgement about how fast reputation should react, not a
# constant; the DEFAULT IS UNCHANGED so this edit is byte-inert until someone sets the variable.
EPOCH_DECAY = float(os.environ.get("EIGENTRUST_EPOCH_DECAY", "0.95"))
# How the [0,1] trust vector becomes the published integer `Agent.reputation_score`.
#   linear (default, unchanged): int(t * 1000)
#   log:                         rank-preserving across orders of magnitude
# 🔴 MEASURED on registry-a 2026-09-10, 4,050 agents: the vector spans 7.1 ORDERS OF MAGNITUDE
# (1.0 down to 7.55e-08). A linear x1000 integer can represent only the top three decades, so it
# produced 21 distinct scores and put 4,010 of 4,050 agents at exactly 0 — and the 40 that scored
# above 0 were the 40 simulation agents. The ranking is computed correctly and then destroyed on
# the way into the column every surface reads. Under `log` the same vector yields 62 distinct
# scores with 1 agent at 0. Left OFF by default: it changes every published number on the node.
PROJECTION_MODE = os.environ.get("EIGENTRUST_PROJECTION", "linear").strip().lower()
MAX_ITERATIONS = 100       # Power iteration safety bound
CONVERGENCE_EPSILON = 1e-6  # L1 norm convergence threshold


def _project(gt_val: float, log_floor: float) -> int:
    """Map a [0,1] trust value onto the published 0-1000 integer.

    linear: the original `int(t * 1000)` — kept byte-identical as the default.
    log:    position within the observed decades, so an ordering that spans many orders of
            magnitude survives the trip into an Integer column. A zero or a value at the floor
            still yields 0; only the spacing changes.
    """
    if PROJECTION_MODE != "log" or gt_val <= 0.0 or log_floor <= 0.0 or gt_val <= log_floor:
        return max(0, min(1000, int(gt_val * 1000)))
    decades = math.log10(1.0 / log_floor)
    if decades <= 0:
        return max(0, min(1000, int(gt_val * 1000)))
    return max(0, min(1000, int(round(1000.0 * (1.0 - math.log10(gt_val / 1.0) / -decades)))))


async def run_epoch(db: AsyncSession) -> dict:
    """
    Full EigenTrust++ epoch computation.

    Returns dict: {
        epoch, agents_computed, computation_time_ms, iterations, converged
    }
    """
    import numpy as np
    from scipy.sparse import csr_matrix, lil_matrix
    from ..models import LocalTrustScore, GlobalTrustVector, Agent
    from ..event_emitter import get_event_emitter

    t_start = time.monotonic()

    # --- Step 0: Check if backfill needed ---
    count_result = await db.execute(
        select(func.count()).select_from(LocalTrustScore)
    )
    lt_count = count_result.scalar()
    if lt_count == 0:
        from ..services.local_trust_updater import backfill_from_event_store
        logger.info("LocalTrustScore table empty — running EventStore backfill first")
        created = await backfill_from_event_store(db)
        await db.commit()
        logger.info(f"Backfill done: {created} pairs. Re-reading...")

    # --- Step 1: Load local trust matrix ---
    lts_result = await db.execute(
        select(LocalTrustScore)
    )
    rows = lts_result.scalars().all()

    # Collect all unique DIDs (exclude self-loops for matrix — those are similarity signals)
    bilateral_rows = [r for r in rows if r.from_did != r.to_did]
    all_dids = sorted(set(
        did for r in bilateral_rows for did in (r.from_did, r.to_did)
    ))

    if not all_dids:
        logger.warning("No bilateral trust pairs found — skipping epoch computation")
        return {"epoch": 0, "agents_computed": 0, "computation_time_ms": 0,
                "iterations": 0, "converged": False}

    n = len(all_dids)
    did_to_idx = {did: i for i, did in enumerate(all_dids)}

    # Build raw S matrix (local trust values, clamped to non-negative)
    S = lil_matrix((n, n), dtype=float)
    volume_map = {}  # idx → total volume transacted
    for r in bilateral_rows:
        i = did_to_idx[r.from_did]
        j = did_to_idx[r.to_did]
        S[i, j] = max(0.0, r.local_trust)
        volume_map[i] = volume_map.get(i, 0) + r.tx_volume

    S = S.tocsr()

    # --- Step 2: Row-normalize ---
    # c_ij = max(s_ij,0) / Σ_j max(s_ij,0)
    row_sums = np.array(S.sum(axis=1)).flatten()
    # Identify zero-sum rows (agents with no positive outgoing trust)
    zero_rows = np.where(row_sums == 0)[0]

    C = lil_matrix((n, n), dtype=float)
    for i in range(n):
        if row_sums[i] > 0:
            for j_idx in range(S.indptr[i], S.indptr[i + 1]):
                j = S.indices[j_idx]
                C[i, j] = S.data[j_idx] / row_sums[i]
        # zero-sum rows handled by pre-trust vector below
    C = C.tocsr()

    # --- Step 3: Similarity activation ---
    # Build per-agent feature vectors: [transfer_count, unique_peers, avg_volume]
    # Agents with cosine similarity < threshold lose trust propagation between them
    # For our 10-agent pool this is lightweight; at 100K agents, skip for non-zero pairs only
    self_loop_counts = {}
    for r in rows:
        if r.from_did == r.to_did:
            idx = did_to_idx.get(r.from_did)
            if idx is not None:
                self_loop_counts[idx] = r.satisfactory

    features = np.zeros((n, 3), dtype=float)
    for r in bilateral_rows:
        i = did_to_idx[r.from_did]
        features[i, 0] += 1  # transfer count
        features[i, 1] += 1  # unique peers (approximate; we sum, then will be set correctly)
        features[i, 2] += float(r.tx_volume)   # numpy float array; the column is NUMERIC since mig 0171
    # Normalize features for cosine similarity
    feat_norms = np.linalg.norm(features, axis=1, keepdims=True)
    feat_norms[feat_norms == 0] = 1.0
    features_norm = features / feat_norms

    # Apply similarity cutoff: if cosine(i, j) < threshold, zero out C[i,j]
    C_masked = lil_matrix(C)
    for i in range(n):
        for j_ptr in range(C.indptr[i], C.indptr[i + 1]):
            j = C.indices[j_ptr]
            sim = float(np.dot(features_norm[i], features_norm[j]))
            if sim < SIMILARITY_THRESHOLD:
                C_masked[i, j] = 0.0
    C = C_masked.tocsr()

    # Re-normalize after masking
    row_sums_masked = np.array(C.sum(axis=1)).flatten()
    C_renorm = lil_matrix((n, n), dtype=float)
    for i in range(n):
        if row_sums_masked[i] > 0:
            for j_ptr in range(C.indptr[i], C.indptr[i + 1]):
                j = C.indices[j_ptr]
                C_renorm[i, j] = C.data[j_ptr] / row_sums_masked[i]
    C = C_renorm.tocsr()

    # --- Step 4: Pre-trust vector ---
    # All agents are treated equally in the pre-trust vector (uniform)
    p = np.ones(n, dtype=float) / n

    # --- Step 5: Load previous epoch scores for decay ---
    all_prev = (await db.execute(select(GlobalTrustVector))).scalars().all()
    prev_vectors = {r.agent_did: r.global_trust for r in all_prev}
    prev_epoch = max((r.epoch for r in all_prev), default=0)

    _NEW_AGENT_SEED = 1.0 / n   # an agent the previous epoch never saw starts uniform, not at zero
    t_prev = np.array([prev_vectors.get(did, _NEW_AGENT_SEED) for did in all_dids])

    # --- Step 6: Power iteration ---
    # t^(k+1) = (1-α) * C^T * t^(k) + α * p
    t = t_prev.copy()
    converged = False
    iterations = 0
    C_T = C.T.tocsr()

    for iteration in range(MAX_ITERATIONS):
        t_new = (1 - ALPHA) * C_T.dot(t) + ALPHA * p
        # Handle zero-sum rows: blend uniformly
        if len(zero_rows) > 0:
            for i in zero_rows:
                t_new += (1 - ALPHA) * (1.0 / n) * t[i]
        # Normalize to sum=1
        t_sum = t_new.sum()
        if t_sum > 0:
            t_new /= t_sum
        delta = float(np.sum(np.abs(t_new - t)))
        t = t_new
        iterations = iteration + 1
        if delta < CONVERGENCE_EPSILON:
            converged = True
            break

    # --- Step 7: MeritRank decay ---
    if prev_vectors:
        # ⚠ THE SAME LOOKUP, TWO DEFAULTS. Step 5 seeds an agent the previous epoch never saw at
        # the uniform 1/n; this line used to seed it at 0.0, so a NEW agent kept only 5 % of its
        # computed trust while an established one carried 95 % of its history — a structural
        # suppression of every newcomer for dozens of epochs, from a default that disagreed with
        # its twin twelve lines up. One default, named once.
        t_prev_aligned = np.array([prev_vectors.get(did, _NEW_AGENT_SEED) for did in all_dids])
        # Blend: new_score = converged * (1-decay) + previous * decay
        t_final = t * (1 - EPOCH_DECAY) + t_prev_aligned * EPOCH_DECAY
    else:
        t_final = t  # First epoch: no decay

    # Re-normalize after decay blend
    t_sum = t_final.sum()
    if t_sum > 0:
        t_final /= t_sum

    # --- Step 8: Volume weighting ---
    vol_weights = np.ones(n, dtype=float)
    for i, did in enumerate(all_dids):
        vol = float(volume_map.get(i, 0))   # Decimal ** float raises; the weight is a ratio
        if vol > 0:
            vol_weights[i] = float(vol ** VOLUME_WEIGHT_EXP)
    t_weighted = t_final * vol_weights
    max_weighted = t_weighted.max()
    if max_weighted > 0:
        t_weighted /= max_weighted  # Normalize to [0, 1]

    # --- Step 9: Write GlobalTrustVector + project to Agent.reputation_score ---
    current_epoch = prev_epoch + 1
    now = datetime.now(timezone.utc)
    elapsed_ms = int((time.monotonic() - t_start) * 1000)

    event_emitter = get_event_emitter()

    agents_result = await db.execute(
        select(Agent).where(Agent.did.in_(all_dids))
    )
    agent_map = {a.did: a for a in agents_result.scalars().all()}

    # Similarity score per agent: mean cosine similarity to all interacted peers
    def _compute_sim_score(idx: int) -> float:
        scores = []
        for j_ptr in range(C.indptr[idx], C.indptr[idx + 1]):
            j = C.indices[j_ptr]
            sim = float(np.dot(features_norm[idx], features_norm[j]))
            scores.append(sim)
        return float(np.mean(scores)) if scores else 0.0

    # --- the projection to the published integer ---
    # `linear` is the historical behaviour and stays the default. `log` exists because the vector
    # this projects is a power law: on registry-a it spans 7.1 orders of magnitude, and a linear
    # x1000 integer can only carry the top three, so 4,010 of 4,050 agents land on exactly 0.
    # The floor is derived from THIS epoch's own smallest positive value rather than pinned, so the
    # mapping cannot go stale as the population changes.
    _positive = [float(x) for x in t_weighted if float(x) > 0.0]
    _log_floor = min(_positive) if _positive else 0.0

    for i, did in enumerate(all_dids):
        gt_val = float(t_weighted[i])
        sim_score = _compute_sim_score(i)
        int_projection = _project(gt_val, _log_floor)

        # Upsert GlobalTrustVector
        gtv_result3 = await db.execute(
            select(GlobalTrustVector).where(GlobalTrustVector.agent_did == did)
        )
        gtv_row = gtv_result3.scalar_one_or_none()

        if gtv_row is None:
            gtv_row = GlobalTrustVector(
                id=str(uuid.uuid4()),
                agent_did=did,
                global_trust=gt_val,
                similarity_score=sim_score,
                epoch=current_epoch,
                computed_at=now,
                computation_time_ms=elapsed_ms,
            )
            db.add(gtv_row)
        else:
            gtv_row.global_trust = gt_val
            gtv_row.similarity_score = sim_score
            gtv_row.epoch = current_epoch
            gtv_row.computed_at = now
            gtv_row.computation_time_ms = elapsed_ms

        # Project to Agent.reputation_score
        agent = agent_map.get(did)
        if agent is not None:
            old_score = agent.reputation_score
            if old_score != int_projection:
                await db.execute(
                    update(Agent)
                    .where(Agent.did == did)
                    .values(reputation_score=int_projection)
                )
                # Emit ReputationChanged event (fire-and-forget)
                try:
                    import asyncio
                    asyncio.create_task(event_emitter.emit_reputation_changed(
                        agent_did=did,
                        old_score=old_score,
                        new_score=int_projection,
                        reason=f"EigenTrust++ epoch {current_epoch}",
                    ))
                except Exception as e:
                    logger.debug(f"ReputationChanged emit error (non-fatal): {e}")

    await db.commit()

    elapsed_ms = int((time.monotonic() - t_start) * 1000)

    # SF-5D: Fetch and store cross-frame reputation scores (best-effort)
    foreign_count = await _fetch_foreign_reputation(db)

    logger.info(
        f"EigenTrust++ epoch {current_epoch} complete: "
        f"{len(all_dids)} agents, {iterations} iterations, "
        f"converged={converged}, {elapsed_ms}ms"
        + (f", {foreign_count} foreign scores cached" if foreign_count else "")
    )
    return {
        "epoch": current_epoch,
        "agents_computed": len(all_dids),
        "computation_time_ms": elapsed_ms,
        "iterations": iterations,
        "converged": converged,
        "foreign_scores_cached": foreign_count,
    }


# --- Module-level state for worker access ---
# §DOCSFIX D6-604 (2026-10-16): the last epoch's result, the next scheduled run and the cross-frame reputation cache
# live in Redis, where every gunicorn worker reads them. As module globals they were the state of the one process that
# ran the epoch (the leader): another process answered /computation-status and /cross-frame with null and empty.
# The globals stay as the fallback of a registry without Redis (the state of this process only), and `state_store()`
# says which one answers.
_STATE_LAST_EPOCH = "registry:eigentrust:last_epoch"
_STATE_NEXT_AT = "registry:eigentrust:next_scheduled_at"
_STATE_FOREIGN = "registry:eigentrust:foreign_reputation"
_last_epoch_result: Optional[dict] = None
_next_scheduled_at: Optional[datetime] = None


async def _redis():
    try:
        from ..background_tasks.leader import get_redis
        return await get_redis()
    except Exception:  # noqa: BLE001 — no Redis is the fallback, never an error here
        return None


async def _shared_get(key: str) -> Optional[str]:
    r = await _redis()
    if r is None:
        return None
    try:
        return await r.get(key)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"EigenTrust++ shared state read failed ({key}): {e}")
        return None


async def _shared_set(key: str, value: str) -> None:
    r = await _redis()
    if r is None:
        return
    try:
        await r.set(key, value)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"EigenTrust++ shared state write failed ({key}), this process keeps it: {e}")


async def state_store() -> str:
    """'shared' when Redis answers (every worker reads the same state), 'process' when it does not."""
    return "shared" if await _redis() is not None else "process"


async def get_last_epoch_result() -> Optional[dict]:
    raw = await _shared_get(_STATE_LAST_EPOCH)
    return json.loads(raw) if raw else _last_epoch_result


async def get_next_scheduled_at() -> Optional[datetime]:
    raw = await _shared_get(_STATE_NEXT_AT)
    return datetime.fromisoformat(raw) if raw else _next_scheduled_at


async def set_next_scheduled_at(dt: datetime) -> None:
    global _next_scheduled_at
    _next_scheduled_at = dt
    await _shared_set(_STATE_NEXT_AT, dt.isoformat())


async def set_last_epoch_result(result: dict) -> None:
    global _last_epoch_result
    _last_epoch_result = result
    await _shared_set(_STATE_LAST_EPOCH, json.dumps(result, default=str))


# --- SF-5D: Cross-Frame Reputation Cache ---
# Stores foreign trust scores fetched from EventStore's cross-frame-reputation endpoint.
# Consumers (e.g., agent profiles, discovery ranking) can query this cache.
_foreign_reputation_cache: dict = {}  # {agent_did: {"global_trust": float, "frame_id": str, ...}}


async def get_all_foreign_reputation() -> dict:
    """Get all foreign reputation scores (the shared copy when Redis answers, else this process's)."""
    raw = await _shared_get(_STATE_FOREIGN)
    return json.loads(raw) if raw else dict(_foreign_reputation_cache)


async def get_foreign_reputation(agent_did: str) -> Optional[dict]:
    """Get foreign reputation score for an agent (from cross-frame cache)."""
    return (await get_all_foreign_reputation()).get(agent_did)


async def _fetch_foreign_reputation(db: AsyncSession) -> int:
    """SF-5D: Fetch cross-frame reputation from EventStore. Best-effort, non-blocking."""
    global _foreign_reputation_cache
    import os
    import httpx

    es_url = os.getenv("EVENT_STORE_URL", "http://event-store:8200")
    es_key = os.getenv("EVENT_STORE_API_KEY", "")
    if not es_key:
        return 0
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
            resp = await client.get(
                f"{es_url}/api/v1/projections/cross-frame-reputation",
                headers={"X-Internal-Key": es_key},
                params={"limit": 500},
            )
            if resp.status_code != 200:
                return 0
            data = resp.json()
            foreign = data.get("foreign_reputation", [])
            new_cache = {}
            for entry in foreign:
                did = entry.get("agent_did")
                if did:
                    new_cache[did] = entry
            _foreign_reputation_cache = new_cache
            await _shared_set(_STATE_FOREIGN, json.dumps(new_cache, default=str))
            return len(new_cache)
    except Exception as e:
        logger.debug(f"SF-5D: Foreign reputation fetch failed (non-fatal): {e}")
        return 0
