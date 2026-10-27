"""Admin: agent signing-key rotation (Option C Phase 9.a, §pass36).

  POST /admin/agents/{did}/rotate-signing-key
    — Generate a fresh EdDSA keypair for the agent. Returns the new private
      PEM ONCE (same lifecycle as client_secret). Bumps rotation_seq.
      Marks the previous active key as expiring after KEY_ROTATION_GRACE_DAYS
      (default 7) so verifiers accept both during the grace window.

  GET /admin/agents/{did}/signing-keys
    — List all signing keys recorded for an agent (current + expiring).
      Doesn't return private material.
"""
from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status, Security
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, security
from ..database import get_db
from ..event_emitter import get_event_emitter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/agents", tags=["Admin — Agent Signing Keys"])

_GRACE_DAYS = int(os.environ.get("KEY_ROTATION_GRACE_DAYS", "7"))


def _generate_eddsa() -> Dict[str, Any]:
    """Return {private_pem, public_jwk} for a fresh Ed25519 keypair."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64

    priv = Ed25519PrivateKey.generate()
    private_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_jwk = {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode("ascii"),
        "alg": "EdDSA",
    }
    return {"private_pem": private_pem, "public_jwk": public_jwk}


@router.post("/{did:path}/rotate-signing-key")
async def rotate_signing_key(
    did: str = Path(..., description="Agent DID"),
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Depends(
        security.require_admin_flag("admin_platform")
    ),
):
    """Rotate the agent's EdDSA signing key.

    Steps:
      1. Find max rotation_seq for this DID; new_seq = N+1.
      2. Generate fresh keypair.
      3. INSERT new row (rotation_seq=N+1, expires_at=NULL).
      4. UPDATE old current row (expires_at=NULL) → expires_at = NOW() + grace.
      5. UPDATE agents.public_key_jwk to the new public JWK.
      6. Emit AgentSigningKeyRotated.
      7. Return {new_kid, private_pem, old_kid_expires_at}. Private PEM shown ONCE.
    """
    # Confirm the agent exists.
    res = await db.execute(
        select(models.Agent).where(models.Agent.did == did)
    )
    agent = res.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {did} not found",
        )

    # Determine new rotation_seq.
    seq_q = await db.execute(
        select(func.coalesce(func.max(models.AgentSigningKey.rotation_seq), 0)).where(
            models.AgentSigningKey.agent_did == did
        )
    )
    current_max = int(seq_q.scalar() or 0)
    new_seq = current_max + 1

    # Generate fresh keypair.
    keys = _generate_eddsa()

    now = datetime.datetime.now(datetime.timezone.utc)
    grace_until = now + datetime.timedelta(days=_GRACE_DAYS)

    # Insert new row.
    new_row = models.AgentSigningKey(
        agent_did=did,
        rotation_seq=new_seq,
        public_jwk=keys["public_jwk"],
        algorithm="EdDSA",
        created_at=now,
        expires_at=None,
    )
    db.add(new_row)

    # Expire any previously-current rows (expires_at IS NULL) with grace.
    if current_max > 0:
        prev_q = await db.execute(
            select(models.AgentSigningKey).where(
                models.AgentSigningKey.agent_did == did,
                models.AgentSigningKey.expires_at.is_(None),
                models.AgentSigningKey.rotation_seq != new_seq,
            )
        )
        prev_rows = list(prev_q.scalars().all())
        for prev in prev_rows:
            prev.expires_at = grace_until
            db.add(prev)

    # Mirror the new public JWK on agents.public_key_jwk so the legacy
    # /agents/{did}/public-key endpoint serves the current key.
    agent.public_key_jwk = keys["public_jwk"]
    db.add(agent)

    await db.commit()

    # Audit emit (best-effort).
    try:
        emitter = get_event_emitter()
        if emitter is not None:
            await emitter.emit(
                event_type="AgentSigningKeyRotated",
                aggregate_id=did,
                aggregate_type="AgentCard",
                data={
                    "agent_did": did,
                    "new_rotation_seq": new_seq,
                    "old_kid_expires_at": grace_until.isoformat() if current_max > 0 else None,
                    "rotated_by_developer_id": current_admin.id,
                    "rotated_by_email": current_admin.email,
                    "grace_days": _GRACE_DAYS,
                },
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[SigningKeyRotate] emit failed (non-fatal): {e}")

    # §pass47 C4 — generic admin audit log (separate from the EventStore audit
    # event above; this row lands in security_audit_logs for SIEM consumers
    # that don't subscribe to EventStore).
    from ..services.admin_audit import log_admin_action
    await log_admin_action(
        db,
        action="rotate_signing_key",
        actor_id=str(current_admin.id),
        target_type="agent",
        target_id=did,
        details={
            "new_rotation_seq": new_seq,
            "grace_days": _GRACE_DAYS,
            "had_previous_key": current_max > 0,
        },
        severity="warning",  # rotation is a privileged op even when routine
    )

    return {
        "agent_did": did,
        "new_kid": f"{did}#{new_seq}",
        "private_pem": keys["private_pem"],
        "public_jwk": keys["public_jwk"],
        "old_kid_expires_at": grace_until.isoformat() if current_max > 0 else None,
        "grace_days": _GRACE_DAYS,
        "shown_once": True,
    }


@router.get("/{did:path}/signing-keys")
async def list_signing_keys(
    did: str = Path(..., description="Agent DID"),
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """List signing-key history for an agent. Public-key material only."""
    res = await db.execute(
        select(models.AgentSigningKey)
        .where(models.AgentSigningKey.agent_did == did)
        .order_by(models.AgentSigningKey.rotation_seq.asc())
    )
    rows = list(res.scalars().all())
    return {
        "agent_did": did,
        "keys": [
            {
                "rotation_seq": r.rotation_seq,
                "kid": f"{did}#{r.rotation_seq}",
                "algorithm": r.algorithm,
                "public_jwk": r.public_jwk,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "is_current": r.expires_at is None,
            }
            for r in rows
        ],
    }
