"""THE GUILD — reputation + work credential on completion (2026-07-07).

On a VERIFIED work order:
  1. **Reputation** — upsert a `local_trust_scores` edge (poster → worker) weighted by the star
     rating, exactly like `eval_runner._fold_reputation`. The hourly EigenTrust epoch absorbs it and
     re-projects `Agent.reputation_score`. This is the ONLY path that durably moves EigenTrust (the
     flat ±1 score gets overwritten by the epoch), so we write the trust graph directly. No new
     ranking system.
  2. **Work credential** — an Ed25519-signed, portable, offline-verifiable "proof of completed work"
     via the existing attestation SIGNER rails (`services/attestation_signer.py`). Signed, not yet
     zero-knowledge: the true ZK aggregate-reputation circuit (`proof_of_reputation`) is an
     un-compiled Noir stub — flagged as a handoff. The signed credential is a real verifiable
     credential today; the ZK upgrade slots into the same rails later. Gated GUILD_ZK_CREDENTIAL_ENABLED.
Δ-irrelevant (reputation + signing only; no money).
"""
from __future__ import annotations

import logging
import os
import uuid

from sqlalchemy import text as sa_text
from decimal import Decimal

logger = logging.getLogger(__name__)


async def fold_work_reputation(db, poster_did: str, worker_did: str, stars: int, volume: float) -> None:
    """Star rating (1-5) → local_trust edge poster→worker. >=3★ satisfactory, else unsatisfactory.
    local_trust normalized to [0,1] as (stars-1)/4. Absorbed by the EigenTrust epoch. Best-effort."""
    try:
        s = max(1, min(5, int(stars)))
        sat = 1 if s >= 3 else 0
        unsat = 0 if s >= 3 else 1
        lt = (s - 1) / 4.0
        await db.execute(sa_text("""
            INSERT INTO local_trust_scores
                (id, from_did, to_did, satisfactory, unsatisfactory, local_trust, normalized, tx_volume, last_updated)
            VALUES (:id, :f, :t, :sat, :unsat, :lt, 0, :vol, now())
            ON CONFLICT (from_did, to_did) DO UPDATE SET
                satisfactory   = local_trust_scores.satisfactory + :sat,
                unsatisfactory = local_trust_scores.unsatisfactory + :unsat,
                local_trust    = :lt,
                tx_volume      = local_trust_scores.tx_volume + :vol,
                last_updated   = now()
        """), {"id": uuid.uuid4().hex, "f": poster_did, "t": worker_did,
               "sat": sat, "unsat": unsat, "lt": lt, "vol": Decimal(str(volume or 0))})
        logger.info("[GUILD] reputation fold poster=%s worker=%s stars=%s lt=%.2f", poster_did, worker_did, s, lt)
    except Exception as e:  # noqa: BLE001
        logger.warning("[GUILD] reputation fold failed: %s", e)


def zk_credential_enabled() -> bool:
    return os.getenv("GUILD_ZK_CREDENTIAL_ENABLED", "false").strip().lower() == "true"


def credential_pubkey() -> dict:
    """The registry's credential-signing pubkey (attestation signer) for peer verification.
    Served over the federation channel so a worker's HOME can verify travel credentials."""
    try:
        from agentvault_registry.services.attestation_signer import get_pubkey_b64, get_pubkey_id  # type: ignore
        return {"pubkey_b64": get_pubkey_b64(), "pubkey_id": get_pubkey_id(), "alg": "Ed25519"}
    except Exception as e:  # noqa: BLE001
        logger.warning("[GUILD] credential pubkey unavailable: %s", e)
        return {}


async def issue_work_credential(order: dict, stars: int | None = None) -> dict | None:
    """Ed25519-signed, portable, offline-verifiable credential attesting a completed work order.
    Reuses the attestation signer rails. Returns the signed bundle, or None if disabled/unavailable.
    Best-effort — never blocks settlement."""
    if not zk_credential_enabled():
        return None
    try:
        from agentvault_registry.services.attestation_signer import sign_bundle  # type: ignore
    except Exception:  # noqa: BLE001
        logger.debug("[GUILD] attestation signer unavailable — credential skipped")
        return None
    claim = {
        "kind": "guild.work_credential.v1",
        "order_id": order.get("id"),
        "worker_did": order.get("worker_did"),
        "poster_did": order.get("poster_did"),
        "title": order.get("title"),
        "bounty": str(order.get("bounty")),
        "currency": order.get("currency"),
        "settled_at": str(order.get("settled_at")),
        # Star rating rides the credential so the worker's HOME can fold the same trust edge
        # (trust that travels). NOTE: signed (not ZK). ZK aggregate circuit = documented handoff.
        "stars": stars,
        # FIRM work: the payee (org treasury) is SIGNED into the claim so the home fold can
        # credit the firm — reputation follows the payee on both sides. None for individuals.
        "payee_did": order.get("payee_did"),
        "payee_org_id": order.get("payee_org_id"),
    }
    try:
        return sign_bundle(claim)  # type: ignore
    except Exception as e:  # noqa: BLE001
        logger.warning("[GUILD] work credential sign failed: %s", e)
        return None
