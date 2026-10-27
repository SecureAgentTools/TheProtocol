"""Frame federation invitations — sovereign frame bilateral handshake.

Revision ID: 0018_frame_invitations
Revises: 0017_peer_topology_last_seen

Adds `frame_invitations` table so a remote sovereign frame can POST "I'd like
to federate" to this frame. Admin reviews, approves or rejects. On approve, we
exchange SPIRE trust bundles bilaterally (no FederationLicense, no
OperatorApplication — frames are sovereign-by-trust-bundle per MODEL 3 of the
scaling doc).

Also adds `peer_registries.spiffe_bundle_endpoint_url` so we can re-fetch a
peer frame's bundle programmatically (today's Frame-B bundle is implicit via
the standard `/.well-known/spiffe/bundle` path; the new column lets us store a
non-standard path if a peer advertises one).

Event policies seeded (all emit_from_registry=true, ON CONFLICT DO NOTHING):
  - FrameInvitationRequested     — initiator POST landed, row created
  - FrameInvitationApproved      — admin approved + our SPIRE bundle set
  - FrameInvitationRejected      — admin rejected with reason
  - FrameFederationEstablished   — bilateral handshake completed both sides
  - FrameFederationRevoked       — admin tore down an established frame
  - FrameBundleRefreshed         — periodic bundle-pull heartbeat (skip_in_projection)
  - FrameTrustStale              — drift signal (skip_in_projection, per-day dedup)

Backfill: inserts a synthetic `frame_invitations` row for every existing
`peer_registries.peer_type='frame'` row so the admin UI shows a consistent
audit trail even for frames (like Frame-B) that pre-date this schema.

IDEMPOTENCY: migration_bridge.py re-stamps alembic_version to 0001_squash on
every boot — all post-squash migrations replay. Every op uses IF NOT EXISTS /
ON CONFLICT / WHERE NOT EXISTS guards so replay is a no-op.
"""

from alembic import op
from sqlalchemy import text


revision = "0018_frame_invitations"
down_revision = "0017_peer_topology_last_seen"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- peer_registries: new column (nullable, backwards-compatible) ---
    bind.execute(text("""
        ALTER TABLE peer_registries
          ADD COLUMN IF NOT EXISTS spiffe_bundle_endpoint_url VARCHAR(500) NULL
    """))

    # Backfill Frame-B's bundle endpoint URL to the standard SPIFFE path so
    # FrameTrustManager can re-fetch without custom config.
    bind.execute(text("""
        UPDATE peer_registries
           SET spiffe_bundle_endpoint_url =
               'https://frame-b.theprotocol.cloud:8443/.well-known/spiffe/bundle'
         WHERE peer_type = 'frame'
           AND (name ILIKE 'Frame-B' OR name ILIKE 'Frame B')
           AND spiffe_bundle_endpoint_url IS NULL
    """))

    # --- frame_invitations table ---
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS frame_invitations (
            id VARCHAR(36) PRIMARY KEY,
            initiator_trust_domain VARCHAR(255) NOT NULL,
            initiator_bundle_endpoint_url VARCHAR(500) NOT NULL,
            initiator_federation_endpoint_url VARCHAR(500) NOT NULL,
            initiator_event_store_url VARCHAR(500) NULL,
            initiator_name VARCHAR(255) NOT NULL,
            initiator_contact_email VARCHAR(255) NOT NULL,
            initiator_description TEXT,
            initiator_nonce VARCHAR(64) NOT NULL,
            initiator_ip VARCHAR(45),
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','approved','rejected','completed','revoked')),
            reviewed_by INTEGER REFERENCES developers(id),
            reviewed_at TIMESTAMPTZ,
            review_notes TEXT,
            rejection_reason TEXT,
            completed_at TIMESTAMPTZ,
            peer_registry_id INTEGER REFERENCES peer_registries(id) ON DELETE SET NULL,
            spire_bundle_imported_at TIMESTAMPTZ,
            revoked_by INTEGER REFERENCES developers(id),
            revoked_at TIMESTAMPTZ,
            revoked_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_frame_invitations_status
          ON frame_invitations(status)
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_frame_invitations_trust_domain
          ON frame_invitations(initiator_trust_domain)
    """))

    # --- frame_invitations: WS3.5 (2026-04-21) — event_store_url column ---
    # Idempotent ADD COLUMN IF NOT EXISTS covers the upgrade path from WS3
    # deployments where the table already exists without this column.
    # (Fresh deploys get it from CREATE TABLE above.)
    bind.execute(text("""
        ALTER TABLE frame_invitations
          ADD COLUMN IF NOT EXISTS initiator_event_store_url VARCHAR(500) NULL
    """))

    # --- Seed event policies ---
    for event_type, skip_proj, description in [
        ("FrameInvitationRequested",     False,
         "Remote frame POSTed a federation invitation. Pending admin review."),
        ("FrameInvitationApproved",      False,
         "Admin approved a frame invitation. SPIRE bundle imported on this side."),
        ("FrameInvitationRejected",      False,
         "Admin rejected a frame invitation with reason."),
        ("FrameFederationEstablished",   False,
         "Bilateral SPIRE bundle exchange completed. Frame is now a federated peer."),
        ("FrameFederationRevoked",       False,
         "Admin revoked federation with a frame. SPIRE bundle removed; peer deactivated."),
        ("FrameBundleRefreshed",         True,
         "Periodic bundle-pull heartbeat for a federated frame. Hourly idempotency."),
        ("FrameTrustStale",              True,
         "Frame trust bundle stale — SPIRE federation refresh overdue. Per-day dedup."),
    ]:
        bind.execute(text("""
            INSERT INTO event_emission_policies
              (event_type, emit_from_teg, emit_from_registry, skip_in_projection, description, updated_at)
            VALUES
              (:et, false, true, :skip, :desc, now())
            ON CONFLICT (event_type) DO NOTHING
        """), {"et": event_type, "skip": skip_proj, "desc": description})

    # --- Backfill synthetic frame_invitations for existing frame peers ---
    # Frame-B was added manually in 2026-04-02. Admin UI audit trail wants a
    # matching invitation row. Guarded by NOT EXISTS so this is idempotent.
    # reviewed_by: prefer the peer's approved_by_developer_id if present; fall
    # back to the first is_admin developer found; if none, leave NULL (FK allows).
    bind.execute(text("""
        INSERT INTO frame_invitations (
            id, initiator_trust_domain, initiator_bundle_endpoint_url,
            initiator_federation_endpoint_url, initiator_name, initiator_contact_email,
            initiator_nonce, status, reviewed_by, reviewed_at, completed_at,
            peer_registry_id, spire_bundle_imported_at, created_at, updated_at
        )
        SELECT
            'synthetic-legacy-frame-' || pr.id::text,
            pr.trust_domain,
            COALESCE(pr.spiffe_bundle_endpoint_url,
                     pr.base_url || '/.well-known/spiffe/bundle'),
            pr.base_url,
            pr.name,
            COALESCE(pr.admin_contact_email, 'legacy@' || COALESCE(pr.trust_domain, 'unknown.invalid')),
            'legacy-no-handshake',
            'completed',
            COALESCE(pr.approved_by_developer_id,
                     (SELECT id FROM developers WHERE is_admin = true ORDER BY id LIMIT 1)),
            pr.approved_at,
            pr.registered_at,
            pr.id,
            pr.registered_at,
            pr.registered_at,
            pr.registered_at
        FROM peer_registries pr
        WHERE pr.peer_type = 'frame'
          AND pr.trust_domain IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM frame_invitations fi WHERE fi.peer_registry_id = pr.id
          )
    """))


def downgrade() -> None:
    bind = op.get_bind()
    for et in (
        "FrameInvitationRequested",
        "FrameInvitationApproved",
        "FrameInvitationRejected",
        "FrameFederationEstablished",
        "FrameFederationRevoked",
        "FrameBundleRefreshed",
        "FrameTrustStale",
    ):
        bind.execute(text("DELETE FROM event_emission_policies WHERE event_type = :et"), {"et": et})
    bind.execute(text("DROP INDEX IF EXISTS ix_frame_invitations_trust_domain"))
    bind.execute(text("DROP INDEX IF EXISTS ix_frame_invitations_status"))
    bind.execute(text("DROP TABLE IF EXISTS frame_invitations"))
    bind.execute(text("ALTER TABLE peer_registries DROP COLUMN IF EXISTS spiffe_bundle_endpoint_url"))
