"""
DevCard v0.1 — HOME-side build/sign/serve (AGORA Passport §9, 2026-06-12).

The third card type beside agent cards + registry cards (Commander idea, D24):
a minimal-disclosure, home-registry-EdDSA-signed owner-identity document.

CONSENT-BOUND + LAZY by design: never part of bulk federation_sync. Two paths:
  PUSH (primary): when this registry's agent opts into a foreign venue, the
       Passport relay builds + signs OUR dev's card and sends it along — the
       purest consent (the dev's own agent initiated the participation).
  PULL (re-verify): peer registries may re-pull by agent DID over the
       federation channel (require_peer_registry_identity).
Every build writes a disclosure-audit row (dev_card_disclosures, migration
0089) — GDPR purpose-binding: who/which-agent/when/why. Signing reuses the
Registry-Card-v0.3 Ed25519 keystore, so venues verify against the home's
already-federated PUBLIC /.well-known/registry-jwks.json (no auth needed for
verification — only for disclosure).
"""
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.config import settings
from agentvault_registry.core.federation_auth import require_peer_registry_identity
from agentvault_registry.database import get_db
from agentvault_registry.models import Agent, Developer, Organization

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/federation", tags=["DevCard"])

DEVCARD_SCHEMA = "devcard/0.1"


def _home_registry_name() -> str:
    """The name this registry's PEERS know it by: a venue resolves the home's JWKS by exactly this string to verify the
    DevCard. §AGORASIM-2 (2026-09-22): it read REGISTRY_NAME first, which on a cloud operator is the stack label
    (`cloud-op-sbxalphaop`) while its card and every peer row say `sbxalphaop`; for an agent the venue cannot place
    through the card mesh (an unlisted clerk) that made every passport order 502 "no ACTIVE peer registry
    'cloud-op-sbxalphaop'". One rule now, the card's: services/contract_xframe.self_federation_name()."""
    from agentvault_registry.services.contract_xframe import self_federation_name
    return (
        self_federation_name()
        or os.getenv("REGISTRY_NAME")
        or os.getenv("LOCAL_REGISTRY_KEY")
        or "local"
    )


async def _devcard_payload(db: AsyncSession, agent: Agent, dev: Developer) -> Dict[str, Any]:
    """The exact minimal-disclosure payload a venue receives. Shared by the
    signing path AND the Settings preview (preview = transparency, no signature,
    no disclosure row)."""
    orgs = (
        await db.execute(select(Organization.slug).where(Organization.owner_id == dev.id))
    ).scalars().all()

    standing = "active"
    if getattr(dev, "is_active", True) is False or getattr(dev, "is_suspended", False):
        standing = "suspended"
    if agent.status != "active":
        standing = "suspended"

    return {
        "schema": DEVCARD_SCHEMA,
        "developer_ref": str(dev.id),
        "display_name": dev.name,
        "contact_email": dev.email,
        "home_registry": _home_registry_name(),
        "standing": standing,
        "agent_did": agent.did,
        "org_refs": list(orgs),
        "attestations": {"email_verified": bool(getattr(dev, "is_email_verified", False))},
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }


async def build_signed_devcard(db: AsyncSession, agent: Agent, requested_by: str) -> Dict[str, Any]:
    """Build + sign the DevCard for a LOCAL agent's owner; write the disclosure
    audit row. Shared by the peer-pull endpoint AND the Passport push relay."""
    dev = (
        await db.execute(select(Developer).where(Developer.id == agent.creator_developer_id))
    ).scalar_one_or_none()
    if dev is None:
        raise HTTPException(status_code=404, detail="owner developer not found")

    # Consent override (§V0064 Settings, migration 0090): an opted-out dev's
    # identity NEVER leaves the home registry — their agents simply cannot
    # Passport-trade until they flip the toggle back.
    if getattr(dev, "dev_card_passport_opt_out", False):
        raise HTTPException(status_code=403, detail="owner has opted out of DevCard passport disclosure")

    payload = await _devcard_payload(db, agent, dev)

    from agentvault_registry.identity import svid_client
    from agentvault_registry.services.registry_card_keystore import get_or_mint_signing_key
    from agentvault_registry.services.registry_card_signer_impl import sign_with_keypair

    spiffe_id = svid_client.get_spiffe_id() or f"spiffe://unknown/{_home_registry_name()}"
    key_row = await get_or_mint_signing_key(db, spiffe_id)
    signature = sign_with_keypair(payload, key_row)
    kid = f"{spiffe_id}#{key_row.rotation_seq}"

    # Disclosure audit (GDPR purpose-binding) — fail-open but loudly logged.
    try:
        await db.execute(
            text(
                "INSERT INTO dev_card_disclosures (developer_id, agent_did, requested_by, purpose)"
                " VALUES (:dev, :did, :peer, 'exchange_participation')"
            ),
            {"dev": dev.id, "did": agent.did, "peer": requested_by[:255]},
        )
        await db.commit()
    except Exception as e:
        logger.error(f"[DevCard] disclosure audit write failed (served anyway): {e}")

    return {
        "payload": payload,
        "signature": {"alg": "EdDSA", "kid": kid, "value": signature},
    }


@router.get("/dev-card/by-agent/{agent_did}", summary="DevCard for an agent's owner (peer registries only)")
async def dev_card_by_agent(
    agent_did: str,
    peer_spiffe: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """PULL path: a venue re-verifies a participant. 404 when the agent isn't
    homed here (the venue asked the wrong registry)."""
    agent = (await db.execute(select(Agent).where(Agent.did == agent_did))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not homed on this registry")
    return await build_signed_devcard(db, agent, requested_by=peer_spiffe)


# ═══════════════════════════════════════════════════════════════════════
# Developer-facing surface (§V0064 Settings → Developer Card tab)
# Transparency + consent: preview the exact disclosure, audit every pull,
# flip the passport opt-out. Dev JWT; never writes disclosure rows.
# ═══════════════════════════════════════════════════════════════════════
from pydantic import BaseModel

from agentvault_registry.security import get_current_developer

dev_router = APIRouter(prefix="/api/v1/dev-card", tags=["DevCard"])


class ConsentBody(BaseModel):
    passport_opt_out: bool


@dev_router.get("/preview/{agent_did}", summary="Preview MY DevCard payload for one of my agents")
async def dev_card_preview(
    agent_did: str,
    dev: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """What a foreign venue would receive if THIS agent opted into Passport
    trading. Unsigned, no disclosure row: transparency only."""
    agent = (
        await db.execute(
            select(Agent).where(Agent.did == agent_did, Agent.creator_developer_id == dev.id)
        )
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found or not yours")
    payload = await _devcard_payload(db, agent, dev)
    return {
        "payload": payload,
        "signed": False,
        "note": "Preview only — the real card is EdDSA-signed at disclosure time and logged below.",
        "passport_opt_out": bool(getattr(dev, "dev_card_passport_opt_out", False)),
    }


@dev_router.get("/disclosures", summary="MY DevCard disclosure audit log")
async def dev_card_disclosures(
    dev: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    rows = (
        await db.execute(
            text(
                "SELECT agent_did, requested_by, purpose, created_at FROM dev_card_disclosures"
                " WHERE developer_id = :dev ORDER BY created_at DESC LIMIT 200"
            ),
            {"dev": dev.id},
        )
    ).all()
    return {
        "disclosures": [
            {
                "agent_did": r[0],
                "requested_by": r[1],
                "purpose": r[2],
                "at": r[3].isoformat() if r[3] else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@dev_router.get("/consent", summary="MY DevCard passport consent state")
async def dev_card_consent_get(
    dev: Developer = Depends(get_current_developer),
) -> Dict[str, Any]:
    return {"passport_opt_out": bool(getattr(dev, "dev_card_passport_opt_out", False))}


@dev_router.put("/consent", summary="Set MY DevCard passport consent")
async def dev_card_consent_set(
    body: ConsentBody,
    dev: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    row = (await db.execute(select(Developer).where(Developer.id == dev.id))).scalar_one()
    row.dev_card_passport_opt_out = bool(body.passport_opt_out)
    await db.commit()
    logger.info(
        f"[DevCard] dev {dev.id} set passport_opt_out={body.passport_opt_out}"
    )
    return {"passport_opt_out": bool(body.passport_opt_out)}
