"""
AGORA PASSPORT — federated participation (§9 of the strategy contract, 2026-06-12).

Lets a federation-trusted agent from ANOTHER registry trade on this venue:

  identity : the agent's HOME registry serves a signed **DevCard v0.1**
             (owner-developer identity; lazy + consent-bound, audited at home).
             The venue verifies the EdDSA signature against the home's already
             federated /.well-known/registry-jwks.json → exchange_participants
             row (verification_source='dev_card') — D25 "no anonymous ghosts"
             extends across the federation.
  orders   : the home registry RELAYS the order over the federation mTLS
             channel (the canary-dispatch transport, peer-vouched by
             require_peer_registry_identity) → the order lands in 'funding'.
  money    : the buyer funds the venue's GATEWAY agent (real local Agent row,
             creds discarded) from home via /teg/send — same-currency message
             rides; cross-frame auto-FX converts at the edge (single-currency
             book preserved). The foreign-funding sweeper opens orders FIFO
             against gateway solvency and moves gateway→escrow through the
             standard mover (exref legs) — I-X3 stays exact.

Flag-gated: EXCHANGE_PASSPORT_ENABLED (default false; frame-c canary true).
Passport P1 scope: BUY limit orders only (sell needs foreign custody of
shares — they have it once they buy; sells then work via the same relay).
Known + documented canary-phase simplification: concurrent underfunded
foreign buys settle FIFO against pooled gateway solvency; overpayment
(FX buffer) parks on the gateway pending reconciliation.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.models import (
    Agent,
    AgentCard,
    ExchangeListing,
    ExchangeOrder,
    ExchangeParticipant,
)
from agentvault_registry.services import exchange_service as svc

logger = logging.getLogger(__name__)

PASSPORT_ENABLED = os.getenv("EXCHANGE_PASSPORT_ENABLED", "false").lower() == "true"
# §2026-06-15 FRAME-SPECIFIC gateway DID (derive from FRAME_CURRENCY). A single
# shared "did:theprotocol:agora-gateway" across A/B/C broke (1) cross-frame
# /teg/send receiver resolution → MultipleResultsFound 500 on cross-frame passport
# funding, and (2) federation card-sync → uix_agent_cards_agent_did dup. Per-frame
# DID resolves uniquely. (Legacy shared-DID gateways stay inert — Δ-neutral.)
# §VENUEGW 2026-08-26 — ONE definition, in exchange_service (which this module already
# imports as `svc`). Two independent copies of a money identity is a drift waiting to
# happen; on a cloud-op the DID is now scoped to the venue that owns the ledger.
GATEWAY_DID = svc.GATEWAY_DID
GATEWAY_DEV_ID = int(os.getenv("EXCHANGE_GATEWAY_DEV_ID", "1"))
PEER_TIMEOUT = float(os.getenv("EXCHANGE_PASSPORT_PEER_TIMEOUT", "15"))
# Batch-H open-rate. Passport buys queue in 'funding' until this sweep opens them
# (one serial escrow-mover leg each). Default 10; bump on passport venues so the
# funding drain keeps pace with the cross-frame buy inflow (the BVT-skew fix).
PASSPORT_SWEEP_BATCH = int(os.getenv("EXCHANGE_PASSPORT_SWEEP_BATCH", "10"))
# §2026-06-17 Batch: cancel passport 'funding' orders whose cross-frame funding
# deposit never landed (gateway short) after this grace window. Without it, an
# underfunded foreign buy sits in 'funding' forever and (with the old FIFO `break`)
# stalled the whole sweep queue. 30-min default: a real gateway→escrow deposit
# completes in seconds; one still unfunded after 30 min never will.
PASSPORT_FUNDING_STALE_SEC = int(os.getenv("EXCHANGE_PASSPORT_FUNDING_STALE_SEC", "1800"))


class PassportError(svc.ExchangeError):
    pass


# ── federation transport (canary-dispatch clone) ─────────────────────────
async def _peer_base(db: AsyncSession, registry_name: str) -> Optional[str]:
    # Env-only per-origin URL map (GCC addressing doctrine): cross-frame targets
    # need the mTLS federation GATEWAY (SVID-terminating), not the public 443 —
    # e.g. EXCHANGE_PASSPORT_URL_MAP={"frame-c": "https://203.0.113.10:31443"}.
    import json as _json

    try:
        umap = _json.loads(os.getenv("EXCHANGE_PASSPORT_URL_MAP", "{}"))
        mapped = umap.get(registry_name) or umap.get(registry_name.lower())
        if mapped:
            return str(mapped).rstrip("/")
    except Exception:
        pass
    from agentvault_registry import models as m

    peers = (
        await db.execute(
            select(m.PeerRegistry).where(func.lower(m.PeerRegistry.name) == registry_name.lower())
        )
    ).scalars().all()
    peer = next((p for p in peers if (p.status or "").upper() == "ACTIVE"), peers[0] if peers else None)
    return peer.base_url.rstrip("/") if peer and peer.base_url else None


def _client_config_for(url: str) -> Tuple[Optional[dict], Optional[str]]:
    """ALWAYS attach the license/secret headers (they authenticate at the app
    layer regardless of transport — public 443 does not terminate client
    certs); add the SVID client cert too when talking to an mTLS gateway."""
    from agentvault_registry.identity import svid_client

    cfg: dict = {"timeout": PEER_TIMEOUT}
    headers: dict = {}
    lic = os.getenv("FEDERATION_LICENSE_KEY", "")
    if lic:
        headers["X-Federation-License"] = lic
    sec = os.getenv("FEDERATION_INTERNAL_SECRET", "")
    if sec:
        headers["X-Federation-Secret"] = sec
    spiffe = svid_client.get_spiffe_id() or ""
    if spiffe:
        headers["X-Federation-SPIFFE-ID"] = spiffe
    if headers:
        cfg["headers"] = headers
    if url.startswith("https://"):
        cc = svid_client.get_client_cert_config(target_url=url)
        if cc:
            cfg.update(cc)
        # SPIRE-issued gateway server certs aren't in the system CA store and
        # cross-domain bundles may not cover them; the mTLS CLIENT cert is the
        # authentication and the env URL map pins the target → FORCE verify=False
        # on mapped gateway targets (override whatever the SVID helper set).
        if os.getenv("EXCHANGE_PASSPORT_URL_MAP"):
            import json as _json

            try:
                if any(str(u).rstrip("/") in url for u in _json.loads(os.getenv("EXCHANGE_PASSPORT_URL_MAP", "{}")).values()):
                    cfg["verify"] = False
            except Exception:
                pass
        # §SIMRUN — AN UNMAPPED HTTPS TARGET USED TO FALL THROUGH TO HTTPX'S DEFAULT,
        # WHICH IS THE SYSTEM CA STORE, AND A SPIRE-ISSUED CERT IS NOT IN IT.
        #
        # Measured 2026-08-27 under a live sim: that was the single largest failure
        # class on the exchange — 16 of 27 failures in a 59-cycle run, every one of
        # them an op->op passport relay dying `CERTIFICATE_VERIFY_FAILED`, eight
        # times more common than the price-band 422 that was actually reported.
        #
        # Two things had to be true at once for it to hide this long:
        #   * `svid_client.get_client_cert_config()` returns **None on every node
        #     measured** (registry-a, frame-c, the cloud-ops — no SPIRE material on
        #     disk, `_initialized=False`), so the branch above never sets `verify`.
        #   * `EXCHANGE_PASSPORT_URL_MAP` covers only the three mainframes on every
        #     op, so `verify=False` masked the gap for exactly the targets people
        #     use by hand, and nothing else.
        #
        # ⚠ The obvious "just verify everywhere" fix would have BROKEN the working
        # path. The mapped entries are RAW IPs (`https://203.0.113.10:8443`) and fail
        # `IP address mismatch, certificate is not valid for '203.0.113.10'` — a
        # HOSTNAME problem, not a CA one. So `verify=False` stays load-bearing there
        # and this only fills in the case nobody chose: setdefault, never override.
        #
        # `get_httpx_verify()` is the fabric context, which trusts the SPIRE bundle
        # AND the public roots. Measured: it verifies 13/13 op venues from op-seoul,
        # and on registry-a this exact call goes ConnectError -> HTTP 422 (i.e. the
        # handshake completes and the request reaches the peer's app layer).
        if "verify" not in cfg:
            from agentvault_registry.es_ssl_helper import get_httpx_verify

            cfg["verify"] = get_httpx_verify()
    return cfg, None


async def peer_request(
    db: AsyncSession, registry_name: str, method: str, path: str, json_body: Optional[dict] = None
) -> Tuple[int, Dict[str, Any]]:
    from agentvault_registry.routers.teg_integration import _to_internal_mtls_url

    base = await _peer_base(db, registry_name)
    if not base:
        raise PassportError(502, f"no ACTIVE peer registry '{registry_name}'")
    url = _to_internal_mtls_url(base) + path
    cfg, err = _client_config_for(url)
    if err:
        raise PassportError(502, err)
    try:
        async with httpx.AsyncClient(**cfg) as c:
            r = await c.request(method, url, json=json_body)
    except httpx.HTTPError as e:
        raise PassportError(502, f"peer '{registry_name}' unreachable: {e}")
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text[:300]}


# ── DevCard verification (AG-20) ─────────────────────────────────────────
async def _home_registry_of(db: AsyncSession, agent_did: str) -> Optional[str]:
    """Origin registry from the federated card mesh (defensive key handling)."""
    card = (
        await db.execute(
            select(AgentCard).where(AgentCard.agent_did == agent_did, AgentCard.is_active.is_(True))
        )
    ).scalars().first()
    if not card or not isinstance(card.card_data, dict):
        return None
    meta = card.card_data.get("federation_metadata") or {}
    return (
        meta.get("origin_registry")
        or meta.get("origin_registry_name")
        or meta.get("source_registry")
        or meta.get("origin")
    )


# ── Home-JWKS cache (AG-20 hardening, §2026-06-16) ────────────────────────
# JWKS signing keys are effectively static, but verify_devcard_envelope() ran
# fetch_home_jwks() over mTLS on EVERY passport order — so a transient empty body
# (a gunicorn/nginx keepalive-reuse race under load) made r.json() throw on a
# zero-byte body and 502'd the WHOLE order, with the failure rate SCALING with
# concurrency. Cache per home (TTL), retry on an empty/transient body, and fall
# back to a stale cached copy rather than failing an order on a blip. Turns a
# per-order fetch (a load-scaling failure surface) into ~one fetch per home/TTL.
_JWKS_CACHE: Dict[str, Tuple[float, list]] = {}      # home -> (expiry_epoch, keys)
_JWKS_TTL_SEC = int(os.getenv("PASSPORT_JWKS_TTL_SEC", "600"))
_JWKS_RETRIES = max(1, int(os.getenv("PASSPORT_JWKS_RETRIES", "2")))


def _invalidate_home_jwks(home: str) -> None:
    """Drop a home's cached JWKS (e.g. after a verify failure → possible key rotation)."""
    _JWKS_CACHE.pop(home, None)


async def fetch_home_jwks(db: AsyncSession, home: str, *, force: bool = False) -> list:
    """Home JWKS over the PUBLIC well-known (no auth required by design).

    Cached per home for _JWKS_TTL_SEC with retry + stale-fallback. ``force=True``
    bypasses the cache read (used to refresh after a verify failure in case the
    home rotated keys). §2026-06-16."""
    from agentvault_registry.routers.teg_integration import _to_internal_mtls_url

    now = time.time()
    cached = _JWKS_CACHE.get(home)
    if not force and cached and cached[0] > now and cached[1]:
        return cached[1]

    base = await _peer_base(db, home)
    if not base:
        if cached and cached[1]:
            return cached[1]                              # stale-fallback over hard-fail
        raise PassportError(502, f"no ACTIVE peer registry '{home}'")
    url = _to_internal_mtls_url(base) + "/.well-known/registry-jwks.json"
    cfg, _ = _client_config_for(url)

    keys: list = []
    last_err: Optional[str] = None
    for _attempt in range(_JWKS_RETRIES):
        try:
            async with httpx.AsyncClient(**(cfg or {"timeout": PEER_TIMEOUT})) as c:
                r = await c.get(url)
            if not (r.text or "").strip():                # the transient empty-200 race
                last_err = f"empty body (HTTP {r.status_code})"
            else:
                keys = (r.json() or {}).get("keys") or []
                if keys:
                    break
                last_err = "no keys in body"
        except Exception as e:                            # noqa: BLE001
            last_err = str(e)
        if _attempt + 1 < _JWKS_RETRIES:
            await asyncio.sleep(0.2)                       # brief backoff before retry

    if keys:
        _JWKS_CACHE[home] = (now + _JWKS_TTL_SEC, keys)
        return keys
    if cached and cached[1]:                              # prefer recent stale over 502-ing the order
        logger.warning("fetch_home_jwks(%s): live fetch failed (%s) — serving stale cached JWKS", home, last_err)
        return cached[1]
    raise PassportError(502, f"home '{home}' JWKS unreachable: {last_err}")


async def verify_devcard_envelope(
    db: AsyncSession, agent_did: str, env: Dict[str, Any], home_hint: Optional[str] = None
) -> Dict[str, Any]:
    """Verify a home-signed DevCard envelope (pushed with the relay or pulled)."""
    from agentvault_registry.services.registry_card_signer_impl import verify_with_jwk

    payload = env.get("payload") or {}
    sig = (env.get("signature") or {}).get("value")
    kid = (env.get("signature") or {}).get("kid")
    if not payload or not sig:
        raise PassportError(403, "DevCard envelope malformed")
    if payload.get("agent_did") != agent_did:
        raise PassportError(403, "DevCard agent_did mismatch")
    home = home_hint or await _home_registry_of(db, agent_did) or payload.get("home_registry")
    if not home:
        raise PassportError(403, f"cannot resolve home registry for {agent_did}")
    keys = await fetch_home_jwks(db, home)
    candidates = [k for k in keys if not kid or k.get("kid") == kid] or keys
    if not any(verify_with_jwk(payload, sig, k) for k in candidates):
        # cached keys may predate a home key-rotation → refresh once and re-verify
        _invalidate_home_jwks(home)
        keys = await fetch_home_jwks(db, home, force=True)
        candidates = [k for k in keys if not kid or k.get("kid") == kid] or keys
        if not any(verify_with_jwk(payload, sig, k) for k in candidates):
            raise PassportError(403, f"DevCard signature INVALID for {agent_did} (home '{home}')")
    return env


async def fetch_and_verify_devcard(db: AsyncSession, agent_did: str) -> Dict[str, Any]:
    """Pull the home-signed DevCard for a foreign agent and verify EdDSA against
    the home's federated JWKS. Returns the verified envelope {payload, signature}."""
    home = await _home_registry_of(db, agent_did)
    if not home:
        raise PassportError(403, f"agent {agent_did} not in the federated card mesh — cannot resolve home registry")

    code, env = await peer_request(db, home, "GET", f"/api/v1/federation/dev-card/by-agent/{agent_did}")
    if code != 200 or "payload" not in env:
        raise PassportError(403, f"home '{home}' DevCard fetch failed (HTTP {code}): {str(env)[:160]}")
    return await verify_devcard_envelope(db, agent_did, env, home_hint=home)


async def ensure_foreign_participant(
    db: AsyncSession, agent_did: str, home_hint: Optional[str] = None,
    dev_card_env: Optional[Dict[str, Any]] = None,
) -> ExchangeParticipant:
    """The §9.2 pipeline: DevCard pull+verify → participant row (auto-created
    account, requirement #2) → verified | blocked (requirement #3)."""
    part = (
        await db.execute(select(ExchangeParticipant).where(ExchangeParticipant.agent_did == agent_did))
    ).scalar_one_or_none()
    if part and part.compliance_status == "verified" and part.verification_source == "dev_card":
        return part  # cached verification (re-pull rides the slow refresh path)

    if dev_card_env is not None:
        env = await verify_devcard_envelope(db, agent_did, dev_card_env, home_hint=home_hint)
    else:
        env = await fetch_and_verify_devcard(db, agent_did)
    p = env["payload"]
    status = "verified" if p.get("standing") == "active" else "blocked"
    now = datetime.now(timezone.utc)
    if part is None:
        part = ExchangeParticipant(agent_did=agent_did)
        db.add(part)
    part.home_registry = home_hint or p.get("home_registry") or "federated"
    part.owner_dev_ref = p.get("developer_ref")
    part.owner_dev_name = p.get("display_name")
    part.owner_dev_contact = p.get("contact_email")
    part.verification_source = "dev_card"
    part.compliance_status = status
    part.kyc = env
    part.verified_at = now if status == "verified" else None
    await db.commit()
    await db.refresh(part)
    if status != "verified":
        raise PassportError(403, f"participant blocked: home standing '{p.get('standing')}'")
    return part


# ── gateway agent (deposit rail terminus) ────────────────────────────────
# §2026-06-15 (V0105) eager gateway federation is OPT-IN + DEFAULT OFF. V0104's
# unconditional fan-out prompted EVERY peer to do a full federation card re-sync
# (≈167-card flare augmentation per peer) just to propagate one tiny no-PII system
# gateway card → disproportionate fleet-wide load. Off by default: the booth hop
# self-heals via periodic sync (≤300s) and the buyer hop rides the V0103 relay
# card-cache. Re-enable only behind a lighter redesign (targeted single-card push).
_EAGER_FED_ENABLED = os.getenv("EXCHANGE_GATEWAY_EAGER_FEDERATION", "false").lower() == "true"
_EAGER_FED_TASKS: set = set()


async def _eager_federate_gateway() -> None:
    """§2026-06-15 EAGER FEDERATION (V0104) — best-effort, one-time: prompt every active
    peer to pull our cards (incl. the just-created frame-specific gateway) so buyer ops
    AND their FX-origination (booth) frames resolve it on the FIRST funding send,
    eliminating the ≤300s cold-start (the buyer "unknown receiver" 409 — also fixed
    buyer-side in V0103 — and the FX-booth "cannot resolve <gw> from this frame" 409).
    Reuses /federation/sync/trigger (the peer pulls only from us via peer_name; the
    endpoint dual-auths our federation mTLS). Sequential + per-peer best-effort, in its
    OWN session (the request's db is gone — this runs fire-and-forget after the relay)."""
    try:
        from agentvault_registry.crud import crud_peer_registry
        from agentvault_registry.database import AsyncSessionLocal
        from agentvault_registry.routers.federation_sync import _get_display_name

        async with AsyncSessionLocal() as db:
            my_name = await _get_display_name(db)
            peers = await crud_peer_registry.list_active_peer_registries_all(db, skip=0, limit=1000)
            poked = 0
            for p in peers:
                try:
                    await peer_request(db, p.name, "POST", "/api/v1/federation/sync/trigger", {"peer_name": my_name})
                    poked += 1
                except Exception:
                    pass  # one unreachable/rate-limited peer must not stop the fan-out
            logger.info("[AGORA-passport] eager-federated gateway %s: poked %d/%d peers", GATEWAY_DID, poked, len(peers))
    except Exception as e:  # never let a federation hiccup escape to the caller
        logger.warning("[AGORA-passport] eager gateway federation failed: %s", e)


def _gateway_public_url() -> str:
    base = (os.getenv("BASE_URL", "") or "").strip().rstrip("/")
    low = base.lower()
    if not base or "localhost" in low or "127.0.0.1" in low or "://0.0.0.0" in low:
        return f"https://theprotocol.cloud/agora/{GATEWAY_DID.rsplit(':', 1)[-1]}"
    return f"{base}/api/v1/agora"


def _gateway_card_data() -> Dict[str, Any]:
    """The gateway's card, CONFORMANT to the canonical A2A AgentCard schema.

    🔴 §VENUEGW 2026-08-26 — it used to be a five-field stub (name/description/did/
    agora_gateway/version). A registry running FEDERATION_INGEST_FAIL_CLOSED=true
    validates every inbound peer card against that schema and QUARANTINES what does
    not conform — so the stub was silently dropped on ingest and the buyer could never
    learn the gateway's address. The control was right; our own card was wrong. It went
    unnoticed because the frame-wide gateway cards predate the flag; giving each venue a
    NEW gateway DID made every op a first ingest, and every one was refused.
    """
    return {
        "protocolVersion": "0.3.0",
        "humanReadableId": f"agora/{GATEWAY_DID.rsplit(':', 1)[-1]}",
        "agentVersion": "1.0.0",
        "name": "AGORA Deposit Gateway",
        "description": (
            "Deposit terminus for federated (Passport) traders on this AGORA market, "
            "with funds sweeping to the market escrow."
        ),
        # ⚠ a cloud-op's baked BASE_URL default is http://localhost:8000 — TRUTHY, so a
        # plain falsy-guard passes it straight through. The gateway is a ledger account,
        # not a callable endpoint; the schema just wants a URL, so refuse loopback and
        # fall back to something stable rather than publishing someone's own loopback.
        "url": _gateway_public_url(),
        "provider": {"name": "AGORA", "url": "https://theprotocol.cloud"},
        "capabilities": {"streaming": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{
            "id": "agora-deposit",
            "name": "AGORA deposit",
            "description": "Receives cross-frame passport funding for this market.",
        }],
        "authSchemes": [{"scheme": "none"}],
        "did": GATEWAY_DID,
        "agora_gateway": True,
        "version": "1.0",
    }


GATEWAY_ROLE = "gateway"


async def ensure_gateway_role(db: AsyncSession, did: str = GATEWAY_DID) -> bool:
    """§GATEWAYROLE (2026-09-24): the gateway signs every repatriation AS ITSELF, so under IRONKEY enforce it needs
    a role carrying teg.transfer + teg.transfer_xreg and nothing else: `gateway`. Every gateway was born with NO
    grant (ensure_gateway never gave one), so every cross-frame repatriation was refused; measured on the sandbox
    pair, 6,876 credits parked as failed in two days, and the same gap latent on EU and ASIA.

    Idempotent. When the gateway exists and its live role set is anything other than exactly {gateway}, it becomes
    exactly that: a stopgap role a person granted (canary) is retired, an expiring or expired gateway grant is
    replaced by a permanent one. Bare-permission grants are untouched. Returns True when it changed the grants;
    the caller commits. A gateway that does not exist yet is left alone (no grant for a DID with no agent)."""
    if (await db.execute(text("SELECT 1 FROM agents WHERE did = :did"), {"did": did})).first() is None:
        return False
    live = set((await db.execute(text(
        "SELECT value FROM agent_role_grants WHERE agent_did = :did AND grant_type = 'role' "
        "AND (expires_at IS NULL OR expires_at > now())"), {"did": did})).scalars().all())
    permanent = (await db.execute(text(
        "SELECT 1 FROM agent_role_grants WHERE agent_did = :did AND grant_type = 'role' "
        "AND value = :role AND expires_at IS NULL"), {"did": did, "role": GATEWAY_ROLE})).first() is not None
    if live == {GATEWAY_ROLE} and permanent:
        return False
    await db.execute(text(
        "DELETE FROM agent_role_grants WHERE agent_did = :did AND grant_type = 'role' "
        "AND NOT (value = :role AND expires_at IS NULL)"), {"did": did, "role": GATEWAY_ROLE})
    await db.execute(text(
        "INSERT INTO agent_role_grants (agent_did, grant_type, value, granted_by_dev_id, expires_at) "
        "VALUES (:did, 'role', :role, NULL, NULL) ON CONFLICT (agent_did, grant_type, value) DO NOTHING"),
        {"did": did, "role": GATEWAY_ROLE})
    logger.warning("[AGORA-passport] gateway %s held roles %s; now exactly [%s] (§GATEWAYROLE)",
                   did, sorted(live) or "none", GATEWAY_ROLE)
    return True


async def ensure_gateway(db: AsyncSession) -> str:
    agent = (await db.execute(select(Agent).where(Agent.did == GATEWAY_DID))).scalar_one_or_none()
    if agent:
        # The agent exists, but its CARD may still be the pre-§VENUEGW stub — and a stub
        # is quarantined by every fail-closed peer, which leaves this venue unreachable
        # while looking fine locally. Heal on the hot path; it is one indexed read.
        _existing = (
            await db.execute(select(AgentCard).where(AgentCard.agent_did == GATEWAY_DID))
        ).scalar_one_or_none()
        if _existing is not None and not (_existing.card_data or {}).get("skills"):
            _existing.card_data = _gateway_card_data()
            await db.commit()
            logger.info("[AGORA-passport] upgraded stub gateway card to A2A-conformant: %s", GATEWAY_DID)
        # §GATEWAYROLE: heal the gateway's authority on the same hot path (two indexed reads when it is right).
        if await ensure_gateway_role(db):
            await db.commit()
        return GATEWAY_DID
    import secrets as _secrets

    from agentvault_registry.security import hash_password

    db.add(
        Agent(
            did=GATEWAY_DID,
            client_id=f"agora-gateway-{_secrets.token_hex(4)}",
            hashed_client_secret=hash_password(f"tp_secret_{_secrets.token_hex(32)}"),
            creator_developer_id=GATEWAY_DEV_ID,
            status="active",
        )
    )
    await db.flush()
    # §GATEWAYROLE: born with its role, committed with the agent below.
    await ensure_gateway_role(db)
    # §2026-06-15 idempotency: an ORPHAN gateway card (card present but agent absent —
    # e.g. the agent was swept by the V0052 card-GC while the card survived) collides
    # with uix_agent_cards_agent_did on a blind insert → 409 DUPLICATE_ENTRY fails the
    # WHOLE inbound passport order. Adopt the existing card; only create when missing.
    _gw_card = (
        await db.execute(select(AgentCard).where(AgentCard.agent_did == GATEWAY_DID))
    ).scalar_one_or_none()
    if _gw_card is not None and not (_gw_card.card_data or {}).get("skills"):
        # An older stub card is already here (created before this fix). Upgrade it in
        # place — otherwise this venue stays un-ingestable on every fail-closed peer.
        _gw_card.card_data = _gateway_card_data()
        logger.info("[AGORA-passport] upgraded stub gateway card to A2A-conformant: %s", GATEWAY_DID)
    if _gw_card is None:
        db.add(
            AgentCard(
                id=uuid.uuid4(),
                developer_id=GATEWAY_DEV_ID,
                agent_did=GATEWAY_DID,
                card_data=_gateway_card_data(),
                name="AGORA Deposit Gateway",
                description="AGORA Passport deposit gateway",
                is_active=True,
            )
        )
    await db.commit()
    logger.info("[AGORA-passport] gateway agent created: %s", GATEWAY_DID)
    # Eager-federate the brand-new gateway to peers — OPT-IN, DEFAULT OFF (see
    # _EAGER_FED_ENABLED above; V0104's unconditional fan-out caused fleet-wide
    # federation-sync load). When off, the booth hop self-heals via periodic sync
    # (≤300s) and the buyer hop rides the V0103 relay card-cache.
    if _EAGER_FED_ENABLED:
        try:
            import asyncio as _aio

            _t = _aio.create_task(_eager_federate_gateway())
            _EAGER_FED_TASKS.add(_t)
            _t.add_done_callback(_EAGER_FED_TASKS.discard)
        except Exception as _e:
            logger.warning("[AGORA-passport] eager gateway federation not scheduled: %s", _e)
    return GATEWAY_DID


async def gateway_balance() -> Decimal:
    """Gateway TEG balance via the exchange-admin TEG surface."""
    from agentvault_registry.services.exchange_service import TEG_ADMIN_API_KEY, TEG_API_BASE_URL, TEG_API_V1_PREFIX
    from agentvault_registry.es_ssl_helper import get_httpx_verify

    async with httpx.AsyncClient(verify=get_httpx_verify()) as c:
        r = await c.get(
            f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/admin/exchange/balance/{GATEWAY_DID}",
            headers={"Authorization": f"Bearer {TEG_ADMIN_API_KEY}"},
            timeout=10.0,
        )
    if r.status_code != 200:
        raise PassportError(502, f"gateway balance probe {r.status_code}")
    return Decimal(str(r.json()["balance"]))


# ── federated order acceptance (venue side, AG-21) ───────────────────────
async def accept_federated_vote(
    db: AsyncSession, peer_spiffe: str, body: Dict[str, Any]
) -> Dict[str, Any]:
    """§2026-06-22 cross-frame shareholder vote relay (VENUE side — the listing's home frame).
    The foreign holder's HOME registry authenticated the agent and vouches via peer mTLS
    (peer_spiffe); we record the vote against THIS venue's FROZEN snapshot weight, stamping the
    home frame as voter_registry_id. The voter need not exist locally — enfranchisement is by
    snapshot membership (agent_did, globally unique). Mirrors the federation-governance vote
    receive. Δ-irrelevant (governance moves no money)."""
    if os.getenv("EXCHANGE_CROSSFRAME_VOTE_ENABLED", "false").lower() not in ("1", "true", "yes"):
        raise svc.ExchangeError(503, "cross-frame AGORA voting disabled on this market (EXCHANGE_CROSSFRAME_VOTE_ENABLED=false)")
    proposal_id = str(body.get("proposal_id") or "")
    voter_did = str(body.get("voter_did") or "")
    if not proposal_id or not voter_did:
        raise svc.ExchangeError(422, "proposal_id and voter_did required")
    in_favor = bool(body.get("in_favor"))
    reason = body.get("reason")
    return await svc.cast_share_vote(
        db, voter_did, proposal_id, in_favor, reason, voter_registry_id=peer_spiffe
    )


async def accept_federated_order(
    db: AsyncSession, peer_spiffe: str, body: Dict[str, Any]
) -> Dict[str, Any]:
    if not PASSPORT_ENABLED:
        raise PassportError(503, "AGORA Passport disabled on this market (EXCHANGE_PASSPORT_ENABLED=false)")
    await svc._require_venue_open(db)

    agent_did = str(body.get("agent_did") or "")
    listing_ref = str(body.get("listing") or "")
    side = str(body.get("side") or "buy")
    qty = int(body.get("qty") or 0)
    price = Decimal(str(body.get("price") or "0"))
    if qty <= 0 or price <= 0:
        raise PassportError(422, "qty and price must be > 0")
    if side == "sell":
        # §2026-06-20 PASSPORT SELL (bidirectional): the foreign agent sells shares it
        # ALREADY holds on this venue (custody = its OrgSharePosition from prior passport
        # buys). NO gateway funding — proceeds repatriate home via the gateway-credit rail
        # in settle_pending_trades (_foreign_home → _add_gateway_credit → repat worker,
        # reverse FX). Delegate to the local place_order so custody-check + share-lock +
        # match are reused verbatim; place_order.ensure_participant is a no-op for an
        # (Agent-row-absent) dev-card-verified foreign seller, so the dev_card participant
        # — which _foreign_home keys on — is preserved.
        await ensure_foreign_participant(db, agent_did, dev_card_env=body.get("dev_card"))
        try:
            placed = await svc.place_order(
                db, agent_did, listing_ref, "sell", "limit", qty, price=price,
                client_order_id=f"psell:{peer_spiffe.split('/')[-1][:20]}:{uuid.uuid4().hex[:8]}",
            )
        except svc.ExchangeError as e:
            raise PassportError(e.status_code, e.detail)
        o = placed.order
        logger.info("[AGORA-passport] federated SELL %s accepted from %s via %s (status=%s)", o.id, agent_did, peer_spiffe, o.status)
        return {
            "order_id": o.id, "status": o.status, "side": "sell",
            "required_amount": "0", "currency": os.getenv("FRAME_CURRENCY", "AVT"),
            "gateway_did": GATEWAY_DID, "remaining": str(o.remaining),
            "note": "passport sell — proceeds repatriate home via gateway credit on fill",
        }
    if side != "buy":
        raise PassportError(422, f"unsupported passport side {side}")

    listing = await svc._get_listing(db, listing_ref)
    if listing.status != "trading" or not listing.approved:
        raise PassportError(409, f"listing not trading (status={listing.status})")

    await ensure_foreign_participant(db, agent_did, dev_card_env=body.get("dev_card"))
    gateway = await ensure_gateway(db)

    # Same guards as local placement (band/tick/notional).
    last = await svc._last_price(db, listing.id)
    if (price % listing.tick) != svc.ZERO:
        raise PassportError(422, f"price must be a multiple of tick {listing.tick}")
    if last is not None:
        lo, hi = svc._band_bounds(last, listing.band_pct)
        if not (lo <= price <= hi):
            raise PassportError(422, f"price outside ±{listing.band_pct}% band around {last}")
    escrow = svc.q18(price * Decimal(qty))
    if escrow > svc.MAX_ORDER_NOTIONAL:
        raise PassportError(422, f"max notional {svc.MAX_ORDER_NOTIONAL}")

    order = ExchangeOrder(
        listing_id=listing.id,
        agent_did=agent_did,
        side="buy",
        order_type="limit",
        price=price,
        qty=qty,
        remaining=qty,
        escrow_amount=escrow,
        status="funding",
        client_order_id=f"passport:{peer_spiffe.split('/')[-1][:20]}:{uuid.uuid4().hex[:8]}",
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    logger.info("[AGORA-passport] federated order %s accepted from %s via %s", order.id, agent_did, peer_spiffe)

    # §2026-06-15 COLD-START FIX: return the (frame-specific, lazily-created V0102)
    # gateway card so the HOME/buyer can cache it BEFORE its cross-frame funding
    # /teg/send. The per-frame gateway is created on first inbound order and is not
    # yet federated → the buyer's send-resolver would 409 "unknown receiver" until
    # the next periodic federation sync (≤300s). Shaped like the federation export's
    # AgentCardSyncData so the buyer upserts it via upsert_agent_cards_from_peer.
    # Best-effort: any failure just omits the card → buyer self-heals via sync.
    gateway_card_export = None
    try:
        gw_row = (
            await db.execute(select(AgentCard).where(AgentCard.agent_did == gateway))
        ).scalar_one_or_none()
        if gw_row is not None:
            from agentvault_registry.identity import svid_client
            from agentvault_registry.routers.federation_sync import _get_display_name
            _sp = svid_client.get_spiffe_id() or ""
            _disp = await _get_display_name(db)
            _cd = dict(gw_row.card_data or {})
            _cd.setdefault("did", gateway)
            _fm = dict(_cd.get("federation_metadata") or {})
            _fm.setdefault("origin_registry_name", _disp)
            if _sp:
                _fm.setdefault("spiffe_id", _sp)
                _fm.setdefault("source_registry", _sp)
            _cd["federation_metadata"] = _fm
            # §DARKSYNC (2026-09-22): a dark gateway stays dark on the buyer (its upsert stores the mirror unlisted)
            _gw_dark = bool(getattr(gw_row, "unlisted", False))
            if _gw_dark:
                from agentvault_registry.services import listing_propagation as _lp
                _cd = _lp.inject_extension(_cd, _lp.tombstone_state(gw_row.updated_at))
            gateway_card_export = {
                "unlisted": _gw_dark,
                "id": str(gw_row.id),
                "developer_id": gw_row.developer_id,
                "card_data": _cd,
                "name": gw_row.name,
                "description": gw_row.description,
                "is_active": True,
                "updated_at": (gw_row.updated_at or datetime.now(timezone.utc)).isoformat(),
            }
    except Exception as _gwe:
        logger.warning("[AGORA-passport] gateway card export skipped: %s", _gwe)

    return {
        "order_id": order.id,
        "status": order.status,
        "required_amount": str(escrow),
        "currency": listing.currency,
        "gateway_did": gateway,
        "gateway_card": gateway_card_export,
        "funding_note": f"send >= required_amount (in {listing.currency}-equivalent via /teg/send) to gateway_did; the sweeper opens the order FIFO on arrival",
    }


def _reserve_repat_enabled() -> bool:
    """Gate (default OFF): when on, sweep_foreign_funding reserves outstanding repat
    obligations so order-funding never spends money owed to pending refunds/dividends —
    the source-side half of the gateway-solvency fix (pairs with gateway_float_keeper)."""
    return (os.getenv("EXCHANGE_PASSPORT_RESERVE_REPAT", "false") or "false").strip().lower() in ("1", "true", "yes", "on")


async def _outstanding_repat_obligations(db: AsyncSession) -> Decimal:
    """Repat obligations owed by THIS venue's gateway: every credit still owed, of every size (the float keeper's
    `_obligations`, the same population: §REPATLANE V0603 counts the fragments and the credits claimed for a send).
    Reserved out of gateway liquidity before funding new passport orders so a refund/dividend
    repatriation is never starved by order-funding spend (the gateway-dry / stranded-refund class)."""
    from agentvault_registry.models import ExchangeGatewayCredit
    v = (await db.execute(
        select(func.coalesce(func.sum(ExchangeGatewayCredit.amount), 0)).where(
            ExchangeGatewayCredit.status.in_(svc.REPAT_OWED_STATUSES),
        )
    )).scalar_one()
    return svc.q18(Decimal(str(v or 0)))


async def sweep_foreign_funding(db: AsyncSession, batch: Optional[int] = None,
                                deadline: Optional[float] = None) -> int:
    """Worker batch H: open passport 'funding' orders FIFO against gateway
    solvency. Money leg = standard mover gateway→escrow (exref) → I-X3 exact.
    `batch` defaults to EXCHANGE_PASSPORT_SWEEP_BATCH; an optional monotonic
    `deadline` bounds the serial-mover inner loop so a larger batch self-limits
    within the worker's cycle budget (no lease over-run, no escrow-row over-contention).
    Per-order money logic is unchanged — bigger batch = more opens per cycle only."""
    if not PASSPORT_ENABLED:
        return 0
    if batch is None:
        batch = PASSPORT_SWEEP_BATCH
    rows = (
        await db.execute(
            select(ExchangeOrder)
            .where(ExchangeOrder.status == "funding", ExchangeOrder.client_order_id.like("passport:%"))
            .order_by(ExchangeOrder.created_at.asc())
            .limit(batch)
        )
    ).scalars().all()
    if not rows:
        return 0
    try:
        bal = await gateway_balance()
    except PassportError as e:
        logger.warning("[AGORA-passport] sweep skipped: %s", e.detail)
        return 0
    # §2026-06-19 repat-reserve: hold back outstanding repat obligations so order-funding
    # can't spend money owed to pending refunds/dividends (the gateway-dry root cause).
    reserve = Decimal("0")
    if _reserve_repat_enabled():
        try:
            reserve = await _outstanding_repat_obligations(db)
        except Exception as _re:
            logger.warning("[AGORA-passport] repat-reserve read failed (%s) — funding without reserve this cycle", _re)
            reserve = Decimal("0")
    done = 0
    for o in rows:
        if deadline is not None and time.monotonic() > deadline:
            break  # cycle budget spent — remaining funded orders open next cycle (FIFO preserved, exref-idempotent)
        if (bal - reserve) < o.escrow_amount:
            continue  # §2026-06-17: SKIP an uncoverable order so coverable ones behind it still open. Was `break`, which let a single underfunded foreign buy stall the entire FIFO queue indefinitely. §2026-06-19: `- reserve` keeps outstanding repat obligations (pending refunds/dividends) un-spent so order-funding can't starve a repatriation; gateway_float_keeper tops the gateway to cover the rest. Permanently-unfunded orders are cleared by expire_stale_funding (below); scan stays bounded by `limit batch` + `deadline`.
        try:
            await svc.mover.move(GATEWAY_DID, svc.EXCHANGE_ESCROW_SENTINEL, o.escrow_amount, "passport_deposit", f"ord-{o.id}:dep")
        except svc.ExchangeError as e:
            logger.warning("[AGORA-passport] deposit sweep for %s failed: %s", o.id, e.detail)
            break
        bal -= o.escrow_amount
        listing = (
            await db.execute(select(ExchangeListing).where(ExchangeListing.id == o.listing_id))
        ).scalar_one()
        await svc._listing_lock(db, o.listing_id)
        await db.refresh(o)
        if o.status != "funding":
            await db.commit()
            continue
        o.status = "open"
        fills = await svc._match(db, listing, o, taker_cap=o.price)
        await db.commit()
        for t in fills:
            svc._emit(
                "ExchangeTradeExecuted",
                listing.id,
                {
                    "trade_id": t.id, "seq": str(t.seq), "symbol": listing.symbol,
                    "price": str(t.price), "qty": str(t.qty), "notional": str(t.notional),
                    "buyer_did": t.buyer_did, "seller_did": t.seller_did, "currency": listing.currency,
                },
                key=f"exchange-trade:{t.id}",
            )
        done += 1
        logger.info("[AGORA-passport] order %s funded+opened (%d fills)", o.id, len(fills))
    return done


async def expire_stale_funding(db: AsyncSession, batch: int = 200,
                               deadline: Optional[float] = None) -> int:
    """Worker batch: cancel passport 'funding' orders whose cross-frame funding
    deposit never landed (the foreign buyer's /teg/send failed) and that have sat
    longer than PASSPORT_FUNDING_STALE_SEC.

    Δ-NEUTRAL by construction: a 'funding' order holds NO real @exchange_escrow
    money (compute_invariants excludes status='funding' from expected escrow), so
    we flip status→cancelled AND set escrow_refunded=escrow_amount, making
    held = escrow_amount − matched_notional − escrow_refunded = 0. That keeps the
    order invisible to refund_terminal_buys, so NO escrow→buyer leg fires (a leg
    would drain other orders' escrow → I-X3 breach). No money moves; Δ unchanged.

    This is the cleanup half of the §2026-06-17 fix; sweep_foreign_funding (above)
    now `continue`s past uncoverable orders so genuinely-funded buys open first —
    expire_stale_funding only ever reaches the permanently-unfunded remainder."""
    if not PASSPORT_ENABLED:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=PASSPORT_FUNDING_STALE_SEC)
    rows = (
        await db.execute(
            select(ExchangeOrder)
            .where(
                ExchangeOrder.status == "funding",
                ExchangeOrder.client_order_id.like("passport:%"),
                ExchangeOrder.created_at < cutoff,
            )
            .order_by(ExchangeOrder.created_at.asc())
            .limit(batch)
        )
    ).scalars().all()
    done = 0
    for o in rows:
        if deadline is not None and time.monotonic() > deadline:
            break  # cycle budget spent — the rest cancel next cycle (idempotent)
        await svc._listing_lock(db, o.listing_id)
        await db.refresh(o)
        if o.status != "funding":  # raced (opened by the sweep / already cancelled)
            await db.commit()
            continue
        o.status = "cancelled"
        o.escrow_refunded = o.escrow_amount  # held→0: no real escrow held, no refund leg
        o.reject_reason = "passport funding deposit never landed (stale); cancelled, no escrow held"[:255]
        await db.commit()
        done += 1
    if done:
        logger.info("[AGORA-passport] expired %d stale unfunded 'funding' orders", done)
    return done


# ═══ §PASSPORTSELL P1 (2026-08-22) — read-only federation views for fill-tracking ═══
# The HOME registry's sim/agents credit passport holdings on CONFIRMED fills, never on
# the relay's 200 (acceptance is not a fill; a 'funding' buy may never land). These two
# views are the truth source: order status for the fill poller, portfolio for the
# restart-proof holdings rebuild. Peer-mTLS trust tier == placing the order; results
# are scoped to the vouched agent_did. NO money moves here.


async def federated_order_status(
    db: AsyncSession, peer_spiffe: str, body: Dict[str, Any]
) -> Dict[str, Any]:
    if not PASSPORT_ENABLED:
        raise PassportError(503, "AGORA Passport disabled on this market (EXCHANGE_PASSPORT_ENABLED=false)")
    from agentvault_registry.models import ExchangeListing, ExchangeOrder

    agent_did = str(body.get("agent_did") or "").strip()
    order_ids = [str(o)[:64] for o in (body.get("order_ids") or []) if o][:50]
    if not agent_did or not order_ids:
        raise PassportError(422, "agent_did and order_ids[] required")
    rows = (
        await db.execute(
            select(ExchangeOrder, ExchangeListing.symbol)
            .join(ExchangeListing, ExchangeListing.id == ExchangeOrder.listing_id)
            .where(ExchangeOrder.agent_did == agent_did, ExchangeOrder.id.in_(order_ids))
        )
    ).all()
    seen = set()
    out = []
    for o, symbol in rows:
        seen.add(str(o.id))
        qty = int(o.qty or 0)
        remaining = int(o.remaining or 0)
        out.append({
            "order_id": str(o.id), "listing": symbol, "side": o.side, "status": o.status,
            "qty": qty, "remaining": remaining, "filled_qty": max(0, qty - remaining),
            "reject_reason": o.reject_reason,
            "updated_at": o.updated_at.isoformat() if o.updated_at else None,
        })
    return {"agent_did": agent_did, "orders": out,
            "missing": [i for i in order_ids if i not in seen]}


async def federated_certificate(
    db: AsyncSession, peer_spiffe: str, body: Dict[str, Any]
) -> Dict[str, Any]:
    """§CERTEVERYBUY — mint a share certificate for a FEDERATED holder, here.

    THE RULE THIS EXISTS TO KEEP: a certificate is a signed statement about a
    cap table, so only the registry that HOLDS that cap table may sign one.
    A passport buy leaves the shares on THIS venue's register, so the buyer's
    home registry cannot honestly attest to them — it has no such row, and
    minting one from a relayed number would be a registry signing a claim about
    somebody else's books. So the home relays here, and what travels back is
    THIS venue's signature, verifiable against THIS venue's published pubkey.

    Same gate as every other passport read: the peer registry is the voucher.
    Holding nothing refuses BY NAME (404), never an empty certificate."""
    if not PASSPORT_ENABLED:
        raise PassportError(503, "AGORA Passport disabled on this market (EXCHANGE_PASSPORT_ENABLED=false)")
    from agentvault_registry.config import settings as _st
    from agentvault_registry.services.share_certificate import build_certificate

    agent_did = str(body.get("agent_did") or "").strip()
    symbol = str(body.get("symbol") or "").strip()
    if not agent_did or not symbol:
        raise PassportError(422, "agent_did and symbol required")
    cert = await build_certificate(db, agent_did, symbol,
                                   getattr(_st, "REGISTRY_NAME", "") or "")
    if cert is None:
        # Not an error condition to hide: the home side polls until the relayed
        # order actually fills, and "not yet" is the honest answer meanwhile.
        raise PassportError(404, f"{agent_did} holds no {symbol.upper()} on this market")
    return {"certificate": cert}


async def federated_portfolio(
    db: AsyncSession, peer_spiffe: str, body: Dict[str, Any]
) -> Dict[str, Any]:
    if not PASSPORT_ENABLED:
        raise PassportError(503, "AGORA Passport disabled on this market (EXCHANGE_PASSPORT_ENABLED=false)")
    from agentvault_registry.models import ExchangeListing, OrgSharePosition

    agent_did = str(body.get("agent_did") or "").strip()
    if not agent_did:
        raise PassportError(422, "agent_did required")
    rows = (
        await db.execute(
            select(OrgSharePosition, ExchangeListing.symbol)
            .join(ExchangeListing, ExchangeListing.id == OrgSharePosition.listing_id)
            .where(OrgSharePosition.agent_did == agent_did)
        )
    ).all()
    return {"agent_did": agent_did, "positions": [
        {"symbol": symbol, "qty": int(p.qty or 0), "locked_qty": int(p.locked_qty or 0),
         "free": max(0, int(p.qty or 0) - int(p.locked_qty or 0))}
        for p, symbol in rows
    ]}
