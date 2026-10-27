"""
§SHOWCASEVISITOR — the sweeper.

The Commander's instruction, verbatim: *"we need a scheduled sweep to correctly
claw back the showcase agents money after some time and delete them."*

One agent per visitor on a PUBLIC endpoint is unbounded rows and scattered
float. This is the other half of that feature, and it is not optional: without
it the showcase quietly accumulates dead identities each holding a few tokens.

🔴 SCOPED BY ISSUER, NEVER BY `birth=true`. Measured on frame-c before a line of
this was written: **4,307 birth tokens already exist**, spawned by the EigenTrust
simulation. A sweeper that enumerated "birth tokens" would have found 4,307 live
simulation agents and tried to retire them. Every query below is scoped to
`issuer_agent_did = <the showcase funder>`, which is the only set this feature
created and therefore the only set it may delete.

WHERE THE MONEY GOES, and why it is not back to the funder. Returning a child's
remainder to the funder would require acting AS the child, which would mean
storing every child's `client_secret` — a credential store for throwaways, to
recover a couple of tokens. Instead the remainder goes to the TREASURY through
the EXISTING admin clawback rail the registry already proxies
(`/admin/treasury/receive`, documented in-source as "Admin clawback"). That is
Δ-neutral: treasury balance is inside `total_circulating`, so this is a transfer,
not a destruction. The funder is not meaningfully drained by the difference —
10M against a 3-token float is ~3.3M visitors — and topping it up, if it ever
matters, is a deliberate operator act through FLOW 4, not something a background
task does to itself.

RETIREMENT IS A SOFT DELETE. `status='revoked'`, the same thing the developer
delete rail does, plus revoking the birth token so the capability stops
resolving. An agent that actually transacted keeps its rows: the ledger it
appears in is immutable and its counterparties' receipts must still resolve.
"""
from __future__ import annotations

import asyncio
import logging
import os
from decimal import Decimal
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import text

from ..database import AsyncSessionLocal
from .leader import run_with_leadership
from ..core.path_segment import seg  # §MCPTEST30 V0523: a caller's value is one path segment, encoded

logger = logging.getLogger(__name__)

# Below this, clawing back costs more than it recovers (a transfer emits events
# and touches two ledgers). Left on the dead agent, which is then retired.
DUST = Decimal("0.000001")


def _cfg() -> Dict[str, Any]:
    from ..services.showcase_visitor import visitor_config
    return visitor_config()


def _funder_did() -> str:
    return os.getenv("SHOWCASE_PPAO_DID", "") or ""


def _teg() -> tuple:
    """🔴 MEASURED, NOT ASSUMED. The first cut of this read
    `os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080")` with a bare
    httpx client, and every balance read failed: frame-c's TEG is
    `https://frame-c-nginx-teg:8443`, behind the fabric CA. That is the
    §OURSTATE-5 scar exactly — a bare `httpx.AsyncClient()` bypasses the CA and
    every ledger read fails — and I wrote it again. Resolve through the same
    settings the admin clawback endpoint resolves through, and verify with the
    fabric CA. Imported lazily: `teg_integration` pulls in the router graph.

    ⚠ The fail-safe held while this was broken: an unreadable balance DEFERRED
    the agent instead of retiring it, so no identity was retired with money on
    it. That is why the deferral path exists."""
    from ..routers.teg_integration import TEG_API_BASE_URL, TEG_ADMIN_API_KEY
    from ..es_ssl_helper import get_httpx_verify
    return TEG_API_BASE_URL, TEG_ADMIN_API_KEY, get_httpx_verify()


def enabled() -> bool:
    from ..services.showcase_visitor import visitor_enabled
    # No funder ⇒ this frame never created a visitor ⇒ nothing to sweep. Inert
    # by construction rather than by a second flag.
    return visitor_enabled() and bool(_funder_did())


async def _teg_balance(client: httpx.AsyncClient, teg_url: str, key: str,
                       did: str) -> Optional[Decimal]:
    """Authoritative balance, read from the TEG the same way the reconciliation
    guard does. The registry's own `agents.liquid_balance` is a synced copy and
    can lag — and a clawback sized from a stale figure is exactly the 400 the
    §OURCHAT claw-back earned, where the refusal was correct and the number was
    not."""
    try:
        r = await client.get(f"{teg_url}/api/v1/agent/{seg(did)}/teg-status",
                             headers={"Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            return None
        return Decimal(str(r.json().get("balance", 0)))
    except Exception:  # noqa: BLE001
        return None


async def _clawback(client: httpx.AsyncClient, teg_url: str, key: str,
                    did: str, amount: Decimal) -> bool:
    try:
        r = await client.post(
            f"{teg_url}/api/v1/admin/treasury/receive",
            # §MONEY-R29: `float(amount)` truncated an 18-decimal Decimal on the way into a
            # money leg. The TEG declares `amount: Decimal`, and the PROVEN escrow rail
            # (services/escrow.py::escrow_deposit) posts `str(amount)` to this very endpoint —
            # match it. Same class as the velocity/local-trust truncations (§VITALS).
            # The route accepts an Idempotency-Key and the reference is already deterministic
            # per DID, so send it: every money leg carries its durable key (services/escrow.py).
            json={"source_agent_id": did, "amount": str(amount),
                  "reason": "showcase visitor agent expired",
                  "reference_id": f"showcase-sweep-{did.split(':')[-1]}"},
            headers={"Authorization": f"Bearer {key}",
                     "Idempotency-Key": f"showcase-sweep-{did.split(':')[-1]}"}, timeout=20.0)
        if r.status_code == 200:
            return True
        logger.warning("[ShowcaseSweep] clawback refused for %s: %s %s",
                       did, r.status_code, r.text[:160])
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("[ShowcaseSweep] clawback error for %s: %s", did, e)
        return False


async def _expired_children(db, funder: str, limit: int) -> List[str]:
    rows = (await db.execute(text("""
        SELECT t.holder_agent_did
          FROM agent_capability_tokens t
          JOIN agents a ON a.did = t.holder_agent_did
         WHERE t.issuer_agent_did = :f
           AND t.caveats->>'birth' = 'true'
           AND t.expires_at IS NOT NULL
           AND t.expires_at < now()
           AND a.status <> 'revoked'
         ORDER BY t.expires_at ASC
         LIMIT :n
    """), {"f": funder, "n": limit})).fetchall()
    return [r[0] for r in rows]


async def _collect_positions(db, funder: str, did: str) -> tuple:
    """🔴 SHARES WERE BEING STRANDED. The first cut clawed the token balance and
    retired the identity without ever looking at positions — measured live: 2
    positions on REVOKED visitor agents, still on the cap table, unsellable by
    anyone, forever. His catch.

    Shares are the REGISTRY ledger, not money (`exchange_service.py:2002` says so
    in as many words), so this is not the TEG-surgery rule-10 case: it is a move
    of a registry row. The safety property is **I-X1**, the exchange's own
    invariant — `Σ positions.qty == (total_shares − ipo_float) + ipo_sold` per
    listing — which a MOVE conserves by construction, because the same quantity
    lands on another holder in the same statement.

    Custody goes to the FUNDER, which is the showcase operator's own agent: the
    visitor was always spending the funder's money, so the funder inheriting what
    that money bought is the honest resting place. It is also reversible by hand,
    which stranding is not.

    Returns (moved_rows, moved_shares, ok)."""
    rows = (await db.execute(text("""
        SELECT listing_id, qty FROM org_share_positions
         WHERE agent_did = CAST(:d AS VARCHAR) AND qty > 0
    """), {"d": did})).fetchall()
    if not rows:
        return 0, 0, True

    moved_rows = moved_shares = 0
    for listing_id, qty in rows:
        q = int(qty)
        # ⚠ EVERY PARAM CAST, AND NO ARRAY PARAMS. The first cut used
        # `ANY(:ls)` plus the same :l in two positions and asyncpg answered
        # `AmbiguousParameterError: inconsistent types deduced for parameter $1`
        # — the one-type-per-param scar from §OURSTATE-1, hit again. Cast the
        # parameter at every site and the deduction has nothing to guess.
        before = (await db.execute(text("""
            SELECT COALESCE(SUM(qty), 0) FROM org_share_positions
             WHERE listing_id = CAST(:l AS VARCHAR)
        """), {"l": listing_id})).scalar()
        cost = (await db.execute(text("""
            SELECT avg_cost FROM org_share_positions
             WHERE listing_id = CAST(:l AS VARCHAR) AND agent_did = CAST(:d AS VARCHAR)
        """), {"l": listing_id, "d": did})).scalar()
        await db.execute(text("""
            INSERT INTO org_share_positions
                (listing_id, agent_did, qty, locked_qty, avg_cost, updated_at)
            VALUES (CAST(:l AS VARCHAR), CAST(:f AS VARCHAR), CAST(:q AS BIGINT), 0,
                    CAST(:c AS NUMERIC), now())
            ON CONFLICT (listing_id, agent_did) DO UPDATE
               SET qty = org_share_positions.qty + EXCLUDED.qty, updated_at = now()
        """), {"l": listing_id, "f": funder, "q": q, "c": str(cost or 0)})
        await db.execute(text("""
            UPDATE org_share_positions SET qty = 0, updated_at = now()
             WHERE listing_id = CAST(:l AS VARCHAR) AND agent_did = CAST(:d AS VARCHAR)
        """), {"l": listing_id, "d": did})
        after = (await db.execute(text("""
            SELECT COALESCE(SUM(qty), 0) FROM org_share_positions
             WHERE listing_id = CAST(:l AS VARCHAR)
        """), {"l": listing_id})).scalar()
        if int(after) != int(before):
            # I-X1 would break. Refuse the whole thing rather than half-move a
            # cap table: the caller rolls back and the agent is deferred.
            logger.error("[ShowcaseSweep] I-X1 would break on listing %s (%s -> %s) — "
                         "refusing to collect positions for %s", listing_id, before, after, did)
            return 0, 0, False
        moved_rows += 1
        moved_shares += q
    return moved_rows, moved_shares, True


async def _retire(db, funder: str, did: str) -> None:
    """Soft-delete, revoke the birth token, and prune any stray allowlist entry
    left by a crash between pay and close. All three scoped to this child and
    this funder."""
    await db.execute(text("UPDATE agents SET status='revoked' WHERE did=:d"), {"d": did})
    await db.execute(text("""
        UPDATE agent_capability_tokens SET status='revoked'
         WHERE issuer_agent_did=:f AND holder_agent_did=:d AND status <> 'revoked'
    """), {"f": funder, "d": did})
    await db.execute(text("""
        UPDATE agent_spend_policies
           SET counterparty_allow = array_remove(counterparty_allow, :d)
         WHERE agent_did = :f
    """), {"f": funder, "d": did})
    await db.commit()


async def _self_heal_orphans(db, funder: str) -> tuple:
    """Children RETIRED BEFORE this collection existed still hold shares —
    measured: 2 of them. `_expired_children` skips revoked agents by design, so
    without this pass those stay orphaned on the cap table forever, unsellable
    by anyone. Same scoping (issuer = funder), same conservation check, and it
    must run even on a cycle where nothing is expired — which is why the caller
    no longer returns early."""
    rows = (await db.execute(text("""
        SELECT DISTINCT p.agent_did
          FROM org_share_positions p
          JOIN agent_capability_tokens t ON t.holder_agent_did = p.agent_did
         WHERE t.issuer_agent_did = CAST(:f AS VARCHAR)
           AND t.caveats->>'birth' = 'true' AND p.qty > 0
         LIMIT 25
    """), {"f": funder})).fetchall()
    n_rows = n_shares = 0
    for (odid,) in rows:
        try:
            mr, ms, okp = await _collect_positions(db, funder, odid)
            if okp and mr:
                await db.commit()
                n_rows += mr; n_shares += ms
                logger.info("[ShowcaseSweep] self-heal: collected %d share(s) orphaned on "
                            "already-retired %s", ms, odid)
            else:
                await db.rollback()
        except Exception as e:  # noqa: BLE001
            await db.rollback()
            logger.warning("[ShowcaseSweep] self-heal failed for %s: %s", odid, e)
    return n_rows, n_shares


async def _cycle() -> None:
    funder = _funder_did()
    if not funder:
        return
    cfg = _cfg()
    teg_url, teg_key, verify = _teg()

    async with AsyncSessionLocal() as db:
        dids = await _expired_children(db, funder, int(cfg["sweep_batch"]))
        if not dids:
            # Still heal: an orphaned position outlives every expiry.
            hr, hs = await _self_heal_orphans(db, funder)
            if hr:
                logger.info("[ShowcaseSweep] self-heal only: positions=%d shares=%d", hr, hs)
            return
        swept = clawed = failed = 0
        pos_rows = pos_shares = 0
        recovered = Decimal("0")

        if not teg_key:
            # Say it rather than silently retiring agents with money on them.
            logger.warning("[ShowcaseSweep] no TEG_ADMIN_API_KEY — %d expired visitor "
                           "agents will NOT be swept (their float would be stranded)",
                           len(dids))
            return

        async with httpx.AsyncClient(timeout=20.0, verify=verify) as client:
            for did in dids:
                bal = await _teg_balance(client, teg_url, teg_key, did)
                if bal is None:
                    # An unreadable balance is not a zero balance. Leave it for
                    # the next cycle rather than retire an agent whose money we
                    # could not account for.
                    failed += 1
                    logger.warning("[ShowcaseSweep] balance unreadable for %s — deferred", did)
                    continue
                if bal > DUST:
                    if await _clawback(client, teg_url, teg_key, did, bal):
                        clawed += 1
                        recovered += bal
                    else:
                        failed += 1
                        continue  # money still on it: do not retire
                # Shares before identity: an agent retired while holding a
                # position leaves that position unsellable by anyone.
                try:
                    mr, ms, okp = await _collect_positions(db, funder, did)
                except Exception as e:  # noqa: BLE001
                    await db.rollback()
                    mr, ms, okp = 0, 0, False
                    logger.warning("[ShowcaseSweep] position collect failed for %s: %s", did, e)
                if not okp:
                    failed += 1
                    logger.warning("[ShowcaseSweep] %s holds shares that could not be collected "
                                   "— deferred, NOT retired", did)
                    continue
                pos_rows += mr
                pos_shares += ms
                await _retire(db, funder, did)
                swept += 1

        hr, hs = await _self_heal_orphans(db, funder)
        pos_rows += hr; pos_shares += hs
        logger.info("[ShowcaseSweep] retired=%d clawed_back=%d recovered=%s "
                    "positions_collected=%d shares=%d deferred=%d (of %d expired)",
                    swept, clawed, recovered, pos_rows, pos_shares, failed, len(dids))


async def run_showcase_visitor_sweeper() -> None:
    if not enabled():
        logger.info("[ShowcaseSweep] inert (no showcase funder configured on this frame)")
        return
    interval = float(_cfg()["sweep_interval"])
    logger.info("[ShowcaseSweep] starting; interval=%ss funder=%s", interval, _funder_did())
    try:
        async for _ in run_with_leadership("showcase_visitor_sweeper", interval=interval):
            try:
                await _cycle()
            except Exception as exc:  # noqa: BLE001
                logger.error("[ShowcaseSweep] cycle failed: %s", exc, exc_info=True)
    except asyncio.CancelledError:
        logger.info("[ShowcaseSweep] stopped (cancellation)")
        raise
