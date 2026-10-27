"""§FEDLICENCE (2026-09-28): the routes of the signed federation licence (services/federation_licence.py).

Public (anyone may verify a licence without trusting the frame that shows it):
  GET  /.well-known/federation-licence.json          this registry's own network licence (the card's block)
  GET  /.well-known/federation-licences.json         the signed list of every licence this registry issued
  GET  /api/v1/federation/licence/own | /list        the same two, on the path a frame's federation proxy serves
  GET  /api/v1/public/federation/licences/{hash}     one licence this registry issued, as issued
  GET  /api/v1/federation/licence/verdicts           what this registry decided about each peer (its TEG copies it)
Federation (mTLS, this frame's own operators):
  GET  /api/v1/federation/licence/mine               an operator's own licence + its frame's network licence
Admin (admin_federation):
  POST /api/v1/admin/federation/licence/key          this frame's licence-signing public key (minted on first call)
  POST /api/v1/admin/federation/licence/genesis      the genesis ceremony (only where FEDERATION_GENESIS_TRUST_DOMAIN
                                                     names this registry's own trust domain; once)
  POST /api/v1/admin/federation/licence/issue        a frame licence (genesis only) or an operator licence
  POST /api/v1/admin/federation/licence/install      install the network licence a genesis issued to this frame
  POST /api/v1/admin/federation/licence/{hash}/revoke|suspend|reinstate
  GET  /api/v1/admin/federation/licence/issued       what this registry issued
  GET  /api/v1/admin/federation/licence/status       mode, root, own verdict, every peer's verdict, the last cycle
  POST /api/v1/admin/federation/licence/refresh      run one verdict cycle now (proofs; the worker runs it anyway)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Security
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, security
from agentvault_registry.config import settings
from agentvault_registry.core.federation_auth import require_peer_registry_identity
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.database import get_db
from agentvault_registry.services import federation_licence as fl

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Federation Licence"])

_HASH_RE = r"^[0-9a-f]{64}$"


def _public_name() -> str:
    return (os.environ.get("REGISTRY_FEDERATION_NAME") or getattr(settings, "REGISTRY_NAME", "") or
            fl.local_trust_domain())[:255]


def _public_url() -> str:
    from agentvault_registry.services.registry_card_builder import _public_web_url
    return _public_web_url()


def _is_operator() -> bool:
    return bool((os.getenv("OPERATOR_DID") or "").strip())


# ---------------------------------------------------------------------------------------------------------------------
# public
# ---------------------------------------------------------------------------------------------------------------------

# the same two reads under /api/v1/federation/licence/: a frame's federation proxy (nginx-federation, the mTLS lane its
# peers dial) serves /api/v1/federation/ and three named well-known files only, so a peer's sync worker fetches THESE
@router.get("/.well-known/federation-licence.json")
@router.get("/api/v1/federation/licence/own")
async def well_known_own_licence(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """This registry's network licence, exactly as its card derives it (state, hash, certificate, chain, and on a frame
    its licence-signing public key and operator policy). A peer verifies the certificate itself; the state is only
    this registry's own reading."""
    block = await fl.card_block(db, is_operator=_is_operator())
    return {"trust_domain": fl.local_trust_domain(), "name": _public_name(), **block}


@router.get("/.well-known/federation-licences.json")
@router.get("/api/v1/federation/licence/list")
async def well_known_issued_list(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """The signed list of every licence this registry issued: the revocation source verifiers read. The payload is
    repeated unsigned for humans; a verifier reads the one inside the JWS. An operator issues nothing and creates no key
    (its card key has no passphrase at rest), so it answers 404."""
    if _is_operator():
        raise HTTPException(status_code=404, detail="an operator issues no licences; its frame's list names it")
    if await fl.active_key_jwk(db) is None:
        # a public GET never mints a key: a frame that has issued nothing and holds no licence key has no list to sign
        return {"jws": None, "payload": None, "count": 0,
                "note": "this registry holds no licence key and has issued no licence"}
    jws, payload = await fl.issued_list_jws(db, public_name=_public_name())
    return {"jws": jws, "payload": payload, "count": len(payload.get("licences") or [])}


@router.get("/api/v1/public/federation/licences/{cert_hash}")
async def public_licence_lookup(cert_hash: str = Path(..., pattern=_HASH_RE),
                                db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    row = (await db.execute(
        select(models.FederationLicenceCert).where(
            models.FederationLicenceCert.hash == cert_hash, models.FederationLicenceCert.role == "issued",
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="no licence with that hash was issued by this registry")
    states = await fl.own_issued_states(db)
    return {**fl.cert_row_brief(row), "state": states.get(row.hash, row.state), "certificate": row.jws,
            "issuer_name": _public_name()}


@router.get("/api/v1/federation/licence/verdicts")
async def licence_verdicts() -> Dict[str, Any]:
    """The licence verdict this registry reached about each peer trust domain, its mode, and the domains it refuses.
    Its own TEG copies this and refuses the same domains on the cross-TEG legs (his word 2026-09-28 "cross-teg cut off
    also approved on revoke"), so a revoked or suspended frame is cut off at the TEGs as well as the registries. Not
    secret: every frame publishes its own licence and the genesis publishes the list of every licence it issued."""
    from agentvault_registry.core import mtls_auth
    await mtls_auth.refresh_peer_trust_domains()
    return mtls_auth.licence_verdicts_snapshot()


# ---------------------------------------------------------------------------------------------------------------------
# federation (a frame's own operators)
# ---------------------------------------------------------------------------------------------------------------------

@router.get("/api/v1/federation/licence/mine", dependencies=[Depends(require_mainframe_only)])
async def operator_asks_for_its_licence(
    spiffe_id: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """An operator of THIS frame asks for its licence over mTLS. While this frame's operator policy auto-issues (his
    word: free for now), the first ask issues it; the frame's own network licence and root ride along. A frame whose
    licensing is off (FEDERATION_LICENCE_MODE=off, the source default) answers 409 and issues nothing."""
    if fl.licence_mode() == "off":
        raise HTTPException(status_code=409, detail="licensing is off on this frame (FEDERATION_LICENCE_MODE=off)")
    try:
        answer = await fl.parent_answer_for_operator(db, spiffe_id=spiffe_id, public_name=_public_name())
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    await db.commit()
    return answer


# ---------------------------------------------------------------------------------------------------------------------
# admin
# ---------------------------------------------------------------------------------------------------------------------

_admin = [Security(security.require_admin_flag("admin_federation"))]


class GenesisBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: Optional[str] = Field(None, max_length=500, pattern=r"^https://")


class IssueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["frame", "operator"]
    trust_domain: str = Field(..., min_length=3, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    url: Optional[str] = Field(None, max_length=500, pattern=r"^https://")
    spiffe: Optional[str] = Field(None, max_length=255, pattern=r"^spiffe://")
    key: Optional[Dict[str, Any]] = Field(None, description="frame licences: the frame's licence-signing public key "
                                                             "(an Ed25519 JWK, from its /.well-known/federation-licence.json)")
    plan: str = Field("", max_length=40, description="frame: founding | private | educational | research | non-profit (perpetual) | enterprise | government (365 days); "
                                                    "operator: empty = this frame's operator policy")
    days: Optional[int] = Field(None, ge=1, le=3650, description="empty = the plan's term (enterprise and government 365 days, the others perpetual)")


class InstallBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    certificate: str = Field(..., min_length=64, max_length=8192)
    chain: List[str] = Field(default_factory=list, max_length=4)


class StateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field("", max_length=240)


@router.post("/api/v1/admin/federation/licence/key", dependencies=[Depends(require_mainframe_only), *_admin])
async def licence_key(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """This frame's licence-signing PUBLIC key, created on first call (the private half encrypted at rest). A genesis
    issues this frame's network licence for exactly this key; the frame then installs it."""
    row, _priv = await fl.get_or_create_key(db)
    await db.commit()
    return {"kid": row.kid, "key": dict(row.public_jwk), "trust_domain": fl.local_trust_domain()}


@router.post("/api/v1/admin/federation/licence/genesis", dependencies=[Depends(require_mainframe_only), *_admin])
async def genesis_ceremony(body: Optional[GenesisBody] = None, db: AsyncSession = Depends(get_db),
                           current: models.Developer = Depends(security.get_current_developer)) -> Dict[str, Any]:
    try:
        row, cert = await fl.issue(db, type_="genesis", sub={"url": (body.url if body and body.url else _public_url())},
                                   plan="genesis", days=None, public_name=_public_name(), created_by=current.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.commit()
    logger.warning("[fedlicence] GENESIS CEREMONY: %s self-issued the network root %s (admin %s)",
                   fl.local_trust_domain(), cert.hash, current.id)
    return {"hash": cert.hash, "certificate": cert.jws, "trust_domain": cert.sub_td, "state": "genesis",
            "pin_hint": "FEDERATION_GENESIS_CERT_HASH=" + cert.hash}


@router.post("/api/v1/admin/federation/licence/issue", dependencies=[Depends(require_mainframe_only), *_admin])
async def issue_licence(body: IssueBody, db: AsyncSession = Depends(get_db),
                        current: models.Developer = Depends(security.get_current_developer)) -> Dict[str, Any]:
    sub: Dict[str, Any] = {"trust_domain": body.trust_domain, "name": body.name, "url": body.url, "spiffe": body.spiffe}
    if body.key is not None:
        sub["key"] = body.key
    try:
        row, cert = await fl.issue(db, type_=body.type, sub=sub, plan=body.plan, days=body.days,
                                   public_name=_public_name(), created_by=current.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    root = await fl.get_cert(db, "root")
    await db.commit()
    return {**fl.cert_row_brief(row), "certificate": cert.jws,
            "chain": ([root.jws] if (body.type == "frame" and root is not None) else [])}


@router.post("/api/v1/admin/federation/licence/install", dependencies=[Depends(require_mainframe_only), *_admin])
async def install_licence(body: InstallBody, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Install the network licence a genesis issued to THIS frame. It must name this frame's trust domain and carry
    this frame's own licence key; the chain's root must be a self-signed genesis for the configured network. The
    verdict is recomputed right away and again every cycle."""
    return await _install(db, body.certificate, body.chain)


async def _install(db: AsyncSession, certificate: str, chain: List[str]) -> Dict[str, Any]:
    try:
        row, v = await fl.install_network_licence(db, certificate, chain)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return {"installed": row.hash, "verdict": v.as_dict()}


@router.post("/api/v1/admin/federation/licence/{cert_hash}/{action}",
             dependencies=[Depends(require_mainframe_only), *_admin])
async def change_state(cert_hash: str = Path(..., pattern=_HASH_RE),
                       action: Literal["revoke", "suspend", "reinstate"] = Path(...),
                       body: Optional[StateBody] = None, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    target = {"revoke": "revoked", "suspend": "suspended", "reinstate": "active"}[action]
    try:
        row = await fl.set_issued_state(db, cert_hash, target, (body.reason if body else ""))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.commit()
    logger.warning("[fedlicence] %s licence %s (%s) -> %s", action, row.hash[:16], row.sub_trust_domain, row.state)
    return fl.cert_row_brief(row)


@router.get("/api/v1/admin/federation/licence/issued", dependencies=_admin)
async def list_issued(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    states = await fl.own_issued_states(db)
    rows = await fl.get_certs(db, "issued")
    return {"count": len(rows), "licences": [{**fl.cert_row_brief(r), "state": states.get(r.hash, r.state)} for r in rows]}


@router.get("/api/v1/admin/federation/licence/status", dependencies=_admin)
async def licence_status(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    from agentvault_registry.core import mtls_auth as _mtls  # this worker's trust-check state (None = not refreshed yet)
    root = await fl.get_cert(db, "root")
    peers = (await db.execute(
        select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE")
        .order_by(models.PeerRegistry.name)
    )).scalars().all()
    return {
        "mode": fl.licence_mode(),
        "genesis_trust_domain": fl.genesis_trust_domain() or None,
        "genesis_cert_pin": fl.genesis_cert_pin() or None,
        "local_trust_domain": fl.local_trust_domain(),
        "is_operator": _is_operator(),
        "root": None if root is None else fl.cert_row_brief(root),
        "self": await fl.card_block(db, is_operator=_is_operator()),
        "last_cycle": await fl.read_summary(),
        "verdicts_loaded_by_trust_check": _mtls._LICENCE_VERDICTS_AVAILABLE,
        "peers": [{
            "name": p.name, "trust_domain": p.trust_domain, "peer_type": p.peer_type,
            "licence_state": p.licence_state, "licence_reason": p.licence_reason, "licence_hash": p.licence_hash,
            "licence_checked_at": p.licence_checked_at.isoformat() if p.licence_checked_at else None,
        } for p in peers],
    }


@router.post("/api/v1/admin/federation/licence/refresh", dependencies=_admin)
async def refresh_now(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """One verdict cycle now, through the same code the sync worker runs (proofs need not wait a cycle)."""
    from agentvault_registry.background_tasks.federation_sync import licence_cycle
    return await licence_cycle()
