"""
Sandbox bootstrap — frame-pair seeding.

Scope (intentionally minimal, per Commander 2026-04-21):
  - Creates/updates the bidirectional peer_registries row linking THIS sandbox
    frame to its sibling (A → B or B → A, detected from REGISTRY_NAME).
  - Creates/updates a "completed" frame_invitations row marking the WS3
    handshake as done (so FrameManagement.vue doesn't show stale "pending"
    state on boot).
  - Calls the sandbox EventStore admin API to seed:
      * federation_operators (self + partner, for governance trust weighting)
      * cross_frame_peers (SF-4 cross-frame event replication)

Explicitly OUT OF SCOPE (deferred to a later operator-provisioning sprint):
  - Operator peer_registries rows (sandbox operators come LAST, after
    cross-frame tests pass; Commander: "huge identity and trust issues"
    otherwise).
  - operator_applications, federation_licenses.
  - Granular admin-flag sub-accounts in `developers` (Appendix E.8).

Idempotency contract:
  - Every DB op is guarded by a pre-check (SELECT before INSERT).
  - Every EventStore call accepts 409 Conflict as "already exists".
  - Any unexpected error is logged + swallowed (non-fatal for startup).

Invoke:
  PYTHONPATH=/app/src python -m agentvault_registry.sandbox_bootstrap
"""

import asyncio
import datetime
import logging
import os
import sys
from typing import Optional
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from agentvault_registry import models
from agentvault_registry.config import settings

logger = logging.getLogger("sandbox_bootstrap")
logging.basicConfig(
    level=logging.INFO,
    format="[sandbox_bootstrap] %(levelname)s: %(message)s",
)

# ----------------------------------------------------------------------------
# Frame-pair topology (hardcoded — this script runs only in sandbox registry
# containers where the topology is known a priori).
# ----------------------------------------------------------------------------

REGISTRY_NAME = os.getenv("REGISTRY_NAME", "")
SANDBOX_A = "Registry-Test"       # compose REGISTRY_NAME value for frame A
SANDBOX_B = "Registry-Test-B"     # compose REGISTRY_NAME value for frame B

# Internal Docker-network URLs for each sandbox frame's registry + eventstore.
SANDBOX_A_BASE_URL = "http://registry-test:8000"
SANDBOX_B_BASE_URL = "http://registry-test-b:8000"
# §TRUSTCHAIN P4.6: these named the OLD sandbox tier (torn down at §BATCH3). A bootstrap of that
# tier is not something this tree can run any more; the values are read from the environment so no
# dead hostname is baked into a peer row, and empty when nobody set them.
SANDBOX_A_ES_URL = os.getenv("SANDBOX_A_ES_URL", "")
SANDBOX_B_ES_URL = os.getenv("SANDBOX_B_ES_URL", "")

# SPIRE trust domains (matches Phase 2 configs + Phase 3 compose env).
TRUST_DOMAIN_A = "sandbox-a.test"
TRUST_DOMAIN_B = "sandbox-b.test"

# SPIFFE bundle endpoints (container-internal, reached via Docker DNS on
# sandbox-identity bridge).
BUNDLE_ENDPOINT_A = "https://sandbox-a-spire-server:8443"
BUNDLE_ENDPOINT_B = "https://sandbox-b-spire-server:8443"

# EventStore admin API key (matches `INTERNAL_API_KEY` on both sandbox ES).
ES_INTERNAL_KEY = os.getenv(
    "EVENT_STORE_API_KEY", "sandbox-event-store-api-key-2026"
)


def _pair_context() -> Optional[dict]:
    """Returns topology context for whichever sandbox frame we're running as.
    None if REGISTRY_NAME isn't one of the sandbox values (not our job)."""
    if REGISTRY_NAME == SANDBOX_A:
        return {
            "self_frame": "A",
            "self_name": "Sandbox-A",
            "self_td": TRUST_DOMAIN_A,
            "self_es_url": SANDBOX_A_ES_URL,
            "peer_name": "Sandbox-B",
            "peer_base_url": SANDBOX_B_BASE_URL,
            "peer_es_url": SANDBOX_B_ES_URL,
            "peer_td": TRUST_DOMAIN_B,
            "peer_bundle_endpoint": BUNDLE_ENDPOINT_B,
        }
    if REGISTRY_NAME == SANDBOX_B:
        return {
            "self_frame": "B",
            "self_name": "Sandbox-B",
            "self_td": TRUST_DOMAIN_B,
            "self_es_url": SANDBOX_B_ES_URL,
            "peer_name": "Sandbox-A",
            "peer_base_url": SANDBOX_A_BASE_URL,
            "peer_es_url": SANDBOX_A_ES_URL,
            "peer_td": TRUST_DOMAIN_A,
            "peer_bundle_endpoint": BUNDLE_ENDPOINT_A,
        }
    return None


# ----------------------------------------------------------------------------
# DB seeding (runs against the local registry DB).
# ----------------------------------------------------------------------------

async def _get_admin_dev_id(session: AsyncSession) -> Optional[int]:
    """Return dev_id of the sandbox admin account (seeded by test_seed)."""
    result = await session.execute(
        select(models.Developer).where(
            models.Developer.email == "admin@test.sandbox"
        )
    )
    admin = result.scalar_one_or_none()
    if admin is None:
        # Fallback — tutorial-admin@theprotocol.cloud is also created by test_seed.
        result = await session.execute(
            select(models.Developer).where(
                models.Developer.email == "tutorial-admin@theprotocol.cloud"
            )
        )
        admin = result.scalar_one_or_none()
    return admin.id if admin else None


async def _seed_peer_registry_row(
    session: AsyncSession, ctx: dict, admin_dev_id: int
) -> Optional[int]:
    """Insert or update the single peer_registries row for the partner frame.
    Returns the peer_registries.id."""
    result = await session.execute(
        select(models.PeerRegistry).where(
            models.PeerRegistry.name == ctx["peer_name"]
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        # Keep trust-domain + bundle endpoint fresh (cheap re-alignment).
        existing.trust_domain = ctx["peer_td"]
        existing.spiffe_bundle_endpoint_url = ctx["peer_bundle_endpoint"]
        existing.peer_type = "frame"
        existing.status = "ACTIVE"
        existing.base_url = ctx["peer_base_url"]
        await session.flush()
        logger.info(f"peer_registries row for {ctx['peer_name']} updated (id={existing.id})")
        return existing.id

    row = models.PeerRegistry(
        owner_developer_id=admin_dev_id,
        name=ctx["peer_name"],
        description=f"Sandbox sibling frame (trust domain: {ctx['peer_td']})",
        base_url=ctx["peer_base_url"],
        admin_contact_email="admin@test.sandbox",
        status="ACTIVE",
        discovery_auth_info={"type": "internal_sandbox"},
        approved_at=datetime.datetime.now(datetime.timezone.utc),
        approved_by_developer_id=admin_dev_id,
        peer_type="frame",
        trust_domain=ctx["peer_td"],
        spiffe_bundle_endpoint_url=ctx["peer_bundle_endpoint"],
        hop_distance=1,
    )
    session.add(row)
    await session.flush()
    logger.info(f"peer_registries row for {ctx['peer_name']} created (id={row.id})")
    return row.id


async def _seed_synthetic_pending_invitation(
    session: AsyncSession, admin_dev_id: int
) -> Optional[str]:
    """
    P5 (2026-04-22): Seed a SYNTHETIC pending frame_invitation the api-tester
    can approve/reject/finalize-retry against.

    Uses trust_domain=`sandbox-synthetic-invite.test` (distinct from real
    sandbox-a.test / sandbox-b.test / any probe-reachable domain) so the row
    can stay `pending` indefinitely without tripping on the auto-probe
    machinery. Test workflow:
      - admin GET /admin/federation/frame-invitations/{id}  → 200 detail view
      - admin POST .../{id}/approve  → will fail at SPIRE-bundle-fetch step
        since the synthetic domain isn't reachable, but the FIRST stages
        (row lookup + status transition validation) exercise correctly
      - admin POST .../{id}/reject   → 200, row → status=rejected
      - admin POST .../{id}/finalize-retry → needs status=approved+pending
    Idempotent: if the row already exists in any non-terminal state (pending
    or approved), keep it. If in terminal state (rejected/revoked), recreate.
    Returns the invitation id.
    """
    SYN_TD = "sandbox-synthetic-invite.test"
    result = await session.execute(
        select(models.FrameInvitation).where(
            models.FrameInvitation.initiator_trust_domain == SYN_TD
        )
    )
    existing = result.scalar_one_or_none()
    now = datetime.datetime.now(datetime.timezone.utc)
    if existing is not None and existing.status in ("pending", "approved"):
        logger.info(
            f"synthetic pending frame_invitation already exists "
            f"(id={existing.id}, status={existing.status}) — skip"
        )
        return existing.id

    if existing is not None:
        # Terminal state (rejected/revoked/completed) — reset back to pending
        # so the api-tester can exercise approve/reject again.
        existing.status = "pending"
        existing.reviewed_by = None
        existing.reviewed_at = None
        existing.review_notes = None
        existing.rejection_reason = None
        existing.completed_at = None
        existing.revoked_by = None
        existing.revoked_at = None
        existing.revoked_reason = None
        existing.peer_registry_id = None
        existing.spire_bundle_imported_at = None
        existing.initiator_nonce = uuid4().hex  # fresh nonce for each reset
        await session.flush()
        logger.info(f"synthetic frame_invitation reset to pending (id={existing.id})")
        return existing.id

    inv_id = str(uuid4())
    inv = models.FrameInvitation(
        id=inv_id,
        initiator_trust_domain=SYN_TD,
        initiator_bundle_endpoint_url=f"https://{SYN_TD}:8443",
        initiator_federation_endpoint_url=f"https://{SYN_TD}:18443",
        initiator_event_store_url=f"https://{SYN_TD}:8200",
        initiator_name="Sandbox Synthetic (api-tester fixture)",
        initiator_contact_email="synthetic@sandbox-synthetic-invite.test",
        initiator_description="P5 synthetic fixture for frame_invitations tests — not a real peer",
        initiator_nonce=uuid4().hex,
        status="pending",
    )
    session.add(inv)
    await session.flush()
    logger.info(f"synthetic pending frame_invitation created (id={inv_id})")
    return inv_id


async def _seed_frame_invitation_row(
    session: AsyncSession, ctx: dict, admin_dev_id: int, peer_registry_id: Optional[int]
) -> None:
    """Mark the WS3 handshake as completed between our frame and the partner."""
    result = await session.execute(
        select(models.FrameInvitation).where(
            models.FrameInvitation.initiator_trust_domain == ctx["peer_td"]
        )
    )
    existing = result.scalar_one_or_none()
    now = datetime.datetime.now(datetime.timezone.utc)
    if existing is not None:
        if existing.status != "completed":
            existing.status = "completed"
            existing.reviewed_by = admin_dev_id
            existing.reviewed_at = now
            existing.completed_at = now
            existing.spire_bundle_imported_at = now
            existing.peer_registry_id = peer_registry_id
            await session.flush()
            logger.info(f"frame_invitations row for {ctx['peer_td']} marked completed")
        else:
            logger.info(f"frame_invitations row for {ctx['peer_td']} already completed (skip)")
        return

    inv = models.FrameInvitation(
        id=str(uuid4()),
        initiator_trust_domain=ctx["peer_td"],
        initiator_bundle_endpoint_url=ctx["peer_bundle_endpoint"],
        initiator_federation_endpoint_url=ctx["peer_bundle_endpoint"],
        initiator_event_store_url=ctx["peer_es_url"],
        initiator_name=ctx["peer_name"],
        initiator_contact_email="admin@test.sandbox",
        initiator_description=f"Sandbox sibling frame (bootstrap auto-seed)",
        initiator_nonce=uuid4().hex,
        status="completed",
        reviewed_by=admin_dev_id,
        reviewed_at=now,
        completed_at=now,
        peer_registry_id=peer_registry_id,
        spire_bundle_imported_at=now,
    )
    session.add(inv)
    await session.flush()
    logger.info(f"frame_invitations row for {ctx['peer_td']} created (completed)")


# ----------------------------------------------------------------------------
# EventStore admin API seeding (runs against BOTH sandbox ES instances).
# ----------------------------------------------------------------------------

async def _es_post(client: httpx.AsyncClient, base: str, path: str, body: dict) -> None:
    """POST to EventStore admin API. Treat 409 Conflict as already-exists."""
    try:
        r = await client.post(
            f"{base}{path}",
            json=body,
            headers={"X-Internal-Key": ES_INTERNAL_KEY},
            timeout=5.0,
        )
        if r.status_code in (200, 201):
            logger.info(f"ES {base}{path} → {r.status_code} OK")
        elif r.status_code == 409:
            logger.info(f"ES {base}{path} → 409 (already exists, idempotent skip)")
        else:
            logger.warning(f"ES {base}{path} → {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"ES {base}{path} unreachable: {e}")


async def _seed_eventstore(ctx: dict) -> None:
    """Populate federation_operators + cross_frame_peers on BOTH sandbox ES."""
    ops_self = {
        "operator_name": ctx["self_name"],
        "spiffe_id": f"spiffe://{ctx['self_td']}",
        "status": "active",
    }
    ops_peer = {
        "operator_name": ctx["peer_name"],
        "spiffe_id": f"spiffe://{ctx['peer_td']}",
        "status": "active",
    }
    cross_peer = {
        "frame_id": f"sandbox-{ctx['peer_name'].split('-')[-1].lower()}",
        "url": ctx["peer_es_url"],
        "added_by": "sandbox_bootstrap",
    }

    async with httpx.AsyncClient() as client:
        for es_base in (ctx["self_es_url"], ctx["peer_es_url"]):
            await _es_post(client, es_base, "/api/v1/admin/federation-operators", ops_self)
            await _es_post(client, es_base, "/api/v1/admin/federation-operators", ops_peer)
            await _es_post(client, es_base, "/api/v1/admin/cross-frame-peers", cross_peer)


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------

async def run_bootstrap() -> int:
    ctx = _pair_context()
    if ctx is None:
        logger.info(
            f"REGISTRY_NAME='{REGISTRY_NAME}' is not a sandbox frame — skipping bootstrap."
        )
        return 0

    logger.info(f"Bootstrapping as {ctx['self_name']} ({ctx['self_td']}) — partner {ctx['peer_name']}")

    # --- DB phase ---
    engine = create_async_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with SessionLocal() as session:
            async with session.begin():
                admin_dev_id = await _get_admin_dev_id(session)
                if admin_dev_id is None:
                    logger.warning(
                        "No sandbox admin dev account found (test_seed must run first). "
                        "Skipping DB seeding this cycle."
                    )
                else:
                    peer_id = await _seed_peer_registry_row(session, ctx, admin_dev_id)
                    await _seed_frame_invitation_row(session, ctx, admin_dev_id, peer_id)
                    await _seed_synthetic_pending_invitation(session, admin_dev_id)
    except Exception as e:
        logger.warning(f"DB seeding hit an error (non-fatal): {e}")
    finally:
        await engine.dispose()

    # --- EventStore phase ---
    try:
        await _seed_eventstore(ctx)
    except Exception as e:
        logger.warning(f"EventStore seeding hit an error (non-fatal): {e}")

    logger.info("Sandbox bootstrap complete.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_bootstrap()))
