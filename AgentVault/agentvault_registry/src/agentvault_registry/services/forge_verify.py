"""GÖDEL FORGE — N-of-M staked verifier quorum for ``code_patch`` evals (2026-07-19).

The anti-eval-hacking core. A candidate variant NEVER self-reports its benchmark score.
Instead, a quorum of independent, staked, org-consented VERIFIER agents each run the held-out
hidden tests on THEIR OWN infrastructure (the platform never executes agent code) and return a
pass-fraction; the score settles ONLY when at least M of them AGREE (within epsilon of the
median). Disagreement → no score (the run is inconclusive, not passed). This directly counters
the objective-hacking Sakana observed in the DGM paper (agents fabricating test logs): forging
one log does nothing; you would have to corrupt a majority of independently-selected, staked
verifiers.

Selection = agents holding a live ``forge.verify_for_org`` delegation grant (grant-only — a role,
incl. legacy-full, never qualifies; the Verifier-Guild org consents per-agent) with stake ≥
FORGE_VERIFIER_MIN_STAKE, excluding the candidate. Verifier authentication is by the verifier's
own agent identity on the response channel; an Ed25519 co-signature over the result bundle
(reusing the attestation sign_bundle rail) is a hardening follow-up. Δ-irrelevant (scoring only;
verifier pay rides the existing reward/guild rails). Gated by FORGE_ENABLED.
"""
from __future__ import annotations

import logging
import statistics
from typing import Awaitable, Callable, Optional

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..forge_flags import (forge_enabled, verifier_quorum_m, verifier_min_stake,
                           verifier_min_reputation, verifier_max_per_operator, verifier_require_sig)

logger = logging.getLogger(__name__)

_AGREE_EPS = 0.15          # verifiers "agree" if within this of the median fraction
_DISPATCH_TIMEOUT = 30.0   # per-verifier HTTP timeout (they run tests on their own infra)


async def _sig_ok(db: AsyncSession, vdid: str, task_id, frac: float,
                  sig_b64: Optional[str]) -> Optional[bool]:
    """Verify a verifier's Ed25519 co-signature over its verdict.

    Returns True (valid), False (present but INVALID — vote must be discarded), or
    None (verifier has no current registered signing key / no signature supplied —
    'unsigned', accepted unless FORGE_VERIFIER_REQUIRE_SIG). Canonical payload matches
    the reference daemon: ``forge-verify|{task_id}|{verifier_did}|{frac:.6f}``."""
    if not sig_b64:
        return None
    try:
        import base64
        import json as _json
        row = (await db.execute(text(
            "SELECT public_jwk FROM agent_signing_keys "
            "WHERE agent_did = :d AND expires_at IS NULL "
            "ORDER BY rotation_seq DESC LIMIT 1"), {"d": vdid})).first()
        if not row or not row[0]:
            return None
        jwk = row[0] if isinstance(row[0], dict) else _json.loads(row[0])
        x = jwk.get("x")
        if not x or jwk.get("crv") != "Ed25519":
            return None
        pub_raw = base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        payload = f"forge-verify|{task_id}|{vdid}|{float(frac):.6f}".encode()
        Ed25519PublicKey.from_public_bytes(pub_raw).verify(
            base64.b64decode(sig_b64), payload)
        return True
    except Exception:  # noqa: BLE001 — any failure = invalid signature
        return False


async def _audit(db: AsyncSession, action: str, *, actor_did: str, candidate_did: str,
                 severity: str, details: dict) -> None:
    """Observe-only feed row (NO auto-teeth — enforcement stays a manual admin act)."""
    try:
        from .admin_audit import log_ironkey_action
        await log_ironkey_action(
            db, action=action, actor_type="agent", actor_id=actor_did,
            target_type="agent", target_id=candidate_did,
            outcome="observed", severity=severity, details=details)
    except Exception as e:  # noqa: BLE001
        logger.debug("[FORGE] audit row failed (%s): %s", action, e)


async def select_verifiers(db: AsyncSession, exclude_did: str, limit: int) -> list[str]:
    """Verifier DIDs = active agents holding a live ``forge.verify_for_org`` grant that clear
    the concrete admission floors (batch 8): stake ≥ FORGE_VERIFIER_MIN_STAKE, reputation ≥
    FORGE_VERIFIER_MIN_REPUTATION, candidate excluded — then a PER-OPERATOR seat cap
    (default quorum_m − 1) so no single controlling developer can constitute a quorum
    majority. Grant-only (never role-derived); ordering is stake-desc deterministic."""
    min_stake = verifier_min_stake()
    min_rep = verifier_min_reputation()
    rows = (await db.execute(text(
        """
        SELECT did, dev_id FROM (
            SELECT g.delegate_agent_did AS did,
                   a.creator_developer_id AS dev_id,
                   COALESCE(a.staked_balance, 0) AS stk,
                   MIN(g.id) AS gid
            FROM agent_delegation_grants g
            JOIN agents a ON a.did = g.delegate_agent_did
            WHERE g.revoked_at IS NULL
              AND (g.expires_at IS NULL OR g.expires_at > now())
              AND 'forge.verify_for_org' = ANY(g.permissions)
              AND a.status NOT IN ('suspended', 'revoked')
              AND g.delegate_agent_did <> :cand
              AND COALESCE(a.staked_balance, 0) >= :min_stake
              AND COALESCE(a.reputation_score, 0) >= :min_rep
            GROUP BY g.delegate_agent_did, a.creator_developer_id, a.staked_balance
        ) v
        ORDER BY stk DESC, gid ASC
        LIMIT :lim
        """
    ), {"cand": exclude_did, "min_stake": min_stake, "min_rep": min_rep,
        "lim": max(limit * 4, 25)})).fetchall()
    cap = verifier_max_per_operator()
    per_dev: dict = {}
    picked: list[str] = []
    for did, dev_id in rows:
        # NULL owners are unattributable — conservatively pooled as ONE operator so a batch
        # of orphaned agents can't skirt the concentration cap.
        key = dev_id if dev_id is not None else "unattributed"
        if per_dev.get(key, 0) >= cap:
            continue
        per_dev[key] = per_dev.get(key, 0) + 1
        picked.append(did)
        if len(picked) >= limit:
            break
    return picked


async def _dispatch_one(client: httpx.AsyncClient, endpoint: str, job: dict) -> Optional[dict]:
    """POST the code_patch job to one verifier; return {"frac": float, "sig": b64|None}."""
    try:
        r = await client.post(endpoint.rstrip("/") + "/forge/verify", json=job,
                              timeout=_DISPATCH_TIMEOUT)
        if r.status_code == 200:
            body = r.json() or {}
            frac = body.get("test_fraction")
            if frac is not None:
                return {"frac": max(0.0, min(1.0, float(frac))),
                        "sig": body.get("sig_ed25519_b64")}
    except Exception as e:  # noqa: BLE001
        logger.debug("[FORGE] verifier dispatch failed %s: %s", endpoint, e)
    return None


async def run_quorum(
    db: AsyncSession,
    task,
    candidate_did: str,
    endpoint_of: Callable[[AsyncSession, str], Awaitable[Optional[str]]],
    pay_slot: Optional[str] = None,
) -> tuple[Optional[float], dict]:
    """Return ``(settled, meta)`` — the quorum-agreed held-out test fraction in [0,1] (or None
    if fewer than M verifiers agree: inconclusive → no score) plus vote metadata
    ``{"responders": n, "signed": k, "votes": [{"did","frac","signed"}...]}``.
    ``endpoint_of(db, did)`` resolves a verifier's service URL from its card. ``pay_slot`` is the run's payment
    identity (background_tasks/eval_runner: a scheduled run's slot, or the day of a run started on demand)."""
    meta: dict = {"responders": 0, "signed": 0, "votes": []}
    if not forge_enabled():
        return None, meta
    m = verifier_quorum_m()
    pool = await select_verifiers(db, candidate_did, max(m + 2, 5))
    if len(pool) < m:
        logger.info("[FORGE] verifier pool %d < quorum M=%d — inconclusive (no score)", len(pool), m)
        return None, meta
    task_id = getattr(task, "id", None)
    job = {
        "candidate_did": candidate_did,
        "task_id": task_id,
        "grader": (getattr(task, "grader_config", None) or {}),
        "holdout": bool(getattr(task, "holdout", False)),
    }
    # Ship the candidate's COMMITTED answers with the dispatch (they are the candidate's own
    # artifact — handing them to the jury IS the protocol). A community verifier can then grade
    # with zero read-back privileges against this registry; the reference daemon keeps its
    # admin-fetch fallback for jobs from older registries that omit this field.
    try:
        vrow = (await db.execute(text(
            "SELECT configuration FROM agent_versions WHERE agent_did = :d "
            "ORDER BY created_at DESC LIMIT 1"), {"d": candidate_did})).first()
        cfg = vrow[0] if vrow and isinstance(vrow[0], dict) else {}
        sols = ((cfg.get("artifacts") or {}).get("answers") or {}).get("solutions")
        if isinstance(sols, list):
            job["candidate_solutions"] = sols
    except Exception:  # noqa: BLE001 — best-effort enrichment; daemon fallback covers it
        logger.debug("[FORGE] candidate solutions inline failed for %s", candidate_did, exc_info=True)
    # Seed-phase escape hatch: until community verifiers advertise their own service URLs on
    # their (agent-owned) cards, a registry may point ALL dispatches at a REFERENCE verifier
    # daemon. Verifier identity/grant/stake selection is unchanged — only the transport address.
    import os
    ep_override = os.getenv("FORGE_VERIFIER_ENDPOINT_OVERRIDE", "").strip() or None
    require_sig = verifier_require_sig()
    votes: list[tuple[str, float, bool]] = []   # (verifier_did, fraction, signed)
    async with httpx.AsyncClient() as client:
        for vdid in pool:
            ep = ep_override or await endpoint_of(db, vdid)
            if not ep:
                continue
            # Each dispatch names the verifier it is addressed to, so a (shared) daemon can
            # co-sign AS that verifier and a hijacked transport cannot answer for another.
            res = await _dispatch_one(client, ep, {**job, "verifier_did": vdid})
            if res is None:
                continue
            frac = res["frac"]
            sig_state = await _sig_ok(db, vdid, task_id, frac, res.get("sig"))
            if sig_state is False:
                # Present-but-INVALID signature: discard the vote entirely + observe-feed row.
                await _audit(db, "forge_verifier_bad_sig", actor_did=vdid,
                             candidate_did=candidate_did, severity="warning",
                             details={"task_id": task_id, "reported": frac})
                continue
            if require_sig and sig_state is not True:
                logger.info("[FORGE] unsigned vote dropped (REQUIRE_SIG) verifier=%s", vdid)
                continue
            votes.append((vdid, frac, sig_state is True))
    meta["responders"] = len(votes)
    meta["signed"] = sum(1 for _, _, sg in votes if sg)
    meta["votes"] = [{"did": d, "frac": s, "signed": sg} for d, s, sg in votes]
    if len(votes) < m:
        logger.info("[FORGE] only %d/%d verifiers responded (< M=%d) — inconclusive", len(votes), len(pool), m)
        return None, meta
    med = statistics.median(s for _, s, _ in votes)
    agree = [(d, s) for d, s, _ in votes if abs(s - med) <= _AGREE_EPS]
    if len(agree) < m:
        logger.info("[FORGE] quorum disagreement (%d/%d within eps of median) — no score", len(agree), len(votes))
        return None, meta
    settled = round(statistics.median(s for _, s in agree), 6)
    logger.info("[FORGE] code_patch quorum settled: %s (M=%d, responders=%d signed=%d, candidate=%s)",
                settled, m, len(votes), meta["signed"], candidate_did)
    # Deviation observe-feed (NO auto-teeth): a settled quorum existed, yet this responder's
    # score sat outside epsilon of the median. Rows feed SIEM/enforcement review; any slash
    # remains a manual admin act (Commander doctrine: observe-only by default).
    for d, s, _sg in votes:
        if abs(s - med) > _AGREE_EPS:
            await _audit(db, "forge_verifier_deviation", actor_did=d,
                         candidate_did=candidate_did, severity="warning",
                         details={"task_id": task_id, "reported": s,
                                  "median": med, "epsilon": _AGREE_EPS})
    # FG-3 — pay the AGREEING verifiers (never on inconclusive): small reward-waterfall legs,
    # Δ=0 (treasury reward rail), idempotent-ish refs. Verification work is paid work.
    await _pay_verifiers(db, [d for d, _ in agree], task_id=task_id, candidate_did=candidate_did, pay_slot=pay_slot)
    return settled, meta


async def _pay_verifiers(db: AsyncSession, verifier_dids: list[str], *, task_id, candidate_did: str,
                         pay_slot: Optional[str] = None) -> None:
    import hashlib
    import os
    from decimal import Decimal, InvalidOperation
    try:
        # Decimal, not float: this string becomes a transfer amount, and
        # float(0.1) is not 0.1 (§MONEY-R15 — the same truncation class that
        # stored 57% of transfers as zero).
        pay = Decimal(os.getenv("FORGE_VERIFIER_PAY", "0.1").strip())
    except (TypeError, ValueError, InvalidOperation):
        pay = Decimal("0.1")
    if pay <= 0 or not verifier_dids:
        return
    try:
        from ..routers.teg_integration import (
            _fund_agent_from_treasury_internal, TreasuryFundAgentRequest,
        )
        for vdid in verifier_dids:
            req = TreasuryFundAgentRequest(
                target_agent_did=vdid, amount=str(pay), reason="reward",
                reference_id=f"forge-verify:{task_id}:{candidate_did[-8:]}:{vdid[-8:]}",
            )
            # §MONEY-R36: the reference_id was already deterministic and carried
            # no weight — it is a memo. Without an idempotency_key a quorum
            # re-run for the same task pays every agreeing verifier a SECOND
            # time. The key is the same tuple the memo already names, so a
            # replay is refused by the row state rather than by luck.
            # §DOCSFIX D6-687: ...and it names the verdict it pays: the run's pay slot, the task, the candidate and the
            # verifier (the pair as a digest, inside the TEG's 255-character key). Without the candidate and the run, a
            # verifier grading the task for another candidate, or again in a later run, got its first payment's answer.
            # §DOCSFIX review: the slot, not a random run id. A candidate starts runs of itself (POST
            # /forge/evals/run): with a fresh id per run, every run it started paid every agreeing verifier again
            # from the treasury, and two workers running one scheduled slot paid it twice.
            pair = hashlib.sha256(f"{candidate_did}|{vdid}".encode()).hexdigest()[:32]
            await _fund_agent_from_treasury_internal(
                db, req, actor_label="forge_verify",
                idempotency_key=(f"forge-verify-{pay_slot}-{task_id}-{pair}" if pay_slot
                                 else f"forge-verify-{task_id}-{pair}"),
            )
        logger.info("[FORGE] paid %d verifiers %s each (task=%s)", len(verifier_dids), pay, task_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("[FORGE] verifier pay failed (scores unaffected): %s", e)
